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

# search_train_info 只用于“车次信息待确认”节点，不暴露给审核 Agent，避免其擅自采用查询结果
TOOLS = [search_policy, calculate_allowance, train_downgrade]
audit_agent = create_react_agent(model, TOOLS)


class ExpenseForm(BaseModel):
    city: Optional[str] = None
    job_level: Optional[str] = None
    hotel_amount: Optional[float] = None
    hotel_nights: Optional[int] = None
    taxi_amount: Optional[float] = None
    train_no: Optional[str] = None
    train_price: Optional[float] = None
    depart_time: Optional[str] = None
    return_train_no: Optional[str] = None
    return_train_price: Optional[float] = None
    return_time: Optional[str] = None


class AgentState(TypedDict, total=False):
    messages: list
    form: dict
    missing: List[str]
    reply: str
    approved: bool
    payment_intent: bool
    pay_id: str
    pending_train_info: dict
    confirmed_train_info: dict


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


# 用户确认 AI 查询车次信息时的意图识别（仅在上一条助手消息为确认提示时生效）
_TRAIN_CONFIRM = re.compile(
    r"确认车次|车次信息|车次没问题|核对无误|(没问题|没错|正确|对的|可以|同意|是的|按这个|按查询结果|ok)",
    re.IGNORECASE,
)

# 车次待确认提示使用固定文案，便于下一轮从历史中解析出已查询到的值
_PENDING_HEADER = "车次信息待确认"
_PENDING_LEG = re.compile(
    r"(去程|返程)\s*([A-Za-z0-9]+)?｜发车时间："
    r"([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}|未查到)｜"
    r"二等座票价：([0-9]+(?:\.[0-9]+)?|未查到)"
)

# 搜索失败时不应把工具返回的提示文案当成车次信息
_SEARCH_FAIL = ("搜索工具未配置", "未搜索到", "搜索失败")


def _confirms_train(text: str) -> bool:
    if _wants_payment(text):
        return False
    return bool(_TRAIN_CONFIRM.search(text or ""))


def _pending_train_info(history: list) -> Optional[dict]:
    """若最近一条消息是车次待确认提示，解析出其中 AI 查询到的去程/返程信息。

    只认最后一条消息：一旦后续已产出核算结果或追问，旧的查询值不再被视为待确认。
    """
    if not history:
        return None
    role, content = history[-1]
    content = content or ""
    if role != "assistant" or _PENDING_HEADER not in content:
        return None
    legs = {}
    for match in _PENDING_LEG.finditer(content):
        key = "outbound" if match.group(1) == "去程" else "return"
        time_text = match.group(3)
        price_text = match.group(4)
        legs[key] = {
            "train_no": match.group(2) or None,
            "depart_time": None if time_text == "未查到" else time_text,
            "train_price": None if price_text == "未查到" else float(price_text),
        }
    return legs or None


def _mentions_train_values(text: str) -> bool:
    """用户本轮是否重新给出了发车时刻或票价（用于判断确认时是否保留用户的新值）。"""
    text = text or ""
    if re.search(r"[0-9]{1,2}[:：][0-9]{2}", text):
        return True
    return bool(re.search(r"票价|车票", text)) and bool(re.search(r"[0-9]", text))


def _apply_confirmed_train(form: dict, confirmed: Optional[dict], override: bool = False) -> dict:
    """用户确认后，用确认值补全抽取缺失的车次字段；默认保留用户本轮给出的值。"""
    if not confirmed:
        return form
    mapping = {
        "outbound": (("train_no", "train_no"), ("depart_time", "depart_time"), ("train_price", "train_price")),
        "return": (
            ("train_no", "return_train_no"),
            ("depart_time", "return_time"),
            ("train_price", "return_train_price"),
        ),
    }
    for leg, pairs in mapping.items():
        info = confirmed.get(leg) or {}
        for source, target in pairs:
            value = info.get(source)
            if value in (None, ""):
                continue
            if override or form.get(target) in (None, ""):
                form[target] = value
    return form


