"""TG 通道：配对流 / 未配对拒绝 / 总开关门控 / 管线接入（假 api_call）。"""

import asyncio

from nianxia_core.channels.telegram import (
    TelegramAdapter,
    load_token,
    new_pairing_code,
)
from nianxia_core.runtime.store import load_app_settings, save_app_settings


class FakeTG:
    """假的 Bot API：记录调用，预置 getMe 与空 updates。"""

    def __init__(self):
        self.sent: list[dict] = []

    async def __call__(self, token: str, method: str, payload: dict) -> dict:
        if method == "getMe":
            return {"id": 1, "username": "nianxia_test_bot"}
        if method == "sendMessage":
            self.sent.append(payload)
            return {"ok": True}
        if method == "getUpdates":
            return []
        return {}


def enable_channels(root):
    s = load_app_settings(root)
    s.channels = {"master_enabled": True, "telegram": {"enabled": True}}
    save_app_settings(root, s)


def test_setup_stores_token_and_code(tmp_path):
    ad = TelegramAdapter(tmp_path, api_call=FakeTG())
    r = asyncio.run(ad.setup("123:abc"))
    assert r["ok"] and r["bot"] == "nianxia_test_bot"
    assert len(r["pairing_code"]) == 6
    assert load_token(tmp_path) == "123:abc"  # 存 secrets，不回显


def test_pairing_flow(tmp_path):
    fake = FakeTG()
    ad = TelegramAdapter(tmp_path, api_call=fake)
    asyncio.run(ad.setup("123:abc"))
    from nianxia_core.channels.telegram import _tg_cfg

    code = _tg_cfg(tmp_path)["pairing_code"]

    # 未配对消息 → 提示配对
    asyncio.run(ad._handle_message("123:abc", {"chat": {"id": 777}, "text": "在吗"}))
    assert "还没配对" in fake.sent[-1]["text"]

    # 发配对码 → 绑定成功
    asyncio.run(ad._handle_message("123:abc", {"chat": {"id": 777}, "text": code}))
    assert "绑定好啦" in fake.sent[-1]["text"]
    assert 777 in _tg_cfg(tmp_path)["allowed_chat_ids"]


def test_paired_message_runs_pipeline_no_engine(tmp_path):
    """配对后的消息走聊天管线；无引擎时如实回报错文案（不伪造回复）。"""
    fake = FakeTG()
    ad = TelegramAdapter(tmp_path, api_call=fake)
    asyncio.run(ad.setup("123:abc"))
    from nianxia_core.channels.telegram import _tg_cfg

    cfg = _tg_cfg(tmp_path)
    cfg["allowed_chat_ids"] = [888]
    from nianxia_core.channels.telegram import _save_tg_cfg

    _save_tg_cfg(tmp_path, cfg)

    asyncio.run(ad._handle_message("123:abc", {"chat": {"id": 888}, "text": "在吗"}))
    reply = fake.sent[-1]["text"]
    assert "还没有接入推理引擎" in reply  # 诚实报错而非编造

    # 消息真实落盘（通道与桌面共用当前角色会话）
    from nianxia_core.memory import ProfileStore

    store = ProfileStore(tmp_path, "default")
    sid = store.resolve_chat_session_id()
    msgs = store.recent_messages(sid, limit=10)
    assert any(m.content == "在吗" for m in msgs)


def test_pairing_code_format():
    code = new_pairing_code()
    assert len(code) == 6 and code == code.upper()
