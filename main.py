from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from agent_core import run_agent_stream

app = FastAPI(title="天软差旅合规 Agent")

# 开启跨域，防止以后前端分离时报错
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Message(BaseModel):
    role: str
    content: str

class QueryRequest(BaseModel):
    text: str
    history: List[Message] = []

@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/chat/stream")
async def chat_stream(request: QueryRequest):
    # 转换历史格式
    history_list = [(msg.role, msg.content) for msg in request.history]
    
    return StreamingResponse(
        run_agent_stream(request.text, history_list), 
        media_type="text/event-stream"
    )