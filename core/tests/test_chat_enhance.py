"""聊天增强：跨会话搜索 / 会话分支 / 卡头像上传 / TTS 音色参数 / 视觉补人设错误路径。"""

import pytest
from fastapi.testclient import TestClient

from nianxia_core.api.app import app
from nianxia_core.memory.store import ProfileStore
from nianxia_core.models import ChatMessage


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from nianxia_core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "data_root", tmp_path)
    return TestClient(app), tmp_path


def _seed_session(root, pid, texts):
    store = ProfileStore(root, pid)
    sid = ProfileStore.new_session_id()
    for role, text in texts:
        store.append_message(sid, ChatMessage(role=role, content=text))
    return sid


def test_search_across_sessions(env):
    c, root = env
    _seed_session(root, "default", [("user", "今天去吃了火锅"), ("assistant", "辣不辣呀")])
    _seed_session(root, "default", [("user", "周末想去看海"), ("assistant", "好呀")])
    r = c.get("/v1/profiles/default/search", params={"q": "火锅"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["role"] == "user"
    assert "火锅" in items[0]["snippet"]
    # 空查询
    assert c.get("/v1/profiles/default/search", params={"q": " "}).json()["items"] == []
    # 无命中
    assert c.get("/v1/profiles/default/search", params={"q": "不存在词"}).json()["items"] == []


def test_branch_session(env):
    c, root = env
    sid = _seed_session(
        root, "default", [("user", "第一句"), ("assistant", "第二句"), ("user", "第三句"), ("assistant", "第四句")]
    )
    r = c.post(f"/v1/profiles/default/sessions/{sid}/branch", json={"upto": 1})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and d["msg_count"] == 2
    new_sid = d["session_id"]
    assert new_sid != sid
    msgs = ProfileStore(root, "default").recent_messages(new_sid, limit=10)
    assert [m.content for m in msgs] == ["第一句", "第二句"]
    # 旧会话原样保留
    old = ProfileStore(root, "default").recent_messages(sid, limit=10)
    assert len(old) == 4
    # upto 越界收敛到末条
    r2 = c.post(f"/v1/profiles/default/sessions/{sid}/branch", json={"upto": 999})
    assert r2.json()["msg_count"] == 4
    # 不存在的会话
    assert c.post("/v1/profiles/default/sessions/nope/branch", json={"upto": 0}).status_code == 404


def test_card_avatar_upload_and_from(env):
    c, root = env
    r = c.post("/v1/cards", json={"name": "测试卡", "description": "d"})
    cid = r.json()["id"]
    # 上传头像
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    r2 = c.post(f"/v1/cards/{cid}/avatar", files={"file": ("face.png", png, "image/png")})
    assert r2.status_code == 200
    d = r2.json()
    assert d["avatar"].startswith("media/cards/")
    assert "avatar_url" in d
    assert (root / d["avatar"]).read_bytes() == png
    # 非法格式
    bad = c.post(f"/v1/cards/{cid}/avatar", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 400
    # avatar-from：复用已上传文件
    r3 = c.post(f"/v1/cards/{cid}/avatar-from", json={"rel": d["avatar"]})
    assert r3.status_code == 200
    # 路径逃逸被拒
    esc = c.post(f"/v1/cards/{cid}/avatar-from", json={"rel": "../secret.png"})
    assert esc.status_code == 404
    # 不存在的卡
    assert c.post("/v1/cards/nope/avatar", files={"file": ("f.png", png, "image/png")}).status_code == 404


def test_tts_voice_param_and_disabled(env):
    c, root = env
    # 关掉朗读开关 → 如实拒绝（不装会读）
    s = c.get("/v1/settings").json()
    s["media"]["tts"]["enabled"] = False
    c.put("/v1/settings", json=s)
    r = c.post("/v1/media/tts", json={"text": "你好", "voice": "zh-CN-YunxiNeural"})
    assert r.json()["ok"] is False
    assert "未开启" in r.json()["error"]


def test_infer_persona_honest_errors(env):
    c, root = env
    # 文件不存在
    r = c.post("/v1/media/infer-persona", json={"rel": "media/cards/none.png"})
    assert r.status_code == 404
    # 文件存在但无 mmproj（tmp 环境没有模型）→ 如实报没视觉
    media = root / "media" / "cards"
    media.mkdir(parents=True)
    (media / "face.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    r2 = c.post("/v1/media/infer-persona", json={"rel": "media/cards/face.png"})
    d = r2.json()
    assert d["ok"] is False
    assert "视觉" in d["error"] or "没跑起来" in d["error"]
