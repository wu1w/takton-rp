"""角色=会话 + 记忆/软约定按角色隔离。"""

from pathlib import Path

from fastapi.testclient import TestClient

from nianxia_core.api.app import app
from nianxia_core.memory.store import ProfileStore, session_id_for_card
from nianxia_core.models import Fact, GrowthProposal


def test_session_id_for_card():
    assert session_id_for_card(None) == "ses___persona__"
    assert session_id_for_card("card_abc") == "ses_card_abc"


def test_one_card_one_session(tmp_path, monkeypatch):
    from nianxia_core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "data_root", tmp_path)
    c = TestClient(app)

    r = c.post(
        "/v1/cards",
        json={"name": "阿茶", "first_mes": "（抬头）欢迎光临"},
    )
    assert r.status_code == 200
    cid = r.json()["id"]

    r1 = c.post("/v1/profiles/default/active-card", json={"card_id": cid})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["session_id"] == session_id_for_card(cid)
    assert d1["created"] is True
    assert "欢迎光临" in d1["greeting"]

    # 再启用一次：幂等，不新建
    r2 = c.post("/v1/profiles/default/active-card", json={"card_id": cid})
    assert r2.json()["session_id"] == d1["session_id"]
    assert r2.json()["created"] is False

    # create_session 兼容接口也回到同一条
    r3 = c.post("/v1/profiles/default/sessions")
    assert r3.json()["session_id"] == d1["session_id"]

    latest = c.get("/v1/profiles/default/sessions/latest").json()
    assert latest["session_id"] == d1["session_id"]
    assert latest["card_id"] == cid
    assert latest["items"][0]["content"] == d1["greeting"]


def test_memory_isolated_by_card(tmp_path, monkeypatch):
    from nianxia_core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "data_root", tmp_path)
    c = TestClient(app)

    a = c.post("/v1/cards", json={"name": "角色A", "first_mes": "我是A"}).json()["id"]
    b = c.post("/v1/cards", json={"name": "角色B", "first_mes": "我是B"}).json()["id"]

    c.post("/v1/profiles/default/active-card", json={"card_id": a})
    c.post("/v1/profiles/default/facts", json={"text": "A记得：用户爱猫", "pinned": True})

    c.post("/v1/profiles/default/active-card", json={"card_id": b})
    c.post("/v1/profiles/default/facts", json={"text": "B记得：用户爱狗", "pinned": True})

    # B 视角
    facts_b = c.get("/v1/profiles/default/facts").json()["items"]
    texts_b = {f["text"] for f in facts_b}
    assert "B记得：用户爱狗" in texts_b
    assert "A记得：用户爱猫" not in texts_b

    # 切回 A
    c.post("/v1/profiles/default/active-card", json={"card_id": a})
    facts_a = c.get("/v1/profiles/default/facts").json()["items"]
    texts_a = {f["text"] for f in facts_a}
    assert "A记得：用户爱猫" in texts_a
    assert "B记得：用户爱狗" not in texts_a

    store = ProfileStore(tmp_path, "default")
    store.add_growth(
        GrowthProposal(text="A的软约定：睡前说晚安", kind="soft_rule", card_id=a)
    )
    store.add_growth(
        GrowthProposal(text="B的软约定：不聊工作", kind="soft_rule", card_id=b)
    )
    # active is A
    g = store.list_growth()
    assert len(g) == 1 and "晚安" in g[0].text
