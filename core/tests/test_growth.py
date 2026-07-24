"""Growth 领悟：策展触发/去重/日配额/确认生效/溯源。"""

import asyncio

from nianxia_core.memory import ProfileStore, assemble
from nianxia_core.models import ChatMessage, GrowthProposal
from nianxia_core.runtime.growth import CURATE_EVERY, maybe_curate


def fill_session(store, sid, n):
    for i in range(n):
        store.append_message(
            sid,
            ChatMessage(role="user" if i % 2 == 0 else "assistant",
                        content=f"内容{i}", ts=float(i)),
        )


class FakeClient:
    engine_name = "l1"

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    async def complete(self, messages, max_tokens=400):
        self.calls += 1
        return self.reply


def test_curate_produces_pending_proposals(tmp_path):
    store = ProfileStore(tmp_path, "default")
    fill_session(store, "ses_g", CURATE_EVERY)
    client = FakeClient('[{"text": "用户希望回复简短", "confidence": 0.8}]')

    out = asyncio.run(maybe_curate(store, "ses_g", client))
    assert len(out) == 1
    g = out[0]
    assert g.status == "pending"
    assert g.kind == "soft_rule"
    assert g.source_session_id == "ses_g"
    assert g.source_excerpt  # 溯源片段非空

    # 未确认前不进装配
    a = assemble(store)
    assert "【软约定】" not in a["system"]

    # 确认后生效
    store.set_growth_status(g.id, "adopted")
    a2 = assemble(store)
    assert "【软约定】" in a2["system"]
    assert "回复简短" in a2["system"]


def test_curate_dedup_against_facts_and_pending(tmp_path):
    store = ProfileStore(tmp_path, "default")
    store.add_fact("用户希望回复简短", pinned=False)  # 已有事实
    fill_session(store, "ses_d", CURATE_EVERY)
    client = FakeClient('[{"text": "用户希望回复简短一点", "confidence": 0.9}]')
    out = asyncio.run(maybe_curate(store, "ses_d", client))
    assert out == []  # 与已有事实相似 → 丢弃


def test_curate_daily_cap(tmp_path):
    store = ProfileStore(tmp_path, "default")
    for i in range(3):
        store.add_growth(GrowthProposal(text=f"已有领悟{i}"))
    fill_session(store, "ses_c", CURATE_EVERY)
    client = FakeClient('[{"text": "用户喜欢早起", "confidence": 0.7}]')
    out = asyncio.run(maybe_curate(store, "ses_c", client, daily_cap=3))
    assert out == []  # 日配额已满


def test_curate_no_engine_and_bad_json(tmp_path):
    store = ProfileStore(tmp_path, "default")
    fill_session(store, "ses_n", CURATE_EVERY)
    assert asyncio.run(maybe_curate(store, "ses_n", None)) == []

    bad = FakeClient("我觉得没什么好提取的")  # 非 JSON
    assert asyncio.run(maybe_curate(store, "ses_n", bad)) == []
    assert store.list_growth() == []  # 绝不写入垃圾