def _train_confirm_reply(legs: list) -> str:
    lines = ["🚄 **[车次信息待确认]**", ""]
    for leg in legs:
        price = leg.get("train_price")
        price_text = f"{price:g} 元" if isinstance(price, (int, float)) else "未查到"
        lines.append(
            f"- {leg['label']} {leg.get('train_no') or ''}｜"
            f"发车时间：{leg.get('depart_time') or '未查到'}｜二等座票价：{price_text}"
        )
    lines.extend(
        [
            "",
            "> ⚠️ 以上发车时间与票价来自 AI 联网查询，可能不准确，**未经您确认不会用于核算**。",
            "> 请核对后回复“确认车次信息”继续；如与实际不符，请直接告诉我正确的发车时间/票价。",
        ]
    )
    return "\n".join(lines)


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
  "train_no": "去程车次号",
  "train_price": 去程二等座票价(数字),
  "depart_time": "去程发车时间(YYYY-MM-DD HH:MM)",
  "return_train_no": "返程车次号",
  "return_train_price": 返程二等座票价(数字),
  "return_time": "返程时间(YYYY-MM-DD HH:MM)"
}}
未提及的字段填 null。以本轮用户最新消息为准；本轮未提及但历史中用户已明确给出的信息可以沿用。
去程车次填 train_no，返程车次填 return_train_no，两个车次号不能混填。
用户自称或落款职级时（如“我是经理”“确认车次信息，经理”），把该职级填入 job_level。
发车时间与票价只能取自用户消息：用户没有明确给出具体时刻/票价时对应字段填 null，
绝不能根据车次号、常识或助手的历史回复自行推断、默认或抄录；用户只给了一等座票价时 train_price 填 null。
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
    # 只有用户明确确认过的车次查询值才会被带入表单；用户本轮重新给出的值优先
    messages = state.get("messages") or []
    latest = messages[-1].content if messages else ""
    confirmed = state.get("confirmed_train_info")
    form = _apply_confirmed_train(
        form, confirmed, override=bool(confirmed) and not _mentions_train_values(latest)
    )
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


_DATE_MENTION = re.compile(r"(?:(\d{4})年)?(?:(\d{1,2})月)?(\d{1,2})日")


def _dates_from_message(text: str) -> List[str]:
    """从用户消息中按出现顺序解析“29日 / 10月29日 / 2026年10月29日”这类日期。"""
    today = datetime.now()
    dates = []
    for match in _DATE_MENTION.finditer(text or ""):
        year = int(match.group(1)) if match.group(1) else today.year
        month = int(match.group(2)) if match.group(2) else today.month
        day = int(match.group(3))
        if not match.group(1) and not match.group(2) and month < today.month:
            year += 1
        try:
            dates.append(datetime(year, month, day).strftime("%Y-%m-%d"))
        except ValueError:
            continue
    return dates


def _structured_train_info(raw: str, latest: str, label: str) -> Optional[dict]:
    """时刻表结构化数据可直接确定时刻与票价，无需模型再解析。"""
    if "来源：去哪儿时刻表" not in raw:
        return None
    time_match = re.search(r"发车时间：([0-9]{2}:[0-9]{2})", raw)
    price_match = re.search(r"二等座票价：([0-9]+(?:\.[0-9]+)?)", raw)
    price = float(price_match.group(1)) if price_match else None
    depart = None
    if time_match:
        dates = _dates_from_message(latest)
        index = 0 if label == "去程" else 1
        if index < len(dates):
            depart = f"{dates[index]} {time_match.group(1)}"
    return {"depart_time": depart, "train_price": price}


