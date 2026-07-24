"""GPU 探测 → 后端候选链（docs/l0-multi-backend.md §6 的实现）。

客户端平台（产品决策）：Windows / macOS 跑 core；安卓/iOS 为薄客户端，无本地推理。
- Windows: PowerShell CIM Win32_VideoController 取显卡名
- macOS: 官方包 Metal 内置，无需探测
- 探测失败 → [vulkan, cpu]；探测结果只排序，不做持久否定（启动失败由回退链兜底）
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess

logger = logging.getLogger(__name__)

# win-hip-radeon 官方构建主要覆盖这些 gfx（营销名粗映射）
_HIP_NAME_MAP = [
    (r"rx\s*79\d{2}", "gfx1100"), (r"rx\s*78\d{2}", "gfx1100"), (r"rx\s*77\d{2}", "gfx1101"),
    (r"rx\s*76\d{2}", "gfx1102"), (r"rx\s*69\d{2}", "gfx1030"), (r"rx\s*68\d{2}", "gfx1030"),
    (r"rx\s*67\d{2}", "gfx1031"), (r"rx\s*66\d{2}", "gfx1032"), (r"vega", "gfx900"),
]
_HIP_SUPPORTED = {"gfx900", "gfx1030", "gfx1031", "gfx1032", "gfx1100", "gfx1101", "gfx1102"}


def detect_gpu_names() -> list[str]:
    """返回本机显卡名列表（仅 Windows 需要；macOS 走 Metal）；拿不到返回 []。"""
    try:
        if platform.system() == "Windows":
            out = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "(Get-CimInstance Win32_VideoController).Name -join '`n'",
                ],
                capture_output=True, text=True, errors="replace", timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return [l.strip() for l in out.stdout.splitlines() if l.strip()]
    except Exception as e:
        logger.info("gpu detect failed: %s", e)
    return []


def _hip_ok(name: str) -> bool:
    low = name.lower()
    for pat, gfx in _HIP_NAME_MAP:
        if re.search(pat, low):
            return gfx in _HIP_SUPPORTED
    # 未识别的 Radeon（如更新型号）：乐观放行，启动失败有回退链
    return True


def backend_candidates(names: list[str], system: str | None = None) -> list[str]:
    """按优先级给出后端候选链（末位永远 cpu）。仅服务 Windows/macOS 客户端。"""
    system = system or platform.system()

    if system == "Darwin":  # macOS：官方包 Metal 内置（arm64/x64 通用）
        return ["metal", "cpu"]

    if system != "Windows":  # 非客户端平台（如开发用 Linux）：保守兜底
        return ["vulkan", "cpu"]

    cands: list[str] = []
    joined = " | ".join(names).lower()

    has_nvidia = "nvidia" in joined or "geforce" in joined or "rtx" in joined or "gtx" in joined
    has_amd = "amd" in joined or "radeon" in joined
    has_intel = "intel" in joined or "arc" in joined or "iris" in joined

    if has_nvidia:
        cands.append("cuda")
    if has_amd and any(_hip_ok(n) for n in names if ("amd" in n.lower() or "radeon" in n.lower())):
        cands.append("hip")
    if has_intel:
        cands.append("sycl")
    cands.append("vulkan")  # 跨厂安全网
    cands.append("cpu")
    # 去重保序
    seen: list[str] = []
    for c in cands:
        if c not in seen:
            seen.append(c)
    return seen
