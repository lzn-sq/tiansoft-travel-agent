import rag
from agent_core import (
    REQUIRED_FIELDS,
    _apply_confirmed_train,
    _confirms_train,
    _dates_from_message,
    _last_approved_total,
    _mentions_train_values,
    _pending_train_info,
    _route_after_validate,
    _structured_train_info,
    _wants_payment,
    validate_node,
)
from auth import create_access_token, decode_access_token
from tools import calculate_allowance


def test_allowance_calculation():
    result = calculate_allowance.invoke(
        {"depart_time_str": "2026-10-29 08:00", "return_time_str": "2026-10-30 14:00"}
    )
    assert "300" in result


def test_allowance_half_days():
    result = calculate_allowance.invoke(
        {"depart_time_str": "2026-10-29 14:00", "return_time_str": "2026-10-30 10:00"}
    )
    assert "1.0 天" in result
    assert "150" in result


def test_allowance_rejects_reversed_time():
    result = calculate_allowance.invoke(
        {"depart_time_str": "2026-10-30 08:00", "return_time_str": "2026-10-29 08:00"}
    )
    assert "错误" in result


def test_policy_chunks_loaded():
    chunks = rag.load_chunks()
    assert len(chunks) >= 4
    assert any("住宿费报销标准" in chunk for chunk in chunks)


def test_keyword_search_fallback():
    result = rag.keyword_search("北京住宿标准", k=2)
    assert "住宿" in result


def test_jwt_roundtrip():
    token = create_access_token("alice")
    assert decode_access_token(token) == "alice"
    assert decode_access_token(token + "tampered") is None
    assert decode_access_token("invalid.token") is None


def test_payment_intent_detection():
    assert _wants_payment("确认打款") is True
    assert _wants_payment("帮我打款吧") is True
    assert _wants_payment("现在付款") is True

    # 只是核算或询问，不应触发打款
    assert _wants_payment("帮我算算") is False
    assert _wants_payment("住宿标准是多少") is False
    assert _wants_payment("我没让打款") is False
    assert _wants_payment("确认一下打款流程") is False


def test_last_approved_total():
    history = [
        ("user", "帮我算算"),
        ("assistant", "📊 **费用明细：**\n✅ **总计报销：1347.5元**"),
        ("user", "确认打款"),
    ]
    assert _last_approved_total(history) == "1347.5"
    assert _last_approved_total([("assistant", "请补充职级")]) is None
    assert _last_approved_total([]) is None


def test_train_no_is_optional():
    assert "train_no" not in REQUIRED_FIELDS
    # 车次号缺失但时间、金额齐全时不应追问
    form = {
        "city": "上海",
        "job_level": "普通员工",
        "hotel_amount": 700,
        "hotel_nights": 2,
        "train_no": None,
        "depart_time": "2026-10-29 09:00",
    }
    assert validate_node({"form": form})["missing"] == []

    # 核心字段仍必须校验
    missing = validate_node({"form": {**form, "city": None}})["missing"]
    assert missing == ["出差目的地"]


def _pending_message():
    return (
        "assistant",
        "🚄 **[车次信息待确认]**\n\n"
        "- 去程 C2202｜发车时间：2026-10-29 06:09｜二等座票价：54.5 元\n"
        "- 返程 C2575｜发车时间：2026-10-31 13:00｜二等座票价：66.5 元\n\n"
        "> 请核对后回复“确认车次信息”继续。",
    )


def test_pending_train_info_only_from_latest_reply():
    pending = _pending_message()
    info = _pending_train_info([("user", "我29日坐C2202去北京，31日坐C2575回天津"), pending])
    assert info == {
        "outbound": {"train_no": "C2202", "depart_time": "2026-10-29 06:09", "train_price": 54.5},
        "return": {"train_no": "C2575", "depart_time": "2026-10-31 13:00", "train_price": 66.5},
    }

    # 已有后续核算结果时，旧查询值不再处于待确认状态
    assert _pending_train_info([("user", "..."), pending, ("assistant", "📊 费用明细")]) is None
    assert _pending_train_info([("user", "帮我算算")]) is None
    # 未查到的项不应被解析成数值
    pending_fail = (
        "assistant",
        "🚄 **[车次信息待确认]**\n\n- 去程 C2202｜发车时间：未查到｜二等座票价：未查到",
    )
    assert _pending_train_info([pending_fail]) == {
        "outbound": {"train_no": "C2202", "depart_time": None, "train_price": None}
    }


def test_train_confirmation_intent():
    assert _confirms_train("确认车次信息") is True
    assert _confirms_train("没问题，按这个算") is True
    # 打款确认不算车次确认
    assert _confirms_train("确认打款") is False
    assert _confirms_train("帮我算算") is False


