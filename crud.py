from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import Session, Message

async def create_session(db: AsyncSession, session_id: str):
    db_session = Session(id=session_id)
    db.add(db_session)
    await db.commit()
    return db_session

async def get_history(db: AsyncSession, session_id: str):
    # 获取最近 10 轮对话（防止 Token 爆炸）
    result = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.id.asc())
    )
    messages = result.scalars().all()
    # 转换为 LangChain 需要的格式
    return [(msg.role, msg.content) for msg in messages]

async def add_message(db: AsyncSession, session_id: str, role: str, content: str):
    db_msg = Message(session_id=session_id, role=role, content=content)
    db.add(db_msg)
    await db.commit()
    return db_msg