"""DeviceClock — 设备时间主路径（device-time-inject 专文的落地）。

规则：
- 业务代码禁止散落 datetime.now()；统一 ClockService.now()/snapshot()。
- 每轮 assemble 现场采样，system 注入与日志共用同一快照。
- 联网校时是可选增强，骨架期不实现，接口预留。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _period(hour: int) -> str:
    if hour < 5:
        return "凌晨"
    if hour < 9:
        return "清晨"
    if hour < 12:
        return "上午"
    if hour < 14:
        return "午间"
    if hour < 18:
        return "下午"
    if hour < 22:
        return "晚上"
    return "深夜"


class ClockService:
    """设备本地时间；联网校时为可选增强（suspect 逻辑后续加）。"""

    def now(self) -> datetime:
        return datetime.now().astimezone()

    def snapshot(self) -> dict[str, Any]:
        now = self.now()
        local = now.astimezone()
        tzname = local.tzname() or "local"
        offset = local.strftime("%z")
        return {
            "iso": local.isoformat(timespec="seconds"),
            "date": local.strftime("%Y-%m-%d"),
            "time": local.strftime("%H:%M"),
            "weekday": _WEEKDAYS[local.weekday()],
            "period": _period(local.hour),
            "tz": f"{tzname} {offset}",
            "source": "device",
            "trusted": True,
            "suspect": False,
        }

    def system_block(self) -> str:
        """注入 system 的【设备时间·实时】块。"""
        s = self.snapshot()
        return (
            f"【设备时间·实时】{s['date']} {s['weekday']} {s['time']}（{s['tz']}）· {s['period']}\n"
            "（用户设备当前时间；不必每轮朗读；自然相关时再用）"
        )


clock = ClockService()
