import os
import uuid
from typing import TypedDict, Annotated, List
import operator
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent
from tools import calculator, search_policy

load_dotenv()

# 初始化模型
model = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
    temperature=0
)

# ================= 1. 定义状态结构 =================
class AgentState(TypedDict):
    messages: Annotated[List, operator.add]

# ================= 2. 定义 Agent 节点 =================
# 审批 Agent（带工具）
approval_tools = [calculator, search_policy]
approval_executor = create_react_agent(model, approval_tools)

async def approval_node(state: AgentState):
    """审批节点：负责查账与合规判定"""
    system_msg = SystemMessage(content="""你是严格的天软财务审批Agent。
    1. 必须调用工具算账和查制度。
    2. 如果合规，输出中必须包含“审批通过”四个字。
    3. 如果违规，输出中说明原因并包含“不予报销”四个字。""")
    
    result = await approval_executor.ainvoke({"messages": [system_msg] + state["messages"]})
    last_message = result["messages"][-1].content
    return {"messages": [AIMessage(content=last_message)]}

async def payment_node(state: AgentState):
    """打款节点：负责生成打款单"""
    pay_id = f"PAY-{uuid.uuid4().hex[:6].upper()}"
    payment_res = f"\n\n💸 **[财务打款 Agent 接管]**\n审批已通过，正在处理打款流程。\n打款单号：{pay_id}\n预计 1 个工作日内到账。"
    return {"messages": [AIMessage(content=payment_res)]}

# ================= 3. 组装状态图 =================
# 审核 Agent：只做合规审核，不涉及打款
review_workflow = StateGraph(AgentState)
review_workflow.add_node("approval", approval_node)
review_workflow.set_entry_point("approval")
review_workflow.add_edge("approval", END)
review_agent = review_workflow.compile()

# 打款 Agent：只负责生成打款单，由调度逻辑单独调用
payment_workflow = StateGraph(AgentState)
payment_workflow.add_node("payment", payment_node)
payment_workflow.set_entry_point("payment")
payment_workflow.add_edge("payment", END)
payment_agent = payment_workflow.compile()

# ================= 4. 判断用户是否要求发起打款 =================
async def wants_payment(query: str) -> bool:
    """区分“审核是否合规”和“要求报销/打款”，避免审核时误触发打款 Agent"""
    try:
        result = await model.ainvoke([
            SystemMessage(content="""判断用户是否在要求执行报销/打款操作。
    只是咨询制度、询问标准、要求审核是否合规、询问能否报销时，回答 REVIEW。
    明确要求“帮我报销”“发起打款”“提交报销”“走打款流程”时，回答 PAY。
    只回答 REVIEW 或 PAY，不要输出其他内容。"""),
            HumanMessage(content=query),
        ])
        return "PAY" in result.content.upper() and "REVIEW" not in result.content.upper()
    except Exception:
        # 判定失败时默认只审核，不误触发打款
        return False

# ================= 5. 对外暴露的流式接口 =================
async def run_agent_stream(query: str, history: list):
    # 将历史记录转为 LangChain 消息格式
    langchain_history = []
    for role, content in history:
        if role == "user":
            langchain_history.append(HumanMessage(content=content))
        elif role == "assistant":
            langchain_history.append(AIMessage(content=content))
            
    langchain_history.append(HumanMessage(content=query))
    state = {"messages": langchain_history}
    
    # 1) 先调用审核 Agent
    review_text = ""
    async for event in review_agent.astream_events(state, version="v2"):
        if event["event"] == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content and "Thought:" not in content and "Action:" not in content:
                review_text += content
                yield f"data: {content}\n\n"
    
    # 2) 只有用户明确要求打款，且审核通过时，才调用打款 Agent
    approved = "审批通过" in review_text and "不予报销" not in review_text
    if approved and await wants_payment(query):
        async for event in payment_agent.astream_events(state, version="v2"):
            if event["event"] == "on_chain_end" and event.get("name") == "payment":
                output = event["data"].get("output") or {}
                for message in output.get("messages", []):
                    content = message.content if isinstance(message.content, str) else ""
                    # 去掉首尾换行，避免内容里的 "\n\n" 被前端当成 SSE 事件分隔符而丢弃
                    content = content.strip()
                    if content:
                        yield f"data: {content}\n\n"