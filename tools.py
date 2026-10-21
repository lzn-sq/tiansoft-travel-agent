from langchain_core.tools import tool

@tool
def calculator(expression: str) -> str:
    """用于计算金额。当需要计算总和、平均值或进行数学运算时使用。
    输入必须是合法的数学表达式字符串，例如 '550+800+120'。"""
    try:
        # 简单安全求值（生产环境不建议直接用 eval，这里为了演示）
        result = eval(expression, {"__builtins__": None}, {})
        return f"计算结果：{result} 元"
    except Exception as e:
        return f"计算失败，请输入合法的数学表达式。错误信息：{str(e)}"

@tool
def check_policy(category: str) -> str:
    """查询天软公司差旅报销标准。当需要确认某项花费是否合规时使用。
    输入类别只能是：'住宿'、'交通'、'餐饮' 其中之一。"""
    # 模拟企业数据库
    policies = {
        "住宿": "一线城市（如北京）每晚上限 600 元，二线城市每晚上限 400 元。",
        "交通": "高铁二等座实报实销，打车需提供行程单，单次上限 100 元。",
        "餐饮": "出差补贴每天 100 元，无需发票。"
    }
    # 模糊匹配，防止模型输入奇怪的字眼
    for key in policies:
        if key in category:
            return policies[key]
    return "未找到该类别的报销标准，请确认输入的是'住宿'、'交通'或'餐饮'。"