import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

# 默认使用 backend 目录下的 agent.db；Docker 中通过 DATABASE_URL 指向持久化卷
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agent.db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


# 获取数据库会话的依赖注入函数
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