async def _parse_train_search(raw_results: str, state: AgentState, train_no: str, label: str) -> dict:
    """让模型只从联网搜索结果中提取发车时刻与票价，找不到就留空，不做任何补全。"""
    messages = state.get("messages") or []
    latest = messages[-1].content if messages else ""

    structured = _structured_train_info(raw_results, latest, label)
    if structured and structured.get("depart_time"):
        print(f" -> {label} {train_no} 时刻表解析: {structured}")
        return structured

    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    prompt = f"""当前时间：{now}
用户本轮消息：{latest}
本次查询：{label}车次 {train_no}
联网搜索结果：
{raw_results}

请只从搜索结果中提取车次 {train_no} 的发车时间与二等座票价，严格输出纯 JSON（不要 Markdown 标记）：
{{"depart_time": "YYYY-MM-DD HH:MM 或 null", "train_price": 数字或 null}}
规则：
1. 只有搜索结果明确给出该车次时刻时才填写发车时间；若只给出“时:分”（如 06:09），日期按用户本轮消息中对应的{label}出行日期（如“29日”“31日”）结合当前时间推算；
2. 搜索结果没有明确给出二等座票价时 train_price 填 null，不能用其他席别（一等座/商务座）票价代替；
3. 严禁依据常识、记忆或车次号编造时刻与票价，不确定一律填 null；不要输出任何解释。"""
    try:
        response = await model.ainvoke([SystemMessage(content=prompt)])
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        parsed = json.loads(content.strip())
    except Exception as e:
        print(f" -> 车次信息解析异常: {e}")
        return {}

    depart = parsed.get("depart_time")
    if not isinstance(depart, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}", depart):
        depart = None
    try:
        price = float(parsed.get("train_price")) if parsed.get("train_price") is not None else None
    except (TypeError, ValueError):
        price = None
    return {"depart_time": depart, "train_price": price}


async def train_confirm_node(state: AgentState) -> dict:
    """AI 查询到的车次时刻/票价必须先展示给用户确认，确认前不进入核算。"""
    print("正在执行：车次信息待确认...")
    form = state.get("form") or {}
    pending = state.get("pending_train_info") or {}
    pending_out = pending.get("outbound") or {}
    pending_ret = pending.get("return") or {}
    city = form.get("city")

    out_train = form.get("train_no") or pending_out.get("train_no")
    ret_train = form.get("return_train_no") or pending_ret.get("train_no")
    out_time = form.get("depart_time") or pending_out.get("depart_time")
    ret_time = form.get("return_time") or pending_ret.get("depart_time")

    out_price = form.get("train_price")
    if out_price in (None, ""):
        out_price = pending_out.get("train_price")
    ret_price = form.get("return_train_price")
    if ret_price in (None, ""):
        ret_price = pending_ret.get("train_price")

    if not pending:
        if out_train:
            raw = await asyncio.to_thread(
                search_train_info.invoke,
                {"depart_city": "", "arrive_city": city or "", "train_no": out_train},
            )
            if not any(marker in raw for marker in _SEARCH_FAIL):
                parsed = await _parse_train_search(raw, state, out_train, "去程")
                out_time = out_time or parsed.get("depart_time")
                if out_price in (None, ""):
                    out_price = parsed.get("train_price")
        if ret_train:
            raw = await asyncio.to_thread(
                search_train_info.invoke,
                {"depart_city": city or "", "arrive_city": "", "train_no": ret_train},
            )
            if not any(marker in raw for marker in _SEARCH_FAIL):
                parsed = await _parse_train_search(raw, state, ret_train, "返程")
                ret_time = ret_time or parsed.get("depart_time")
                if ret_price in (None, ""):
                    ret_price = parsed.get("train_price")

    legs = []
    if out_train or out_time or out_price not in (None, ""):
        legs.append({"label": "去程", "train_no": out_train, "depart_time": out_time, "train_price": out_price})
    if ret_train or ret_time or ret_price not in (None, ""):
        legs.append({"label": "返程", "train_no": ret_train, "depart_time": ret_time, "train_price": ret_price})

    others = [item for item in (state.get("missing") or []) if item != "发车时间"]
    if not legs:
        reply = "🔎 未识别到车次号。请提供去程/返程车次号（如 C2202），或直接提供发车时间和票价。"
    else:
        reply = _train_confirm_reply(legs)
        incomplete = [leg["label"] for leg in legs if not leg["depart_time"] or leg["train_price"] in (None, "")]
        if incomplete:
            reply += f"\n\n> 部分车次信息未查到（{'、'.join(incomplete)}），请直接补充对应发车时间/票价后我再核算。"

    if others:
        reply += "\n\n另需补充：\n" + "\n".join(f"- {item}" for item in others)
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
3. 交通费只能使用 form 中的 train_price（去程）与 return_train_price（返程），均为用户提供或用户已确认的二等座票价，
   不得调用联网搜索、也不得按常识估算；两项都有时合计写入明细，某项为 null 时注明“该段票价未提供，暂未计入”，不能编造金额；
   若用户说明乘坐一等座，按对应票价作为报销金额并注明“一等座按二等座票价报销，差价自理”；
