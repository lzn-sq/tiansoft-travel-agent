import os
import json
import re
import uuid
import asyncio
from datetime import datetime
from typing import TypedDict, List, Optional

from pydantic import BaseModel
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent

from tools import search_policy, calculate_allowance, train_downgrade, search_train_info

load_dotenv()

model = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
    temperature=0,
    timeout=60,
    max_retries=2,
)

TOOLS = [search_policy, calculate_allowance, train_downgrade, search_train_info]
audit_agent = create_react_agent(model, TOOLS)


class ExpenseForm(BaseModel):
    city: Optional[str] = None
    job_level: Optional[str] = None
    hotel_amount: Optional[float] = None
    hotel_nights: Optional[int] = None
    taxi_amount: Optional[float] = None
    train_no: Optional[str] = None
    depart_time: Optional[str] = None
    return_time: Optional[str] = None


class AgentState(TypedDict, total=False):
    messages: list
    form: dict
    missing: List[str]
    reply: str
    approved: bool
    payment_intent: bool
    pay_id: str


REQUIRED_FIELDS = {
    "city": "出差目的地",
    "job_level": "职级",
    "hotel_amount": "住宿总额",
    "hotel_nights": "住宿晚数",
    "depart_time": "发车时间",
}

# 只有用户明确表达打款意愿时才进入打款节点，避免核算后擅自打款
_PAYMENT_INTENT = re.compile(
    r"(确认|同意|提交|申请|立即|直接|请|帮我|给我|开始|进行|办理|发起|可以|那就|现在)\s*(打款|付款|支付)"
    r"|打款吧|出款|confirm\s*pay|pay\s*now",
    re.IGNORECASE,
)


def _wants_payment(text: str) -> bool:
    return bool(_PAYMENT_INTENT.search(text or ""))


# ================= 节点实现 =================

async def extract_node(state: AgentState) -> dict:
    print("\n[1/4] 正在执行：提取信息...")
    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    prompt = f"""当前时间：{now}。
请从用户的对话中提取本次差旅报销信息，严格输出纯 JSON 格式（不要任何 Markdown 标记）：
{{
  "city": "目的地城市",
  "job_level": "职级",
  "hotel_amount": 住宿费总额(数字),
  "hotel_nights": 住宿晚数(数字),
  "taxi_amount": 打车费总额(数字),
  "train_no": "车次号",
  "depart_time": "发车时间(YYYY-MM-DD HH:MM)",
  "return_time": "返程时间(YYYY-MM-DD HH:MM)"
}}
未提及的字段填 null。以本轮用户最新消息为准；本轮未提及但历史中已明确的信息可以沿用。
若用户给出返程时间但没给日期（如“回来的时候下午三点”），结合“出差 N 天”或出发日期推算返程日期，
补全为 YYYY-MM-DD HH:MM；无法确定时填 null。"""
    try:
        response = await model.ainvoke([SystemMessage(content=prompt)] + state.get("messages", []))
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        form_dict = json.loads(content.strip())
        form = ExpenseForm(**form_dict).model_dump()
        print(f" -> 提取成功: {form}")
    except Exception as e:
        print(f" -> 提取异常: {e}")
        form = ExpenseForm().model_dump()
    return {"form": form}


def validate_node(state: AgentState) -> dict:
    print("[2/4] 正在执行：校验必填项...")
    form = state.get("form") or {}
    missing = [
        label for key, label in REQUIRED_FIELDS.items() if form.get(key) in (None, "")
    ]
    print(f" -> 缺失字段: {missing}")
    return {"missing": missing}


def ask_more_node(state: AgentState) -> dict:
    missing = state.get("missing") or []
    reply = "⚠️ 缺失信息，无法精准核算。请补充：\n" + "\n".join(f"- {item}" for item in missing)
    return {"reply": reply}


async def audit_node(state: AgentState) -> dict:
    print("[3/4] 正在执行：审核 Agent 核算...")
    form = state.get("form") or {}
    prompt = f"""你是一名严格的差旅费用审核员。信息已齐全，请依据以下数据核算总账：
{form}

要求：
1. 先调用 search_policy，分别检索住宿标准、交通/打车标准、补助标准；
2. 住宿：hotel_amount 是本次住宿总费用（不是单晚价格），单晚价格 = hotel_amount / hotel_nights；
   按城市等级与职级核对限额，超标部分需明确说明由个人自理；
   未超标时住宿明细金额必须等于 hotel_amount。例如 hotel_amount=630、hotel_nights=2、单晚 315 元未超 600 元/晚，
   则写“住宿：630 元”，不能写成 600 元或 1200 元；
3. 打车费核对单次 100 元、单日 200 元限额；
4. 若 return_time 不为 null，必须调用 calculate_allowance(depart_time_str, return_time_str) 计算补助；
   规则为 12:00 前出发计全天、12:00 后出发计半天，12:00 前返回计半天、12:00 后返回计全天；
   若 return_time 为 null，在明细中写“差旅补助：未提供返程时间，暂未计入”；
5. 若涉及一等座，调用 train_downgrade 计算降级报销。
6. 直接给出最终结果，不要输出中间试算、笔误或自我更正过程。

【输出格式】（必须包含总计报销一行）：
📊 **费用明细：**
- 交通：xxx元
- 住宿：xxx元
- 打车：xxx元
- 差旅补助：xxx元
✅ **总计报销：xxx元**"""
    try:
        result = await audit_agent.ainvoke(
            {"messages": [SystemMessage(content=prompt)] + state.get("messages", [])},
            config={"recursion_limit": 30},
        )
        reply = result["messages"][-1].content or "⚠️ 审核未生成有效结果，请重试。"
    except Exception as e:
        print(f" -> 核算异常: {e}")
        reply = f"⚠️ 计算阶段异常：{e}"

    return {"reply": reply, "approved": "总计报销" in reply}


