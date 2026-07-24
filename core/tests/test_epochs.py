"""Epochs 封纪：触发门槛 / 游标不重复封 / 装配年表 / 无引擎跳过。"""

import asyncio
import time

from nianxia_core.memory import ProfileStore, assemble
from nianxia_core.models import ChatMessage
from nianxia_core.runtime.epochs import SEAL_AGE_SECONDS, maybe_seal_epoch


class FakeClient:
    engine_name = "l1"

    async def complete(self, messages, max_tokens=400):
        return "那些日子里，你们从陌生走到熟悉，聊过周末的去处，也约定以后要常说话。"


def make_old_sessions(store, n, age=SEAL_AGE_SECONDS + 3600):
    for i in range(n):
        sid = f"ses_old_{i}"
        ts = time.time() - age - i * 60
        store.append_message(sid, ChatMessage(role="user", content=f"旧消息{i}", ts=ts))
        # list_sessions 以文件 mtime 排序/过滤 updated_at；这里直接改文件 mtime
        import os

        p = store.session_path(sid)
        os.utime(p, (ts, ts))


def test_seal_and_assemble(tmp_path):
    store = ProfileStore(tmp_path, "default")
    make_old_sessions(store, 3)

    epoch = asyncio.run(maybe_seal_epoch(store, FakeClient()))
    assert epoch is not None
    assert "日子" in epoch.text

    # 装配进年表块
    a = assemble(store)
    assert "【岁月年表】" in a["system"]

    # 游标生效：不重复封
    assert asyncio.run(maybe_seal_epoch(store, FakeClient())) is None


def test_seal_thresholds(tmp_path):
    store = ProfileStore(tmp_path, "default")
    # 只有 2 段旧会话 → 不封
    make_old_sessions(store, 2)
    assert asyncio.run(maybe_seal_epoch(store, FakeClient())) is None
    # 无引擎 → 不封
    make_old_sessions(store, 1)
    assert asyncio.run(maybe_seal_epoch(store, None)) is None
    assert store.list_epochs() == []
