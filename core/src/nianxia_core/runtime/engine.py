"""引擎选择：按 tier 找一条真实可用的推理路径（L0 sidecar / L1 云）。

返回 (engine_name, client) 或 (None, None)——后者由调用方如实报未接入。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..inference import L0Client, get_sidecar, l1_from_media_settings

logger = logging.getLogger(__name__)


def pick_engine(
    tier: str,
    data_root: Path,
    media: dict[str, Any],
    api_key: str | None,
) -> tuple[str | None, Any]:
    """tier=L0 → 先 L0 后 L1 兜底；tier=L1 → 先 L1 后 L0 兜底；L2 暂同 L1 策略。"""
    sidecar = get_sidecar(data_root)
    l1 = l1_from_media_settings(media, api_key)

    def try_l0() -> tuple[str | None, Any]:
        st = sidecar.status()
        if not st["installed"]:
            return None, None
        if sidecar.is_running() or sidecar.start():
            return "l0", L0Client(port=st["port"])
        return None, None

    order = ["l0", "l1"] if tier == "L0" else ["l1", "l0"]
    for which in order:
        if which == "l1" and l1 is not None:
            return "l1", l1
        if which == "l0":
            name, client = try_l0()
            if client is not None:
                return name, client
    return None, None
