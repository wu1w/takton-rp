"""Swipes / 编辑+重生成 / 设定书 Lite 的后端测试。"""

import json

import pytest

from nianxia_core.memory.store import ProfileStore
from nianxia_core.models import CharacterCard, ChatMessage, LoreEntry


def _mk_store(tmp_path):
    return ProfileStore(tmp_path, "default")


def _seed_session(store, sid):
    store.append_message(sid, ChatMessage(role="user", content="你好"))
    store.append_message(sid, ChatMessage(role="assistant", content="你好呀", swipes=["你好呀"]))
    store.append_message(sid, ChatMessage(role="user", content="今天怎么样"))
    store.append_message(sid, ChatMessage(role="assistant", content="不错呢", swipes=["不错呢"]))


# ---------- store 助手 ----------

def test_update_message_and_truncate(tmp_path):
    store = _mk_store(tmp_path)
    sid = "ses_t1"
    _seed_session(store, sid)
    msgs = store.recent_messages(sid, limit=10)
    # 更新第二条（assistant）
    m = store.update_message(sid, msgs[1].id, content="改后的回复", swipe_idx=0)
    assert m is not None and m.content == "改后的回复"
    # 截断：删掉第二条之后的两条
    removed = store.truncate_after(sid, msgs[1].id)
    assert removed == 2
    left = store.recent_messages(sid, limit=10)
    assert len(left) == 2 and left[-1].content == "改后的回复"


def test_update_missing_returns_none(tmp_path):
    store = _mk_store(tmp_path)
    sid = "ses_t2"
    _seed_session(store, sid)
    assert store.update_message(sid, "msg_nope", content="x") is None


# ---------- swipe 切换（无引擎路径，纯本地） ----------

@pytest.mark.anyio
async def test_swipe_prev_next_local(tmp_path):
    from nianxia_core.runtime.companion import run_swipe

    store = _mk_store(tmp_path)
    sid = "ses_t3"
    store.append_message(sid, ChatMessage(role="user", content="问"))
    store.append_message(sid, ChatMessage(
        role="assistant", content="第二版",
        swipes=["第一版", "第二版"], swipe_idx=1,
    ))
    target = store.recent_messages(sid, limit=10)[-1]

    events = []
    async for ev in run_swipe("default", sid, target.id, "prev", "L0", store):
        events.append(ev)
    data = [l for e in events for l in e.splitlines() if l.startswith("data:")]
    obj = json.loads(data[0][5:])
    assert obj["swipe_idx"] == 0 and obj["content"] == "第一版" and obj["swipes_count"] == 2
    # 持久化了
    assert store.recent_messages(sid, limit=10)[-1].content == "第一版"


@pytest.mark.anyio
async def test_swipe_rejects_user_message(tmp_path):
    from nianxia_core.runtime.companion import run_swipe

    store = _mk_store(tmp_path)
    sid = "ses_t4"
    _seed_session(store, sid)
    user_msg = [m for m in store.recent_messages(sid, limit=10) if m.role == "user"][0]
    events = []
    async for ev in run_swipe("default", sid, user_msg.id, "new", "L0", store):
        events.append(ev)
    assert any("只能对角色的回复重抽" in e for e in events)


@pytest.mark.anyio
async def test_swipe_new_no_engine_honest_error(tmp_path):
    """无引擎时 swipe new 如实报 engine_unavailable，不伪造变体。"""
    from nianxia_core.runtime.companion import run_swipe

    store = _mk_store(tmp_path)
    sid = "ses_t5"
    _seed_session(store, sid)
    target = store.recent_messages(sid, limit=10)[-1]
    events = []
    async for ev in run_swipe("default", sid, target.id, "new", "L0", store):
        events.append(ev)
    text = "".join(events)
    assert "engine_unavailable" in text
    # swipes 没有被伪造内容污染
    m = store.recent_messages(sid, limit=10)[-1]
    assert m.swipes == ["不错呢"]


# ---------- regen（无引擎路径） ----------

@pytest.mark.anyio
async def test_regen_requires_user_tail(tmp_path):
    from nianxia_core.runtime.companion import run_regen

    store = _mk_store(tmp_path)
    sid = "ses_t6"
    _seed_session(store, sid)  # 尾部是 assistant
    events = []
    async for ev in run_regen("default", sid, "L0", store):
        events.append(ev)
    assert any("没法续写" in e for e in events)


# ---------- 设定书 Lite 装配 ----------

def test_lorebook_keyword_and_constant(tmp_path):
    from nianxia_core.memory.assemble import assemble
    from nianxia_core.runtime.cards import CardStore

    store = _mk_store(tmp_path)
    cs = CardStore(tmp_path)
    card = cs.save(CharacterCard(name="测试卡"))
    card.lorebook = [
        LoreEntry(keys=["青茗山"], content="青茗山是狐族圣地，终年云雾。"),
        LoreEntry(keys=["不存在的关键词"], content="不该注入的条目。"),
        LoreEntry(constant=True, content="常驻设定：世界里有灵力。", order=10),
        LoreEntry(keys=["禁用词"], content="被禁用的。", enabled=False),
    ]
    cs.save(card)
    persona = store.load_persona()
    persona.active_card_id = card.id
    store.save_persona(persona)

    asm = assemble(store, tier="L1", query="我们什么时候去青茗山看看？")
    sys_text = asm["system"]
    assert "青茗山是狐族圣地" in sys_text       # 关键词命中
    assert "常驻设定：世界里有灵力" in sys_text  # 常驻
    assert "不该注入的条目" not in sys_text      # 未命中
    assert "被禁用的" not in sys_text            # enabled=False


def test_lorebook_scans_chat_history(tmp_path):
    from nianxia_core.memory.assemble import assemble
    from nianxia_core.runtime.cards import CardStore

    store = _mk_store(tmp_path)
    cs = CardStore(tmp_path)
    card = cs.save(CharacterCard(name="测试卡2"))
    card.lorebook = [LoreEntry(keys=["灵茶"], content="灵茶能恢复灵力。")]
    cs.save(card)
    persona = store.load_persona()
    persona.active_card_id = card.id
    store.save_persona(persona)

    sid = "ses_lore"
    store.append_message(sid, ChatMessage(role="user", content="我泡了壶灵茶"))
    asm = assemble(store, tier="L1", query="接着聊", session_id=sid)
    assert "灵茶能恢复灵力" in asm["system"]  # query 没提但历史里有 → 命中


def test_lorebook_cut_at_low_scale(tmp_path):
    from nianxia_core.memory.assemble import assemble
    from nianxia_core.runtime.cards import CardStore

    store = _mk_store(tmp_path)
    cs = CardStore(tmp_path)
    card = cs.save(CharacterCard(name="测试卡3"))
    card.lorebook = [LoreEntry(constant=True, content="常驻设定X。")]
    cs.save(card)
    persona = store.load_persona()
    persona.active_card_id = card.id
    store.save_persona(persona)

    asm = assemble(store, tier="L1", scale=0.25)
    assert "常驻设定X" not in asm["system"]
