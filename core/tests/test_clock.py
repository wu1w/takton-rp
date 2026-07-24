"""设备时间：快照字段齐全、system 块可注入。"""

from nianxia_core.clock import ClockService


def test_snapshot_fields():
    snap = ClockService().snapshot()
    for key in ("iso", "date", "time", "weekday", "period", "tz", "source"):
        assert key in snap, f"missing {key}"
    assert snap["source"] == "device"
    assert snap["weekday"].startswith("周")
    assert snap["period"] in ("凌晨", "清晨", "上午", "午间", "下午", "晚上", "深夜")


def test_system_block_contains_time():
    block = ClockService().system_block()
    assert "【设备时间·实时】" in block
    assert "不必每轮朗读" in block
