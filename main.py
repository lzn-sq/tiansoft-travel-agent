import uuid
from fastapi import FastAPI, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from database import engine, Base, get_db
import models, crud
from agent_core import run_agent_stream

app = FastAPI(title="天软企业级 Agent")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# 启动时自动建表
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

class ChatRequest(BaseModel):
    session_id: str
    text: str

@app.get("/api/session")
async def create_new_session(db: AsyncSession = Depends(get_db)):
    """前端初始化时，请求分配一个唯一会话 ID"""
    session_id = str(uuid.uuid4())
    await crud.create_session(db, session_id)
    return {"session_id": session_id}

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    session_id = request.session_id
    user_text = request.text
    
    # 1. 先从数据库获取历史记录
    history = await crud.get_history(db, session_id)
    
    # 2. 保存用户的新消息入库
    await crud.add_message(db, session_id, "user", user_text)
    
    # 3. 定义一个生成器，包裹流式输出，并在流结束后保存 AI 回复
    async def event_generator():
        full_ai_reply = ""
        async for chunk in run_agent_stream(user_text, history):
            # 提取实际内容（去掉 data: 前缀）用于存库
            content = chunk.replace("data: ", "").strip()
            if content:
                full_ai_reply += content
            yield chunk
            
        # 流结束后，保存 AI 完整的回复
        if full_ai_reply:
            await crud.add_message(db, session_id, "assistant", full_ai_reply)

    return StreamingResponse(event_generator(), media_type="text/event-stream")