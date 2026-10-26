from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

# 使用 SQLite 异步驱动
DATABASE_URL = "sqlite+aiosqlite:///./agent.db"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# 获取数据库会话的依赖注入函数
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session