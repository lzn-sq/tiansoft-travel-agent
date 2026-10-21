import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from tools import calculator, check_policy

load_dotenv()

model = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
    temperature=0
)

tools = [calculator, check_policy]
agent_executor = create_react_agent(model, tools)

# 【修改这里】：增加 history 参数
def run_agent(query: str, history: list = None):
    if history is None:
        history = []
        
    # 1. 放入 System Prompt
    messages = [
        ("system", """你是一个严格的天软公司财务审核员。
        【必须遵守的规则】：
        1. 绝对不能自己心算，凡是涉及算总和，必须调用 `calculator` 工具，并将所有金额转换为纯数字表达式（如 '550+800+120'）。
        2. 必须调用 `check_policy` 工具核对标准。如果需要查多项，请多次调用该工具（如分别查'住宿'和'交通'）。
        3. 如果用户未说明城市级别，请默认按一线城市标准严格审核，并在回答中说明你的假设。
        4. 最终回答必须清晰列出：总金额、各项明细、是否超标、具体的合规建议。
        5. 如果用户补充了细节，请结合历史记录重新计算和判断。""")
    ]
    
    # 2. 把历史对话塞进去（这就是大模型的记忆）
    messages.extend(history)
    
    # 3. 把当前用户的最新问题加进去
    messages.append(("user", query))
    
    # 4. 调用 Agent
    result = agent_executor.invoke({"messages": messages})
    return result["messages"][-1].content