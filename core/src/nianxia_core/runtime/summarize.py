"""压缩：近聊滑窗（成对裁剪）+ 冷路径摘要生成。

延迟宪法：滑窗是热路径纯规则；摘要只在冷路径（响应流完之后）生成，
且必须有真实引擎——无引擎时如实跳过，绝不伪造摘要。
"""

from __future__ import annotations

import logging
from typing import Any

from ..memory.store import ProfileStore
from ..models import ChatMessage, SessionSummary

logger = logging.getLogger(__name__)

# 分档滑窗（消息条数；user+assistant 成对计）
WINDOW_MSGS = {"L0": 6, "L1": 20, "L2": 40}

# 冷路径摘要触发：未压缩区达到这么多条才触发
SUMMARIZE_AFTER = 12
# 摘要后保留多少条最新消息不进摘要（交给滑窗原样带）
SUMMARY_KEEP_TAIL = 6


def pair_window(messages: list[ChatMessage], tier: str) -> list[ChatMessage]:
    """取最近 N 条，并保证窗口以 user 消息开头（成对完整，不剩孤儿回复）。"""
    limit = WINDOW_MSGS.get(tier, 6)
    window = messages[-limit:] if len(messages) > limit else list(messages)
    while window and window[0].role == "assistant":
        window = window[1:]
    return window


_SUMMARY_PROMPT = (
    "把以下对话压缩成 3-5 句中文摘要。只保留：用户的个人信息与偏好、"
    "双方做过的约定、还没聊完的话头。不要寒暄，不要评价，直接给摘要。"
)


async def maybe_summarize(
    store: ProfileStore, session_id: str, client: Any
) -> SessionSummary | None:
    """响应流完后调用。client 须有 complete(messages)->str（L1/L0 通用）。

    无引擎 / 未达阈值 / 无新内容 → 返回 None（如实跳过）。
    """
    if client is None:
        return None
    msgs = store.recent_messages(session_id, limit=10_000)
    covered = store.summary_covered_upto(session_id)
    fresh = [m for m in msgs if m.ts > covered and m.role in ("user", "assistant")]
    if len(fresh) < SUMMARIZE_AFTER:
        return None

    body = fresh[:-SUMMARY_KEEP_TAIL]  # 老的进摘要，新的留滑窗
    if len(body) < 4:
        return None

    transcript = "\n".join(
        ("用户" if m.role == "user" else "角色") + "：" + m.content for m in body
    )
    try:
        text = await client.complete(
            [
                {"role": "system", "content": _SUMMARY_PROMPT},
                {"role": "user", "content": transcript},
            ]
        )
    except Exception as e:  # 摘要失败不碍聊天：记日志跳过
        logger.warning("summary failed: %s", e)
        return None

    text = (text or "").strip()
    if not text:
        return None
    summary = SessionSummary(
        session_id=session_id,
        covers_upto=body[-1].ts,
        text=text,
        engine=getattr(client, "engine_name", "l1"),
    )
    store.add_summary(summary)
    return summary
