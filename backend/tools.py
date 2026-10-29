import os
import re
from datetime import datetime
from typing import Optional

import requests
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


_TIMETABLE_URL = "https://train.qunar.com/train/timetable/{train_no}"
_TIMETABLE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def lookup_train_schedule(train_no: str) -> Optional[dict]:
    """从时刻表页解析车次的发车时刻与二等座/一等座票价（结构化、确定性来源）。

    只负责时刻表与票价本身；具体出行日期由调用方结合用户消息确定。
    """
    if not re.fullmatch(r"[A-Za-z0-9]{1,8}", train_no or ""):
        return None
    try:
        response = requests.get(
            _TIMETABLE_URL.format(train_no=train_no.upper()),
            headers=_TIMETABLE_HEADERS,
            timeout=10,
        )
        if response.status_code != 200:
            return None
        text = response.text
    except Exception as e:
        print(f" -> 时刻表抓取失败 {train_no}: {e}")
        return None

    def fact(name: str) -> Optional[str]:
        match = re.search(r'"id":"%s"[^}]*"value":"([^"]+)"' % name, text)
        return match.group(1) if match else None

    def price(seat: str) -> Optional[float]:
        match = re.search(
            r'"@type":"Offer","name":"%s","category":"%s","price":"([0-9]+(?:\.[0-9]+)?)"'
            % (seat, seat),
            text,
        )
        return float(match.group(1)) if match else None

    depart_hm = fact("departureTime")
    if not depart_hm or not re.fullmatch(r"[0-9]{2}:[0-9]{2}", depart_hm):
        return None
    return {
        "train_no": train_no.upper(),
        "depart_time": depart_hm,
        "arrival_time": fact("arrivalTime"),
        "from_station": fact("departureStation"),
        "to_station": fact("arrivalStation"),
        "second_price": price("二等座"),
        "first_price": price("一等座"),
    }


@tool
def search_train_info(depart_city: str, arrive_city: str, train_no: str) -> str:
    """联网查询车次发车时间和二等座票价（优先使用时刻表结构化数据，失败时回退搜索）。"""
    schedule = lookup_train_schedule(train_no)
    if schedule:
        return "\n".join(
            [
                "来源：去哪儿时刻表",
                f"车次：{schedule['train_no']}",
                f"出发站：{schedule['from_station'] or '未知'}",
                f"到达站：{schedule['to_station'] or '未知'}",
                f"发车时间：{schedule['depart_time']}",
                f"到达时间：{schedule['arrival_time'] or '未知'}",
                f"二等座票价：{schedule['second_price'] if schedule['second_price'] is not None else '未知'}",
                f"一等座票价：{schedule['first_price'] if schedule['first_price'] is not None else '未知'}",
            ]
        )
    if not tavily_tool:
        return "搜索工具未配置，请手动输入发车时间和票价。"
    query = " ".join(
        part
        for part in ("12306 火车", train_no, depart_city, arrive_city, "时刻表 二等座票价")
        if part
    )
    try:
        results = tavily_tool.invoke(query)
        if not results:
            return f"未搜索到 {train_no} 的信息。"
        return "\n".join([f"内容:{r.get('content')}" for r in results])
    except Exception as e:
        return f"搜索失败：{e}"
