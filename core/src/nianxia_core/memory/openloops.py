"""Open Loops（未完话头）：规则预埋提取 + ≥6h 召回 + 闭环。

规则（PRD §5.3.3 预埋 P0）：
- 触发：用户消息含「下次/改天/明天再/回头说/到时候/以后聊」类推延词
  → 生成 open loop（0 LLM，冷路径调用）
- 召回：距上次会话 ≥6h 才注入上下文；日常连聊不刷屏
- 闭环：话题聊完标 completed，移出活跃
"""

from __future__ import annotations

import re

from ..models import new_id

# 推延模式：用户明确说"以后再说"的信号
_DEFER_PATTERNS = [
    r"下次[再说聊讲]",
    r"改天[再说聊讲]",
    r"明天再[说聊讲]",
    r"回头[再说聊讲告]",
    r"以后[再说聊讲慢]",
    r"到时候再[说聊讲]",
    r"先不聊这个",
    r"这事以后再说",
]
_DEFER_RE = re.compile("|".join(_DEFER_PATTERNS))

RECALL_GAP_SECONDS = 6 * 3600  # ≥6h 才召回


def detect_deferral(message: str) -> bool:
    return bool(_DEFER_RE.search(message))


def make_loop(message: str) -> dict:
    topic = message.strip()
    if len(topic) > 30:
        topic = topic[:30] + "…"
    return {
        "id": new_id("loop"),
        "topic": topic,
        "status": "open",
        "source": "rule",
    }


def topic_already_open(loops: list[dict], topic: str) -> bool:
    """同一话头不重复挂：前缀 6 字相同即视为同一话头（推延措辞不同无所谓）。"""
    base = topic.rstrip("…").strip()[:6]
    if len(base) < 4:
        return False
    return any(
        l.get("status", "open") == "open" and l.get("topic", "").strip()[:6] == base
        for l in loops
    )