4. 打车费核对单次 100 元、单日 200 元限额；
5. 若 return_time 不为 null，必须调用 calculate_allowance(depart_time_str, return_time_str) 计算补助；
   规则为 12:00 前出发计全天、12:00 后出发计半天、12:00 前返回计半天、12:00 后返回计全天；
   若 return_time 为 null，在明细中写“差旅补助：未提供返程时间，暂未计入”；
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
    form = state.get("form") or {}
    missing = state.get("missing") or []
    # 用户给出的车次，时刻/票价由 AI 主动查询并请用户确认，不要求用户自己填
    out_incomplete = form.get("train_no") and (
        not form.get("depart_time") or form.get("train_price") in (None, "")
    )
    ret_incomplete = form.get("return_train_no") and (
        not form.get("return_time") or form.get("return_train_price") in (None, "")
    )
    # 用户刚确认过车次信息时不再重复确认：必填项仍缺则追问，否则直接核算
    if (out_incomplete or ret_incomplete) and not state.get("confirmed_train_info"):
        return "train"
    return "ask" if missing else "audit"


def _route_after_audit(state: AgentState) -> str:
    if not state.get("approved"):
        return "end"
    return "pay" if state.get("payment_intent") else "confirm"


_builder = StateGraph(AgentState)
_builder.add_node("extract", extract_node)
_builder.add_node("validate", validate_node)
_builder.add_node("ask_more", ask_more_node)
_builder.add_node("train_confirm", train_confirm_node)
_builder.add_node("audit", audit_node)
_builder.add_node("confirm", confirm_node)
_builder.add_node("payment", payment_node)

_builder.set_entry_point("extract")
_builder.add_edge("extract", "validate")
_builder.add_conditional_edges(
    "validate", _route_after_validate, {"train": "train_confirm", "ask": "ask_more", "audit": "audit"}
)
_builder.add_edge("ask_more", END)
_builder.add_edge("train_confirm", END)
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

    # 车次查询结果只有在用户明确确认后才可用；未确认的查询值不进入模型上下文，避免被直接采用
    pending_train = _pending_train_info(history)
    confirmed_train = pending_train if pending_train and _confirms_train(query) else None

    langchain_history = []
    for role, content in history:
        if role == "assistant" and _PENDING_HEADER in (content or ""):
            continue
        langchain_history.append(
            HumanMessage(content=content) if role == "user" else AIMessage(content=content)
        )
    langchain_history.append(HumanMessage(content=query))

    try:
        result = await graph.ainvoke(
            {
                "messages": langchain_history,
                "payment_intent": payment_intent,
                "pending_train_info": pending_train,
                "confirmed_train_info": confirmed_train,
            },
            config={"recursion_limit": 30},
        )
        final_reply = result.get("reply") or "⚠️ 未能生成核算结果，请补充信息后重试。"

        async for chunk in _emit(final_reply):
            yield chunk

    except Exception as e:
        print(f"[Agent] 核心流程异常: {e}")
        yield sse_event(f"⚠️ 核心流程执行异常：{str(e)}")