def test_confirmed_train_info_fills_missing_fields():
    form = {
        "train_no": "C2202",
        "depart_time": None,
        "train_price": None,
        "return_train_no": "C2575",
        "return_time": None,
        "return_train_price": None,
    }
    confirmed = {
        "outbound": {"train_no": "C2202", "depart_time": "2026-10-29 06:09", "train_price": 54.5},
        "return": {"train_no": "C2575", "depart_time": "2026-10-31 13:00", "train_price": 66.5},
    }
    applied = _apply_confirmed_train(form, confirmed)
    assert applied["depart_time"] == "2026-10-29 06:09"
    assert applied["train_price"] == 54.5
    assert applied["return_time"] == "2026-10-31 13:00"
    assert applied["return_train_price"] == 66.5

    # 用户本轮给出的值优先，不被查询结果覆盖
    form2 = {"depart_time": "2026-10-29 06:30", "train_price": None}
    applied2 = _apply_confirmed_train(
        form2, {"outbound": {"depart_time": "2026-10-29 06:09", "train_price": 54.5}}
    )
    assert applied2["depart_time"] == "2026-10-29 06:30"
    assert applied2["train_price"] == 54.5

    # 用户只是确认时，以展示过的确认值为准，覆盖抽取模型可能给出的默认值
    form3 = {"depart_time": "2026-10-29 00:00", "train_price": None}
    assert _mentions_train_values("确认车次信息") is False
    assert _apply_confirmed_train(
        form3, {"outbound": {"depart_time": "2026-10-29 06:09"}}, override=True
    )["depart_time"] == "2026-10-29 06:09"
    assert _mentions_train_values("确认，不过发车时间是08:30") is True
    assert _mentions_train_values("确认，票价553元") is True


def test_route_requires_train_confirmation_before_audit():
    base = {
        "city": "北京",
        "job_level": "普通员工",
        "hotel_amount": 630,
        "hotel_nights": 2,
        "train_no": "C2202",
        "depart_time": None,
        "train_price": None,
    }
    # 车次信息不完整：先请用户确认查询结果
    assert _route_after_validate({"form": base, "missing": ["发车时间"]}) == "train"
    # 有车次但缺票价：同样先确认
    assert _route_after_validate({"form": {**base, "depart_time": "2026-10-29 08:00"}, "missing": []}) == "train"
    # 只要用户给了车次，即使其他必填项也缺失，仍先由 AI 查询车次，而不是让用户填发车时间
    assert _route_after_validate({"form": {**base, "job_level": None}, "missing": ["职级", "发车时间"]}) == "train"
    # 返程车次也由 AI 查询，缺返程时刻/票价时同样先确认
    assert _route_after_validate(
        {
            "form": {
                **base,
                "depart_time": "2026-10-29 08:00",
                "train_price": 54.5,
                "return_train_no": "C2575",
                "return_time": None,
                "return_train_price": None,
            },
            "missing": [],
        }
    ) == "train"
    # 用户刚确认过车次，但必填的发车时间仍未查到：不再重复展示确认，改为追问
    assert _route_after_validate(
        {"form": base, "missing": ["发车时间"], "confirmed_train_info": {"outbound": {"train_no": "C2202"}}}
    ) == "ask"
    # 没有车次号时按原逻辑追问
    assert _route_after_validate({"form": {**base, "train_no": None}, "missing": ["发车时间"]}) == "ask"
    # 信息齐全才进入审核
    assert _route_after_validate(
        {
            "form": {
                **base,
                "depart_time": "2026-10-29 06:09",
                "train_price": 54.5,
                "return_train_no": "C2575",
                "return_time": "2026-10-31 13:00",
                "return_train_price": 66.5,
            },
            "missing": [],
        }
    ) == "audit"


def test_dates_from_message():
    text = "2026年10月29日坐C2202去北京，10月31日坐C2575返回天津"
    assert _dates_from_message(text) == ["2026-10-29", "2026-10-31"]
    assert _dates_from_message("本月29日出发，31日返回")[1].endswith("-31")
    assert _dates_from_message("没有日期") == []


def test_structured_train_info_uses_timetable_data():
    raw = (
        "来源：去哪儿时刻表\n车次：C2202\n出发站：天津\n到达站：北京南\n"
        "发车时间：06:09\n到达时间：06:44\n二等座票价：54.5\n一等座票价：88"
    )
    outbound = _structured_train_info(raw, "10月29日坐C2202去北京，10月31日坐C2575返回", "去程")
    assert outbound == {"depart_time": "2026-10-29 06:09", "train_price": 54.5}
    # 非时刻表结构化来源不走该分支
    assert _structured_train_info("内容: C2202 06:09", "10月29日出发", "去程") is None


def test_train_confirm_appends_other_missing_fields():
    import asyncio

    from agent_core import train_confirm_node

    state = {
        "form": {
            "city": "北京",
            "job_level": None,
            "train_no": "C2202",
            "return_train_no": "C2575",
        },
        "missing": ["职级", "发车时间"],
        "pending_train_info": {
            "outbound": {"train_no": "C2202", "depart_time": "2026-10-29 06:09", "train_price": 54.5},
            "return": {"train_no": "C2575", "depart_time": "2026-10-31 13:00", "train_price": 66.5},
        },
        "messages": [],
    }
    reply = asyncio.run(train_confirm_node(state))["reply"]
    assert "确认车次信息" in reply
    assert "去程 C2202｜发车时间：2026-10-29 06:09｜二等座票价：54.5 元" in reply
    assert "返程 C2575｜发车时间：2026-10-31 13:00｜二等座票价：66.5 元" in reply
    assert "职级" in reply
