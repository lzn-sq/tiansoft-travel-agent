import os
import json
import time
import hmac
import base64
import hashlib

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

import models
from database import get_db

JWT_SECRET = os.getenv("JWT_SECRET", "tiansoft-dev-secret-change-me")
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_MINUTES", "1440")) * 60

_bearer = HTTPBearer(auto_error=False)


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    # bcrypt 只处理前 72 字节
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(username: str) -> str:
    header = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64e(
        json.dumps(
            {"sub": username, "exp": int(time.time()) + TOKEN_TTL_SECONDS},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _b64e(hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def decode_access_token(token: str) -> str | None:
    try:
        header, payload, signature = token.split(".")
    except ValueError:
        return None

    signing_input = f"{header}.{payload}".encode("ascii")
    expected = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    try:
        actual = _b64d(signature)
    except Exception:
        return None
    if not hmac.compare_digest(expected, actual):
        return None

    try:
        data = json.loads(_b64d(payload))
    except Exception:
        return None

    if data.get("exp", 0) < int(time.time()):
        return None
    username = data.get("sub")
    return username if isinstance(username, str) and username else None


def _unauthorized(detail: str = "登录状态已失效，请重新登录") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> models.User:
    if credentials is None:
        raise _unauthorized("缺少身份凭证")
    username = decode_access_token(credentials.credentials)
    if not username:
        raise _unauthorized()

    result = await db.execute(select(models.User).where(models.User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise _unauthorized()
    return user
