import os
from datetime import datetime

from langchain_core.tools import tool
from langchain_community.tools.tavily_search import TavilySearchResults
from dotenv import load_dotenv

import rag

load_dotenv()

# 初始化 Tavily 搜索工具
os.environ["TAVILY_API_KEY"] = os.getenv("TAVILY_API_KEY", "")
try:
    tavily_tool = TavilySearchResults(max_results=2)
except Exception as e:
    print(f"Tavily 初始化失败: {e}")
    tavily_tool = None


# ================= 工具定义区 =================

@tool
def search_policy(query: str) -> str:
    """检索天软公司差旅报销制度。query 传入要查询的问题或关键词，
    例如“北京住宿标准”“打车限额”“出差补助规则”“火车票降级”。返回最相关的条款片段。"""
    return rag.search(query, k=4)


@tool
def calculate_allowance(depart_time_str: str, return_time_str: str) -> str:
    """计算差旅补助。输入格式 'YYYY-MM-DD HH:MM'。
    规则：每天 150 元，中午 12 点为界，12 点后出发算半天，12 点前返回算半天。"""
    try:
        fmt = "%Y-%m-%d %H:%M"
        depart = datetime.strptime(depart_time_str, fmt)
        ret = datetime.strptime(return_time_str, fmt)
        if ret < depart:
            return "时间顺序错误：返程时间早于出发时间，请核对。"
        days = (ret.date() - depart.date()).days + 1
        if depart.hour >= 12:
            days -= 0.5
        if ret.hour <= 12:
            days -= 0.5
        days = max(days, 0.5)
        amount = days * 150
        return f"计算成功：共折合 {days} 天，差旅补助总计 {amount} 元。"
    except Exception as e:
        return f"时间格式错误：{e}"


@tool
def train_downgrade(seat_class: str, actual_price: float, second_class_price: float) -> str:
    """火车票降级报销计算。一等座降级为二等座报销。"""
    if seat_class == "二等座":
        return f"实报实销 {actual_price} 元。"
    allowed = min(actual_price, second_class_price)
    return f"降级报销：实际报销 {allowed} 元，个人自理 {actual_price - allowed} 元。"


@tool
def search_train_info(depart_city: str, arrive_city: str, train_no: str) -> str:
    """联网搜索车次发车时间和二等座票价。"""
    if not tavily_tool:
        return "搜索工具未配置，请手动输入发车时间和票价。"
    query = f"12306 火车 {train_no} 从{depart_city}到{arrive_city} 时刻表 二等座票价"
    try:
        results = tavily_tool.invoke(query)
        if not results:
            return f"未搜索到 {train_no} 的信息。"
        return "\n".join([f"内容:{r.get('content')}" for r in results])
    except Exception as e:
        return f"搜索失败：{e}"
