"""API：health / clock / facts / chat SSE 端到端。"""

import json

import pytest
from fastapi.testclient import TestClient

from nianxia_core.api.app import create_app
from nianxia_core.config import get_settings


@pytest.fixture()
def client(tmp_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("NIANXIA_DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_clock(client):
    r = client.get("/v1/clock")
    assert r.status_code == 200
    assert r.json()["source"] == "device"


def test_fact_remember_and_recall(client):
    r = client.post(
        "/v1/profiles/default/facts",
        json={"text": "用户住在杭州", "pinned": True},
    )
    assert r.status_code == 200
    assert r.json()["pinned"] is True

    r = client.get("/v1/profiles/default/facts")
    assert any(f["text"] == "用户住在杭州" for f in r.json()["items"])

    r = client.get("/v1/profiles/default/recall", params={"q": "杭州"})
    assert len(r.json()["items"]) == 1


def test_chat_stream_engine_unavailable(client):
    """未配置引擎时：如实报 engine_unavailable，绝不伪造回复。"""
    with client.stream(
        "POST",
        "/v1/chat/stream",
        json={"profile_id": "default", "message": "在吗", "tier": "L0"},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())

    assert "event: session" in body
    assert "event: trace" in body
    assert "event: message_end" in body
    assert "event: delta" not in body  # 红线：无 mock 回复
    assert "engine_unavailable" in body
    assert '"engine": "none"' in body or '"engine":"none"' in body

    # 会话落盘可对账（user 消息必须落盘，即便引擎未接入）
    sid = None
    for line in body.splitlines():
        if line.startswith("data:") and "session_id" in line:
            payload = json.loads(line[5:])
            if "session_id" in payload:
                sid = payload["session_id"]
                break
    assert sid and sid.startswith("ses_")


def test_profiles_seeded(client):
    r = client.get("/v1/profiles")
    assert r.status_code == 200
    assert r.json()["items"][0]["name"]
