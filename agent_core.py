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
    next_action: str  # 决定路由去哪个节点

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
    
    # 决定下一步动作
    next_action = "payment" if "审批通过" in last_message and "不予报销" not in last_message else "end"
    return {"messages": [AIMessage(content=last_message)], "next_action": next_action}

async def payment_node(state: AgentState):
    """打款节点：负责生成打款单"""
    pay_id = f"PAY-{uuid.uuid4().hex[:6].upper()}"
    payment_res = f"\n\n💸 **[财务打款 Agent 接管]**\n审批已通过，正在处理打款流程。\n打款单号：{pay_id}\n预计 1 个工作日内到账。"
    return {"messages": [AIMessage(content=payment_res)], "next_action": "end"}

# ================= 3. 组装状态图 =================
workflow = StateGraph(AgentState)

# 添加节点
workflow.add_node("approval", approval_node)
workflow.add_node("payment", payment_node)

# 设置入口
workflow.set_entry_point("approval")

# 设置条件路由边
def route_decision(state: AgentState):
    if state["next_action"] == "payment":
        return "payment"
    return END

workflow.add_conditional_edges("approval", route_decision, {"payment": "payment", END: END})
workflow.add_edge("payment", END)

# 编译图
multi_agent_graph = workflow.compile()

# ================= 4. 对外暴露的流式接口 =================
async def run_agent_stream(query: str, history: list):
    # 将历史记录转为 LangChain 消息格式
    langchain_history = []
    for role, content in history:
        if role == "user":
            langchain_history.append(HumanMessage(content=content))
        elif role == "assistant":
            langchain_history.append(AIMessage(content=content))
            
    langchain_history.append(HumanMessage(content=query))
    
    # 使用 astream_events 精细控制流
    async for event in multi_agent_graph.astream_events({"messages": langchain_history, "next_action": ""}, version="v2"):
        if event["event"] == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content and "Thought:" not in content and "Action:" not in content:
                yield f"data: {content}\n\n"