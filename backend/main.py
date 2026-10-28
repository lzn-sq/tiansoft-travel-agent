import os
import re
import json
import uuid
import asyncio
from datetime import datetime

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

load_dotenv()

from auth import create_access_token, get_current_user, hash_password, verify_password
from database import Base, engine, get_db
import crud
import models
import rag
from agent_core import run_agent_stream, sse_event
from rate_limit import auth_limiter, chat_limiter

app = FastAPI(title="天软差旅合规多智能体系统")

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost,http://127.0.0.1",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_background_tasks = set()


def _migrate_schema(conn) -> None:
    """兼容旧库：补充 sessions.user_id / title / updated_at 字段。"""
    columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(sessions)")}
    if "user_id" not in columns:
        conn.exec_driver_sql("ALTER TABLE sessions ADD COLUMN user_id INTEGER")
    if "title" not in columns:
        conn.exec_driver_sql("ALTER TABLE sessions ADD COLUMN title VARCHAR(120)")
    if "updated_at" not in columns:
        conn.exec_driver_sql("ALTER TABLE sessions ADD COLUMN updated_at DATETIME")
        conn.exec_driver_sql("UPDATE sessions SET updated_at = created_at WHERE updated_at IS NULL")


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_schema)

    # 后台预热向量库，避免首次对话等待；失败会自动降级为关键词检索
    if os.getenv("RAG_WARMUP", "1") == "1" and os.getenv("ZHIPU_API_KEY"):
        task = asyncio.create_task(asyncio.to_thread(rag.warmup))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


# ================= 请求体 =================

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=72)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=72)


class SessionCreateRequest(BaseModel):
    title: str | None = None


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _iso(value) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


# ================= 鉴权接口 =================

@app.post("/api/auth/register")
async def register(request: Request, payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    await auth_limiter.check(f"register:{_client_key(request)}")

    username = payload.username.strip()
    if await crud.get_user_by_username(db, username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已存在")

    await crud.create_user(db, username, hash_password(payload.password))
    return {
        "access_token": create_access_token(username),
        "token_type": "bearer",
        "username": username,
    }


@app.post("/api/auth/login")
async def login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    await auth_limiter.check(f"login:{_client_key(request)}")

    username = payload.username.strip()
    user = await crud.get_user_by_username(db, username)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    return {
        "access_token": create_access_token(username),
        "token_type": "bearer",
        "username": username,
    }


@app.get("/api/auth/me")
async def me(user: models.User = Depends(get_current_user)):
    return {"username": user.username, "created_at": _iso(user.created_at)}


# ================= 会话接口 =================

@app.post("/api/session")
async def create_session(
    payload: SessionCreateRequest | None = None,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = str(uuid.uuid4())
    title = (payload.title.strip()[:40] if payload and payload.title else None)
    await crud.create_session(db, session_id, user_id=user.id, title=title)
    return {"session_id": session_id}


@app.get("/api/sessions")
async def list_sessions(
    user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    sessions = await crud.list_sessions(db, user.id)
    return {
        "sessions": [
            {
                "id": item.id,
                "title": item.title or "新对话",
                "created_at": _iso(item.created_at),
                "updated_at": _iso(item.updated_at),
            }
            for item in sessions
        ]
    }


@app.get("/api/sessions/{session_id}/messages")
async def session_messages(
    session_id: str,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await crud.get_owned_session(db, session_id, user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    messages = await crud.get_messages(db, session_id)
    return {
        "session_id": session_id,
        "title": session.title or "新对话",
        "messages": [
            {
                "id": str(item.id),
                "role": item.role,
                "content": item.content,
                "created_at": _iso(item.created_at),
            }
            for item in messages
        ],
    }


@app.delete("/api/sessions/{session_id}")
async def remove_session(
    session_id: str,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await crud.get_owned_session(db, session_id, user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    await crud.delete_session(db, session_id)
    return {"ok": True}


# ================= 对话接口 =================

@app.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await chat_limiter.check(f"chat:{user.username}")

    session_id = request.session_id
    user_text = request.text.strip()
    if not user_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="消息不能为空")

    session = await crud.get_owned_session(db, session_id, user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    history = await crud.get_history(db, session_id)
    await crud.add_message(db, session_id, "user", user_text)

    async def event_generator():
        full_ai_reply = ""
        saved = False
        try:
            async with asyncio.timeout(180):
                async for chunk in run_agent_stream(user_text, history):
                    raw = chunk[len("data: "):].rstrip("\n") if chunk.startswith("data: ") else chunk
                    try:
                        content = json.loads(raw).get("text", "")
                    except Exception:
                        content = raw

                    if content:
                        full_ai_reply += content
                    yield chunk
        except asyncio.TimeoutError:
            yield sse_event("⚠️ 后端处理超时（超过 180 秒），请检查网络或重新发送。")
        except asyncio.CancelledError:
            # 用户主动中止或断开连接：保留已生成内容
            raise
        except Exception as e:
            yield sse_event(f"⚠️ 系统异常：{str(e)}")
        finally:
            if full_ai_reply and not saved:
                saved = True
                try:
                    await crud.add_message(db, session_id, "assistant", full_ai_reply)
                    match = re.search(r"PAY-[A-Z0-9]{6}", full_ai_reply)
                    if match:
                        await crud.create_payment_record(db, match.group(0), session_id)
                except Exception as e:
                    print(f"[Chat] 回复落库失败: {e}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
