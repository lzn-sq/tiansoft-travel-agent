from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from agent_core import run_agent
from typing import List # 新增

app = FastAPI(title="天软差旅合规 Agent (DeepSeek版)")

# 定义历史消息的格式
class Message(BaseModel):
    role: str   # 只能是 "user" 或 "assistant"
    content: str

# 更新请求体，包含当前问题和历史记录
class QueryRequest(BaseModel):
    text: str
    history: List[Message] = []  # 默认为空列表

@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/chat")
async def chat(request: QueryRequest):
    # 把前端传过来的历史记录转换一下格式，传给 Agent
    history_list = []
    for msg in request.history:
        history_list.append((msg.role, msg.content))
    
    # 调用 Agent 时，把历史记录也传进去
    reply = run_agent(request.text, history_list)
    return {"reply": reply}