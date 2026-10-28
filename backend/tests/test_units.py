import rag
from agent_core import _last_approved_total, _wants_payment
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
