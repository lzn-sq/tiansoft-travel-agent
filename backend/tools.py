import re
import os
from langchain_core.tools import tool
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from dotenv import load_dotenv

load_dotenv()

# 初始化 ChromaDB
def get_vectorstore():
    # 如果没有，用智谱的 Embedding (需要你在 .env 里加 ZHIPU_API_KEY)
    # 如果你没有智谱Key，这里会报错。请在 bigmodel.cn 注册一个免费拿Key
    embeddings = OpenAIEmbeddings(
        model="embedding-2",
        api_key=os.getenv("ZHIPU_API_KEY"),
        base_url="https://open.bigmodel.cn/api/paas/v4/"
    )
    
    persist_dir = "./chroma_db"
    # 如果本地已经有数据库了，直接加载
    if os.path.exists(persist_dir):
        return Chroma(persist_directory=persist_dir, embedding_function=embeddings)
    
    # 如果没有，读取文件并建库
    loader = TextLoader("policy.txt", encoding="utf-8")
    docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=20)
    splits = text_splitter.split_documents(docs)
    
    vectorstore = Chroma.from_documents(documents=splits, embedding=embeddings, persist_directory=persist_dir)
    return vectorstore

vectorstore = get_vectorstore()
retriever = vectorstore.as_retriever(search_kwargs={"k": 2})

@tool
def calculator(expression: str) -> str:
    """用于计算金额总和。输入必须是纯数字表达式，如 '550+800'。"""
    try:
        clean_expr = re.sub(r'[^0-9+\-*/().]', '', expression)
        return f"计算结果：{eval(clean_expr, {'__builtins__': None}, {})} 元"
    except Exception as e:
        return f"计算失败：{str(e)}"

@tool
def search_policy(query: str) -> str:
    """从向量数据库中查询公司差旅制度。输入你要查询的类别，如：'住宿标准'、'打车限制'。"""
    # 真正的 RAG 检索！只返回最相关的 2 个文档片段
    docs = retriever.invoke(query)
    if not docs:
        return "未找到相关制度。"
    return "\n---\n".join([d.page_content for d in docs])