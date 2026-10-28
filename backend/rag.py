import os
import re
import time
import hashlib
import threading
from pathlib import Path
from typing import List

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
POLICY_PATH = BASE_DIR / "policy.txt"
CHROMA_DIR = os.getenv("CHROMA_DIR", str(BASE_DIR / "chroma_db"))
COLLECTION_NAME = "policy_chunks_v1"

ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
EMBED_MODEL = os.getenv("EMBED_MODEL", "embedding-2")
EMBED_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"

RETRY_SECONDS = int(os.getenv("RAG_RETRY_SECONDS", "300"))

_lock = threading.Lock()
_collection = None
_next_retry_at = 0.0


def load_chunks() -> List[str]:
    """按章节切分制度文本，过长章节再按行聚合，单块不超过 500 字。"""
    if not POLICY_PATH.exists():
        return []
    text = POLICY_PATH.read_text(encoding="utf-8").strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: List[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= 500:
            chunks.append(paragraph)
            continue
        buffer = ""
        for line in paragraph.splitlines():
            if buffer and len(buffer) + len(line) + 1 > 500:
                chunks.append(buffer.strip())
                buffer = line
            else:
                buffer = f"{buffer}\n{line}" if buffer else line
        if buffer.strip():
            chunks.append(buffer.strip())
    return chunks


def _chunk_id(chunk: str) -> str:
    return hashlib.sha1(chunk.encode("utf-8")).hexdigest()[:16]


def embed_texts(texts: List[str]) -> List[List[float]]:
    if not ZHIPU_API_KEY:
        raise RuntimeError("未配置 ZHIPU_API_KEY")

    embeddings: List[List[float]] = []
    headers = {"Authorization": f"Bearer {ZHIPU_API_KEY}"}
    for start in range(0, len(texts), 32):
        batch = texts[start : start + 32]
        response = httpx.post(
            EMBED_URL,
            headers=headers,
            json={"model": EMBED_MODEL, "input": batch},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        items = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        if len(items) != len(batch):
            raise RuntimeError("embedding 返回数量与输入不一致")
        embeddings.extend([item["embedding"] for item in items])
    return embeddings


def _ensure_collection():
    """首次使用时构建 Chroma 集合；失败则 5 分钟内不再重试，直接走关键词降级。"""
    global _collection, _next_retry_at

    if _collection is not None:
        return _collection
    if time.time() < _next_retry_at:
        return None

    with _lock:
        if _collection is not None:
            return _collection
        if time.time() < _next_retry_at:
            return None

        try:
            chunks = load_chunks()
            if not chunks:
                raise RuntimeError("policy.txt 不存在或为空")

            import chromadb

            ids = [_chunk_id(chunk) for chunk in chunks]
            client = chromadb.PersistentClient(path=CHROMA_DIR)
            collection = client.get_or_create_collection(
                COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
            )

            existing_docs = collection.get(ids=ids, include=["documents"]).get("documents") or []
            if existing_docs != chunks:
                # 切分规则变化或首次构建：重建集合，避免残留旧向量
                if collection.count() > 0:
                    client.delete_collection(COLLECTION_NAME)
                    collection = client.get_or_create_collection(
                        COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
                    )
                embeddings = embed_texts(chunks)
                collection.upsert(
                    ids=ids,
                    documents=chunks,
                    embeddings=embeddings,
                    metadatas=[{"source": "policy.txt", "chunk": index} for index in range(len(chunks))],
                )
                print(f"[RAG] 制度向量库构建完成，共 {len(chunks)} 块")

            _collection = collection
        except Exception as exc:  # 网络/密钥/依赖问题都降级
            print(f"[RAG] 向量检索不可用，降级为关键词检索：{exc}")
            _collection = None
            _next_retry_at = time.time() + RETRY_SECONDS

    return _collection


def warmup() -> None:
    """启动时预热，避免首次对话等待向量构建。"""
    _ensure_collection()


def _bigrams(text: str) -> set:
    normalized = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", text)
    return {normalized[i : i + 2] for i in range(len(normalized) - 1)}


def keyword_search(query: str, k: int = 4) -> str:
    chunks = load_chunks()
    if not chunks:
        return "未找到制度文件。"

    query = (query or "").strip()
    if not query:
        return "\n\n---\n\n".join(chunks[:k])

    terms = re.findall(r"[\u4e00-\u9fa5]{2,}|[A-Za-z0-9]{2,}", query)
    query_grams = _bigrams(query)

    scored = []
    for index, chunk in enumerate(chunks):
        score = sum(3 for term in terms if term in chunk) + len(query_grams & _bigrams(chunk))
        scored.append((score, index, chunk))

    scored.sort(key=lambda item: (-item[0], item[1]))
    picked = [chunk for score, _, chunk in scored[:k] if score > 0]
    if not picked:
        picked = [chunk for _, _, chunk in scored[:k]]
    return "\n\n---\n\n".join(picked)


def search(query: str, k: int = 4) -> str:
    """优先向量检索；任何异常都回退到关键词检索，保证核算流程不中断。"""
    query = (query or "").strip()
    collection = _ensure_collection()

    if collection is not None and query:
        try:
            count = collection.count()
            if count > 0:
                query_embedding = embed_texts([query])[0]
                result = collection.query(
                    query_embeddings=[query_embedding], n_results=min(k, count)
                )
                documents = (result.get("documents") or [[]])[0]
                if documents:
                    return "\n\n---\n\n".join(documents)
        except Exception as exc:
            print(f"[RAG] 向量查询失败，改用关键词检索：{exc}")

    return keyword_search(query, k)
