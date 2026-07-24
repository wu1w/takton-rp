"""压缩链路：成对滑窗 / 摘要装配 / 冷路径摘要生成。"""

import asyncio

from nianxia_core.memory import ProfileStore, assemble
from nianxia_core.memory.store import ChatMessage
from nianxia_core.models import SessionSummary
from nianxia_core.runtime.summarize import (
    SUMMARIZE_AFTER,
    maybe_summarize,
    pair_window,
)


def mk(role, text, ts):
    return ChatMessage(role=role, content=text, ts=ts)


def test_pair_window_keeps_complete_pairs():
    msgs = []
    for i in range(10):
        msgs.append(mk("user", f"问{i}", i * 2))
        msgs.append(mk("assistant", f"答{i}", i * 2 + 1))
    w = pair_window(msgs, "L0")
    assert len(w) <= 6
    assert w[0].role == "user"  # 不成对的不留孤儿
    assert w[-1].role == "assistant"

    # 奇数切断时丢弃开头孤儿 assistant
    odd = msgs[:-1]
    w2 = pair_window(odd, "L0")
    assert w2[0].role == "user"


def test_summary_injected_in_assemble(tmp_path):
    store = ProfileStore(tmp_path, "default")
    store.add_summary(
        SessionSummary(session_id="ses_a", covers_upto=100.0, text="用户曾说下周要去青岛出差。")
    )
    a = assemble(store, tier="L1")
    assert "【前情摘要】" in a["system"]
    assert "青岛出差" in a["system"]

    # L0 档摘要被压到 300 字以内
    long_text = "长" * 500
    store.add_summary(
        SessionSummary(session_id="ses_b", covers_upto=200.0, text=long_text)
    )
    a0 = assemble(store, tier="L0")
    assert "【前情摘要】" in a0["system"]
    assert "长" * 301 not in a0["system"]


class FakeClient:
    engine_name = "l1"

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, max_tokens=400):
        self.calls += 1
        return "用户聊了工作和咖啡；约好明天继续。"


def test_cold_path_summary_generated(tmp_path):
    store = ProfileStore(tmp_path, "default")
    sid = "ses_x"
    # 写入 SUMMARIZE_AFTER + KEEP_TAIL 条消息
    total = SUMMARIZE_AFTER + 6 + 2
    for i in range(total):
        store.append_message(sid, mk("user" if i % 2 == 0 else "assistant", f"消息{i}", float(i)))

    client = FakeClient()
    s = asyncio.run(maybe_summarize(store, sid, client))
    assert s is not None
    assert "咖啡" in s.text or "明天" in s.text
    assert s.covers_upto > 0
    assert client.calls == 1

    # 覆盖位之后没有足够新消息 → 不再重复摘要
    s2 = asyncio.run(maybe_summarize(store, sid, client))
    assert s2 is None
    assert client.calls == 1

    # 装配层能看到摘要
    a = assemble(store, tier="L1")
    assert "【前情摘要】" in a["system"]


def test_cold_path_no_engine_skips(tmp_path):
    store = ProfileStore(tmp_path, "default")
    sid = "ses_y"
    for i in range(SUMMARIZE_AFTER + 10):
        store.append_message(sid, mk("user", f"消息{i}", float(i)))
    s = asyncio.run(maybe_summarize(store, sid, None))
    assert s is None  # 无引擎：如实跳过，绝不伪造摘要
    assert store.list_summaries() == []
