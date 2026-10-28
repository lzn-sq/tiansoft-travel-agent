import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# 必须在导入 main 之前设置，database / auth / rag 在导入时读取环境变量
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_agent.db"
os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["ZHIPU_API_KEY"] = ""
os.environ["TAVILY_API_KEY"] = ""
os.environ["JWT_SECRET"] = "test-secret"
os.environ["RAG_WARMUP"] = "0"
os.environ["CHAT_RATE_LIMIT"] = "1000"
os.environ["AUTH_RATE_LIMIT"] = "1000"

DB_FILE = BACKEND_DIR / "test_agent.db"


@pytest.fixture(scope="session", autouse=True)
def clean_database():
    if DB_FILE.exists():
        DB_FILE.unlink()
    yield
    try:
        DB_FILE.unlink()
    except OSError:
        pass


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def auth_headers(client):
    credentials = {"username": "tester", "password": "secret123"}
    client.post("/api/auth/register", json=credentials)
    response = client.post("/api/auth/login", json=credentials)
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def other_auth_headers(client):
    credentials = {"username": "other_user", "password": "secret123"}
    client.post("/api/auth/register", json=credentials)
    response = client.post("/api/auth/login", json=credentials)
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
