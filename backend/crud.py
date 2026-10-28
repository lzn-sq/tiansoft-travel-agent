import os
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete

import models

# 历史裁剪参数：默认只取最近 12 条、总字符数 6000
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "12"))
HISTORY_MAX_CHARS = int(os.getenv("HISTORY_MAX_CHARS", "6000"))
HISTORY_MESSAGE_CHARS = int(os.getenv("HISTORY_MESSAGE_CHARS", "2000"))


# ---------------- 用户 ----------------

async def get_user_by_username(db: AsyncSession, username: str) -> Optional[models.User]:
    result = await db.execute(select(models.User).where(models.User.username == username))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, username: str, password_hash: str) -> models.User:
    user = models.User(username=username, password_hash=password_hash)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ---------------- 会话 ----------------

async def create_session(
    db: AsyncSession, session_id: str, user_id: Optional[int] = None, title: Optional[str] = None
) -> models.Session:
    now = datetime.utcnow()
    db_session = models.Session(id=session_id, user_id=user_id, title=title, updated_at=now)
    db.add(db_session)
    await db.commit()
    return db_session


async def get_owned_session(
    db: AsyncSession, session_id: str, user_id: int
) -> Optional[models.Session]:
    result = await db.execute(
        select(models.Session).where(
            models.Session.id == session_id, models.Session.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def list_sessions(db: AsyncSession, user_id: int) -> List[models.Session]:
    result = await db.execute(
        select(models.Session)
        .where(models.Session.user_id == user_id)
        .order_by(models.Session.updated_at.desc())
        .limit(100)
    )
    return list(result.scalars().all())


async def get_messages(db: AsyncSession, session_id: str) -> List[models.Message]:
    result = await db.execute(
        select(models.Message)
        .where(models.Message.session_id == session_id)
        .order_by(models.Message.id.asc())
    )
    return list(result.scalars().all())


async def delete_session(db: AsyncSession, session_id: str) -> None:
    await db.execute(
        delete(models.PaymentRecord).where(models.PaymentRecord.session_id == session_id)
    )
    await db.execute(delete(models.Session).where(models.Session.id == session_id))
    await db.commit()


# ---------------- 消息 ----------------

async def get_history(db: AsyncSession, session_id: str) -> List[Tuple[str, str]]:
    """返回裁剪后的历史 [(role, content)]，从旧到新。"""
    result = await db.execute(
        select(models.Message)
        .where(models.Message.session_id == session_id)
        .order_by(models.Message.id.desc())
        .limit(HISTORY_LIMIT)
    )
    messages = list(reversed(result.scalars().all()))

    selected: List[Tuple[str, str]] = []
    total_chars = 0
    for msg in reversed(messages):
        content = msg.content or ""
        if len(content) > HISTORY_MESSAGE_CHARS:
            content = content[:HISTORY_MESSAGE_CHARS] + "…"
        if selected and total_chars + len(content) > HISTORY_MAX_CHARS:
            break
        selected.append((msg.role, content))
        total_chars += len(content)
    return list(reversed(selected))


async def add_message(db: AsyncSession, session_id: str, role: str, content: str):
    db_msg = models.Message(session_id=session_id, role=role, content=content)
    db.add(db_msg)

    # 同步会话更新时间；首条用户消息作为会话标题
    session = await db.get(models.Session, session_id)
    if session is not None:
        session.updated_at = datetime.utcnow()
        if role == "user" and not session.title:
            session.title = content.strip().replace("\n", " ")[:40] or "新对话"

    await db.commit()
    return db_msg


async def create_payment_record(db: AsyncSession, pay_id: str, session_id: str):
    record = models.PaymentRecord(pay_id=pay_id, session_id=session_id)
    db.add(record)
    await db.commit()
    return record
