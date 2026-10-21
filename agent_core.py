import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from tools import calculator, search_policy

load_dotenv()

# 1. 接入 DeepSeek
model = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
    temperature=0
)

tools = [calculator, search_policy]
agent_executor = create_react_agent(model, tools)

# 2. 流式输出生成器
async def run_agent_stream(query: str, history: list = None):
    if history is None:
        history = []
    
    messages = [
        ("system", """你是一个高效、精准的天软公司财务审核员。
        【任务要求】：
        1. 必须先调用 `calculator` 工具计算总金额。
        2. 必须调用 `search_policy` 工具核对标准。
        3. 回答必须极其精简，先给结论，再列重点，严禁长篇大论。
        4. 绝对禁止输出 Markdown 表格，使用简短的列表（1. 2. 3.）即可。
        5. 如果违规，最多指出最核心的 2-3 个违规点。
        
        【输出格式规范】：
        📊 **总体花费：xxx 元**
        ✅ **审核结论：合规** (或 ❌ **审核结论：违规**)
        
        如果违规，补充：
        ⚠️ **违规明细：**
        1. [具体原因]
        2. [具体原因]
        """)
    ]
    messages.extend(history)
    messages.append(("user", query))
    
    # 使用 astream_events 进行流式生成
    async for event in agent_executor.astream_events({"messages": messages}, version="v1"):
        if event["event"] == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content:
                # 将文本以 SSE 格式产出
                yield f"data: {content}\n\n"