"""Open loops：规则提取 / ≥6h 召回门控 / 闭环。"""

import time

from nianxia_core.memory import ProfileStore, assemble
from nianxia_core.memory.openloops import (
    detect_deferral,
    make_loop,
    topic_already_open,
)


def test_deferral_detection():
    assert detect_deferral("今天累了，这件事我们下次再说")
    assert detect_deferral("改天再聊这个吧")
    assert detect_deferral("明天再讲")
    assert not detect_deferral("我明天要早起")
    assert not detect_deferral("今天天气不错")


def test_loop_lifecycle_and_recall_gate(tmp_path):
    store = ProfileStore(tmp_path, "default")
    loop = make_loop("周末去哪玩，下次再说")
    store.add_open_loop(loop)

    # 距上次会话 < 6h：不召回（不刷屏）
    bond = store.load_bond()
    bond.last_session_at = time.time() - 3600  # 1h 前
    store.save_bond(bond)
    a = assemble(store)
    assert "【未完话头】" not in a["system"]

    # ≥6h：召回
    bond.last_session_at = time.time() - 7 * 3600
    store.save_bond(bond)
    a2 = assemble(store)
    assert "【未完话头】" in a2["system"]
    assert "周末去哪玩" in a2["system"]

    # 闭环后不再召回
    assert store.close_open_loop(loop["id"]) is True
    a3 = assemble(store)
    assert "周末去哪玩" not in a3["system"]


def test_topic_dedup():
    loops = [{"id": "x", "topic": "周末去哪玩，下次再说", "status": "open"}]
    assert topic_already_open(loops, "周末去哪玩，改天再聊")
    assert not topic_already_open(loops, "完全不相干的话题")
