import os
import re
import uuid
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from tools import calculator, search_policy

load_dotenv()

model = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
    temperature=0
)

tools = [calculator, search_policy]
approval_agent = create_react_agent(model, tools)

# 极度强制的 Prompt，如果不带“审批通过”四个字，就视为失败
SYSTEM_PROMPT = """你是一个严格的天软公司财务审核员。
【重要任务】：
1. 必须先调用计算器算账，再查报销标准。
2. **绝对不要输出思考过程**。
3. 直接输出审核结果。
4. **特别注意**：如果你的结论是合规的，你的回复最后**必须**原样包含“审批通过”这四个字。如果不合规，请说明原因。
"""

async def run_agent_stream(query: str, history: list = None):
    if history is None:
        history = []
    
    messages = [("system", SYSTEM_PROMPT)] + history + [("user", query)]
    
    full_reply = ""
    
    async for event in approval_agent.astream_events({"messages": messages}, version="v2"):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content and "Thought:" not in content and "Action:" not in content:
                full_reply += content
                yield f"data: {content}\n\n"
                
    # 只要包含“审批通过”，立刻触发打款
    if "审批通过" in full_reply:
        pay_id = f"PAY-{uuid.uuid4().hex[:6].upper()}"
        
        # 【核心修复】：彻底干掉所有换行符，确保前端 100% 能接收到！
        payment_text = f"💸 [系统财务中心接管] 审批已通过，正在处理打款流程。打款单号：{pay_id}，预计 1 个工作日内到账。"
        
        # 打印日志，让你在终端里能亲眼看到它触发了
        print(f"\n======> 成功触发打款！单号：{pay_id}\n")
        
        yield f"data: {payment_text}\n\n"