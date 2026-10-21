import re
import os
from langchain_core.tools import tool
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv

load_dotenv()

# 1. 初始化本地知识库（简化版 RAG，确保稳定不报错）
def init_knowledge_base():
    if not os.path.exists("policy.txt"):
        return "未找到 policy.txt 知识库文件。"
    loader = TextLoader("policy.txt", encoding="utf-8")
    docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=20)
    splits = text_splitter.split_documents(docs)
    return splits

policy_splits = init_knowledge_base()

@tool
def calculator(expression: str) -> str:
    """用于计算差旅金额总和。当需要计算总和、平均值或进行数学运算时使用。
    输入必须是合法的数学表达式字符串，例如 '550+800+120'。千万不要包含文字。"""
    try:
        # 用正则清洗，防止模型传入奇怪的中文字符
        clean_expr = re.sub(r'[^0-9+\-*/().]', '', expression)
        if not clean_expr:
            return "提取不到有效的数字表达式，请重新输入。"
        result = eval(clean_expr, {"__builtins__": None}, {})
        return f"计算结果：{result} 元"
    except Exception as e:
        return f"计算失败，请输入合法的数学表达式。错误信息：{str(e)}"

@tool
def search_policy(query: str) -> str:
    """查询天软公司差旅报销标准。当需要确认住宿、交通、餐饮是否合规时使用。
    输入你查询的类别，如：'住宿'、'交通'、'一线城市标准'。"""
    # 模拟检索过程，将所有政策条款返回给大模型参考
    if isinstance(policy_splits, str):
        return policy_splits
    relevant_docs = [doc.page_content for doc in policy_splits]
    return "\n".join(relevant_docs)