def payment_node(state: AgentState) -> dict:
    print("[4/4] 正在执行：打款 Agent...")
    pay_id = f"PAY-{uuid.uuid4().hex[:6].upper()}"
    reply = (state.get("reply") or "") + f"\n\n💸 **[财务中心]** 打款成功，单号：{pay_id}。\n\n"
    return {"reply": reply, "pay_id": pay_id}


def confirm_node(state: AgentState) -> dict:
    """核算完成但用户尚未明确要求打款：只提示，不出单。"""
    reply = (state.get("reply") or "") + (
        "\n\n> 以上为核算结果，**尚未打款**。请核对金额；如确认打款，请直接回复“确认打款”。"
    )
    return {"reply": reply, "approved": state.get("approved", False)}


# ================= 状态图编排 =================

def _route_after_validate(state: AgentState) -> str:
    return "ask" if state.get("missing") else "audit"


def _route_after_audit(state: AgentState) -> str:
    if not state.get("approved"):
        return "end"
    return "pay" if state.get("payment_intent") else "confirm"


_builder = StateGraph(AgentState)
_builder.add_node("extract", extract_node)
_builder.add_node("validate", validate_node)
_builder.add_node("ask_more", ask_more_node)
_builder.add_node("audit", audit_node)
_builder.add_node("confirm", confirm_node)
_builder.add_node("payment", payment_node)

_builder.set_entry_point("extract")
_builder.add_edge("extract", "validate")
_builder.add_conditional_edges("validate", _route_after_validate, {"ask": "ask_more", "audit": "audit"})
_builder.add_edge("ask_more", END)
_builder.add_conditional_edges(
    "audit", _route_after_audit, {"pay": "payment", "confirm": "confirm", "end": END}
)
_builder.add_edge("confirm", END)
_builder.add_edge("payment", END)

graph = _builder.compile()


# ================= 流式输出 =================

def sse_event(text: str) -> str:
    """封装一条完整的 SSE 事件。用 JSON 编码，避免正文中的换行破坏事件边界。"""
    return f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"


_TOTAL_AMOUNT = re.compile(r"总计报销[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)\s*元")


def _last_approved_total(history: list) -> Optional[str]:
    """从历史里找到最近一次审核通过的总计金额，用于“确认打款”时免重复抽取。"""
    for role, content in reversed(history):
        if role != "assistant" or "总计报销" not in (content or ""):
            continue
        match = _TOTAL_AMOUNT.search(content)
        if match:
            return match.group(1)
    return None


async def _emit(text: str):
    for char in text:
        yield sse_event(char)
        await asyncio.sleep(0.008)


async def run_agent_stream(query: str, history: list):
    # 前端已用 loading 状态占位，稍等一下确保连接第一时间有响应
    await asyncio.sleep(0.05)

    payment_intent = _wants_payment(query)
    if payment_intent:
        total = _last_approved_total(history)
        if total:
            # 上一轮已核算且用户现在明确确认打款：直接出款，避免重新抽取导致漏字段
            pay_id = f"PAY-{uuid.uuid4().hex[:6].upper()}"
            reply = (
                f"✅ 已确认按上次核算结果打款，本次报销 **{total} 元**。\n\n"
                f"💸 **[财务中心]** 打款成功，单号：{pay_id}。\n\n"
            )
            async for chunk in _emit(reply):
                yield chunk
            return

    langchain_history = []
    for role, content in history:
        langchain_history.append(
            HumanMessage(content=content) if role == "user" else AIMessage(content=content)
        )
    langchain_history.append(HumanMessage(content=query))

    try:
        result = await graph.ainvoke(
            {"messages": langchain_history, "payment_intent": payment_intent},
            config={"recursion_limit": 30},
        )
        final_reply = result.get("reply") or "⚠️ 未能生成核算结果，请补充信息后重试。"

        async for chunk in _emit(final_reply):
            yield chunk

    except Exception as e:
        print(f"[Agent] 核心流程异常: {e}")
        yield sse_event(f"⚠️ 核心流程执行异常：{str(e)}")
