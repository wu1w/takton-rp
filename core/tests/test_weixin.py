"""微信 iLink：setup 落盘 / 配对 / 管线（假 API）。"""

import asyncio

from nianxia_core.channels import weixin
from nianxia_core.runtime.store import load_app_settings, save_app_settings


class FakeApi:
    def __init__(self):
        self.calls = []
        self.qr_status = "wait"
        self.n = 0

    async def __call__(self, method, endpoint, payload, token):
        self.calls.append((method, endpoint, payload, token))
        if "get_bot_qrcode" in endpoint:
            return {"qrcode": "QRCODE123", "qrcode_img_content": "https://example.test/qr"}
        if "get_qrcode_status" in endpoint:
            self.n += 1
            if self.n < 2:
                return {"status": "wait"}
            return {
                "status": "confirmed",
                "ilink_bot_id": "bot_acc",
                "bot_token": "tok_wx",
                "baseurl": "https://ilinkai.weixin.qq.com",
                "ilink_user_id": "u_owner",
            }
        if endpoint.endswith("sendmessage") or "sendmessage" in endpoint:
            return {"ret": 0}
        if "getupdates" in endpoint:
            return {"ret": 0, "msgs": [], "get_updates_buf": "buf1"}
        return {"ret": 0}


def enable(root):
    s = load_app_settings(root)
    ch = dict(s.channels or {})
    ch["master_enabled"] = True
    wx = dict(ch.get("weixin") or {})
    wx["enabled"] = True
    ch["weixin"] = wx
    s.channels = ch
    save_app_settings(root, s)


def test_qr_login_saves_secrets(tmp_path):
    api = FakeApi()
    ad = weixin.WeixinAdapter(tmp_path, api_fn=api)
    r = asyncio.run(ad.qr_start())
    assert r["ok"] and r["qrcode"] == "QRCODE123"
    p1 = asyncio.run(ad.qr_poll("QRCODE123"))
    assert p1["status"] == "wait"
    p2 = asyncio.run(ad.qr_poll("QRCODE123"))
    assert p2["status"] == "confirmed" and p2.get("account_id") == "bot_acc"
    st = weixin.status(tmp_path)
    assert st["configured"] is True and st["account_id"] == "bot_acc"
    sec = weixin._load_secrets(tmp_path)
    assert sec["token"] == "tok_wx"
    assert "tok_wx" not in str(st)


def test_pairing_and_chat(tmp_path):
    # seed credentials
    weixin._save_secrets(
        tmp_path,
        {"account_id": "bot_acc", "token": "tok", "base_url": "https://ilinkai.weixin.qq.com"},
    )
    cfg = weixin._wx_cfg(tmp_path)
    cfg["pairing_code"] = "AABBCC"
    weixin._save_wx_cfg(tmp_path, cfg)
    enable(tmp_path)

    api = FakeApi()
    ad = weixin.WeixinAdapter(tmp_path, api_fn=api)

    r = asyncio.run(
        ad.handle_inbound_message(
            {
                "from_user_id": "user1",
                "context_token": "ctx1",
                "item_list": [{"type": 1, "text_item": {"text": "在吗"}}],
            }
        )
    )
    assert r.get("paired") is False

    r2 = asyncio.run(
        ad.handle_inbound_message(
            {
                "from_user_id": "user1",
                "context_token": "ctx1",
                "item_list": [{"type": 1, "text_item": {"text": "AABBCC"}}],
            }
        )
    )
    assert r2.get("paired") is True
    assert "user1" in weixin._wx_cfg(tmp_path)["allowed_users"]
    assert weixin._load_ctx(tmp_path).get("user1") == "ctx1"

    r3 = asyncio.run(
        ad.handle_inbound_message(
            {
                "from_user_id": "user1",
                "context_token": "ctx2",
                "item_list": [{"type": 1, "text_item": {"text": "在吗"}}],
            }
        )
    )
    assert "还没有接入推理引擎" in (r3.get("reply") or "")

    from nianxia_core.memory import ProfileStore

    store = ProfileStore(tmp_path, "default")
    sid = store.resolve_chat_session_id()
    assert any(m.content == "在吗" for m in store.recent_messages(sid, limit=10))


def test_master_gate(tmp_path):
    weixin._save_secrets(tmp_path, {"account_id": "a", "token": "t", "base_url": weixin.ILINK_BASE})
    ad = weixin.WeixinAdapter(tmp_path, api_fn=FakeApi())
    r = asyncio.run(
        ad.handle_inbound_message(
            {"from_user_id": "u", "item_list": [{"type": 1, "text_item": {"text": "hi"}}]}
        )
    )
    assert r["handled"] is False
