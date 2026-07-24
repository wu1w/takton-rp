"""GrowthCurator — 他的领悟：冷路径策展软约定候选。

铁律：
- 只在冷路径（响应流完之后）跑，必须有真引擎；
- 日配额（默认 3）、去重（与事实/已有领悟相似即丢）、溯源（session+原文片段）；
- 产物永远是「待确认」，绝不自动写进硬记忆。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..memory.store import ProfileStore
from ..models import GrowthProposal

logger = logging.getLogger(__name__)

CURATE_EVERY = 8  # 会话每累积 8 条消息策展一次

_PROMPT = (
    "你是记忆策展员。阅读这段对话，提取 0-2 条「值得向用户确认的相处约定或偏好」，"
    "例如用户的习惯、雷区、相处方式。要求：\n"
    "- 只提取对话中真实出现的信息，禁止编造；\n"
    "- 个人信息事实（住址/过敏等硬事实）不要，那是另一类记忆；只要相处约定；\n"
    "- 输出严格 JSON 数组，每条 {\"text\": \"...\", \"confidence\": 0.0-1.0}；\n"
    "- 没有值得提取的就输出 []，不要硬凑。"
)


def _similar(a: str, b: str) -> float:
    """字符 bigram Jaccard 相似度。"""
    ga = {a[i : i + 2] for i in range(len(a) - 1)} or {a}
    gb = {b[i : i + 2] for i in range(len(b) - 1)} or {b}
    inter = len(ga & gb)
    return inter / (len(ga) + len(gb) - inter) if (ga or gb) else 0.0


def _parse_proposals(raw: str) -> list[dict]:
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
            out.append(
                {
                    "text": item["text"].strip()[:80],
                    "confidence": float(item.get("confidence", 0.5)),
                }
            )
    return out[:2]


async def maybe_curate(
    store: ProfileStore,
    session_id: str,
    client: Any,
    daily_cap: int = 3,
) -> list[GrowthProposal]:
    """返回本轮新产出的待确认领悟（可为空）。无引擎/超配额/无新内容 → []。"""
    if client is None:
        return []
    if store.growth_count_today() >= daily_cap:
        return []

    msgs = store.recent_messages(session_id, limit=CURATE_EVERY)
    if len(msgs) < CURATE_EVERY:
        return []

    transcript = "\n".join(
        ("用户" if m.role == "user" else "角色") + "：" + m.content for m in msgs
    )
    try:
        raw = await client.complete(
            [
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": transcript},
            ],
            max_tokens=300,
        )
    except Exception as e:
        logger.warning("growth curate failed: %s", e)
        return []

    candidates = _parse_proposals(raw or "")
    if not candidates:
        return []

    # 去重：与已有事实 + 已有领悟（pending/adopted）相似度超阈即丢
    existing_texts = [f.text for f in store.list_facts()]
    existing_texts += [
        g.text for g in store.list_growth() if g.status in ("pending", "adopted")
    ]

    produced: list[GrowthProposal] = []
    quota_left = daily_cap - store.growth_count_today()
    excerpt = " / ".join(m.content[:20] for m in msgs[-2:])[:60]
    for c in candidates:
        if quota_left <= 0:
            break
        if any(_similar(c["text"], t) >= 0.5 for t in existing_texts):
            continue
        g = GrowthProposal(
            text=c["text"],
            kind="soft_rule",
            confidence=c["confidence"],
            source_session_id=session_id,
            source_excerpt=excerpt,
            card_id=store.active_card_id(),
        )
        store.add_growth(g)
        existing_texts.append(g.text)
        produced.append(g)
        quota_left -= 1
    return produced
