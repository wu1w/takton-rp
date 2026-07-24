"""Token 估算（CJK 感知）+ 各引擎上下文预算。

启发式（与 Takton TokenMeter 同源）：
- CJK 字符 ≈ 1.5 字符/token
- 拉丁/数字 ≈ 4 字符/token
- 每条消息加结构开销

用途：装配后主动估算，超预算先收缩再发给引擎；配合 reactive 重试兜底。
"""

from __future__ import annotations

from typing import Any

# 引擎上下文窗口（token）。L0=本地 2B sidecar（-c 4096）；L1=云端/局域网大模型。
CONTEXT_WINDOWS = {"l0": 4096, "l1": 262_144, "l2": 131_072}
# 给补全预留的输出 token（RP 回复一般几百 token，取保守值）
RESERVE_COMPLETION = 800
# 触发收缩的占用比例
BUDGET_RATIO = 0.85

_CJK_RANGES = (
    (0x4E00, 0x9FFF),    # CJK 统一表意
    (0x3400, 0x4DBF),    # 扩展 A
    (0x3000, 0x303F),    # CJK 标点
    (0xFF00, 0xFFEF),    # 全角
    (0xF900, 0xFAFF),    # 兼容表意
)


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in _CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """混合文本 token 估算：CJK 保守按 1 token/字符（Qwen 系真实接近），其余按 4 字符/token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    return int(cjk + other / 4 + 0.5)


def estimate_messages(messages: list[dict[str, Any]]) -> int:
    """OpenAI 风格消息列表估算（每条 +4 结构开销；多模态 content 取文本部分）。"""
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):  # 多模态：文本计数，图片按固定 1024 估
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        total += estimate_tokens(str(part.get("text", "")))
                    else:
                        total += 1024
        total += 4
    return total


def token_budget(engine_name: str | None) -> int:
    """该引擎本轮允许的最大 prompt token（窗口 × 比例 − 输出预留）。"""
    window = CONTEXT_WINDOWS.get(engine_name or "l0", 4096)
    return int(window * BUDGET_RATIO) - RESERVE_COMPLETION
