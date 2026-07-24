"""QQ 官方机器人：AppID+AppSecret setup / 配对 / 管线（假 token+API）。"""

import asyncio

from nianxia_core.channels import qqbot
from nianxia_core.runtime.store import load_app_settings, save_app_settings


async def fake_token(app_id: str, secret: str) -> dict:
    if app_id == "bad":
        return {"error": "invalid"}
    return {"access_token": "tok_test", "expires_in": 7200}


class FakeApi:
    def __init__(self):
        self.calls: list[tuple] = []

    async def __call__(self, method: str, path: str, token: str, body: dict | None) -> dict:
        self.calls.append((method, path, body))
        if path == "/gateway":
            return {"url": "wss://example.invalid/ws"}
        return {"id": "m1", "file_info": "fi_test"}


def enable(root):
    s = load_app_settings(root)
    ch = dict(s.channels or {})
    ch["master_enabled"] = True
    qq = dict(ch.get("qqbot") or {})
    qq["enabled"] = True
    ch["qqbot"] = qq
    s.channels = ch
    save_app_settings(root, s)


def test_setup_appid_secret(tmp_path):
    r = qqbot.setup(tmp_path, "app123", "sec456")
    assert r["ok"] and r["app_id"] == "app123" and len(r["pairing_code"]) == 6
    st = qqbot.status(tmp_path)
    assert st["configured"] is True and st["app_id"] == "app123"
    # secret 不在 status 里
    assert "sec456" not in str(st)
    sec = qqbot._load_secrets(tmp_path)
    assert sec["client_secret"] == "sec456"


def test_setup_validate_rejects_bad(tmp_path):
    ad = qqbot.QQBotAdapter(tmp_path, token_fn=fake_token)
    r = asyncio.run(ad.setup_validate("bad", "x"))
    assert r["ok"] is False


def test_pairing_and_chat(tmp_path):
    qqbot.setup(tmp_path, "app1", "sec1")
    enable(tmp_path)
    api = FakeApi()
    ad = qqbot.QQBotAdapter(tmp_path, token_fn=fake_token, api_fn=api)

    code = qqbot._qq_cfg(tmp_path)["pairing_code"]

    # 未配对
    r = asyncio.run(
        ad.handle_inbound(chat_id="u1", user_id="u1", text="在吗", chat_type="c2c")
    )
    assert r.get("paired") is False
    assert any(
        c[1].endswith("/messages") and "配对" in str((c[2] or {}).get("content", ""))
        for c in api.calls
    )

    # 配对
    r2 = asyncio.run(
        ad.handle_inbound(chat_id="u1", user_id="u1", text=code, chat_type="c2c")
    )
    assert r2.get("paired") is True
    assert "u1" in qqbot._qq_cfg(tmp_path)["allowed_users"]

    # 已配对走管线（无引擎如实报错）
    api.calls.clear()
    r3 = asyncio.run(
        ad.handle_inbound(chat_id="u1", user_id="u1", text="在吗", chat_type="c2c")
    )
    assert "还没有接入推理引擎" in (r3.get("reply") or "")

    from nianxia_core.memory import ProfileStore

    store = ProfileStore(tmp_path, "default")
    sid = store.resolve_chat_session_id()
    assert any(m.content == "在吗" for m in store.recent_messages(sid, limit=10))


def test_master_gate(tmp_path):
    qqbot.setup(tmp_path, "a", "b")
    # master off
    ad = qqbot.QQBotAdapter(tmp_path, token_fn=fake_token, api_fn=FakeApi())
    r = asyncio.run(ad.handle_inbound(chat_id="u", user_id="u", text="hi"))
    assert r["handled"] is False
