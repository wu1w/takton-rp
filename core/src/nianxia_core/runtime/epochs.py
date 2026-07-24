"""Epochs 封纪：把已成往事的会话封存成岁月年表（冷路径，需真引擎）。"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..memory.store import ProfileStore
from ..models import Epoch

logger = logging.getLogger(__name__)

SEAL_AGE_SECONDS = 3 * 86400  # 3 天前的会话才算"往事"
SEAL_MIN_SESSIONS = 3  # 至少攒 3 段才封一次

_PROMPT = (
    "你是年表撰写者。把下面这些日子里的对话片段，封成 1-3 句「岁月年表」："
    "第三人称、平静温暖的口吻，只写真实发生过的事（约定、经历、情绪转折），"
    "不写细节流水账，禁止编造。直接输出年表正文，不要任何前缀。"
)


async def maybe_seal_epoch(store: ProfileStore, client: Any) -> Epoch | None:
    if client is None:
        return None
    covered = store.epoch_covered_upto()
    cutoff = time.time() - SEAL_AGE_SECONDS
    old = [
        s for s in store.list_sessions()
        if covered < s["updated_at"] < cutoff
    ]
    if len(old) < SEAL_MIN_SESSIONS:
        return None

    # 素材：每段会话的首尾消息片段
    snippets: list[str] = []
    for s in old[:10]:
        msgs = store.recent_messages(s["session_id"], limit=4)
        text = " / ".join(m.content[:24] for m in msgs)
        if text:
            import datetime as dt

            day = dt.datetime.fromtimestamp(s["updated_at"]).strftime("%m月%d日")
            snippets.append(f"{day}：{text}")
    if not snippets:
        return None

    try:
        text = await client.complete(
            [
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": "\n".join(snippets)},
            ],
            max_tokens=300,
        )
    except Exception as e:
        logger.warning("epoch seal failed: %s", e)
        return None

    text = (text or "").strip()
    if not text:
        return None

    epoch = Epoch(
        covers_from=min(s["updated_at"] for s in old),
        covers_to=max(s["updated_at"] for s in old),
        text=text[:400],
        engine=getattr(client, "engine_name", "l1"),
    )
    store.add_epoch(epoch)
    return epoch
