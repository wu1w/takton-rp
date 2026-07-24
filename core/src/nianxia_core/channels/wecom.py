"""企业微信通道：自建应用消息 · 文本 + 图片 + 文件。

- corpsecret / EncodingAESKey 存 secrets/channels/wecom.key（JSON，不回显）
- 回调：GET 验证 echostr；POST 解密 → 管线 → 主动 API 发回
- 图片：入站 MediaId 下载；出站 media/upload + image/file 消息
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import struct
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx
from Crypto.Cipher import AES

from ..models import Attachment, ChatRequest
from ..runtime.store import load_app_settings, save_app_settings
from .media_io import (
    collect_tool_images,
    extract_outbound_media,
    run_chat_collect_async,
    save_inbound_bytes,
)
from .telegram import new_pairing_code

logger = logging.getLogger(__name__)

API = "https://qyapi.weixin.qq.com/cgi-bin"


def _aes_key(encoding_aes_key: str) -> bytes:
    return base64.b64decode(encoding_aes_key + "=")


def _pkcs7_pad(data: bytes) -> bytes:
    pad = 32 - len(data) % 32
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    return data[: -data[-1]]


def encrypt_msg(msg: str, corpid: str, aes_key: str) -> str:
    key = _aes_key(aes_key)
    raw = (
        __import__("os").urandom(16)
        + struct.pack(">I", len(msg.encode()))
        + msg.encode()
        + corpid.encode()
    )
    cipher = AES.new(key, AES.MODE_CBC, key[:16])
    return base64.b64encode(cipher.encrypt(_pkcs7_pad(raw))).decode()


def decrypt_msg(encrypt: str, corpid: str, aes_key: str) -> str:
    key = _aes_key(aes_key)
    cipher = AES.new(key, AES.MODE_CBC, key[:16])
    raw = _pkcs7_unpad(cipher.decrypt(base64.b64decode(encrypt)))
    msg_len = struct.unpack(">I", raw[16:20])[0]
    msg = raw[20 : 20 + msg_len].decode()
    got_corp = raw[20 + msg_len :].decode()
    if got_corp != corpid:
        raise ValueError("corpid mismatch")
    return msg


def signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    return hashlib.sha1("".join(sorted([token, timestamp, nonce, encrypt])).encode()).hexdigest()


def _key_path(data_root: Path) -> Path:
    p = data_root / "secrets" / "channels"
    p.mkdir(parents=True, exist_ok=True)
    return p / "wecom.key"


def _wc_cfg(data_root: Path) -> dict[str, Any]:
    s = load_app_settings(data_root)
    return (s.channels or {}).get("wecom") or {}


def _save_wc_cfg(data_root: Path, cfg: dict[str, Any]) -> None:
    s = load_app_settings(data_root)
    channels = dict(s.channels or {})
    channels["wecom"] = cfg
    s.channels = channels
    save_app_settings(data_root, s)


def setup(
    data_root: Path, corpid: str, agentid: int, token: str, corpsecret: str, aes_key: str
) -> dict[str, Any]:
    cfg = _wc_cfg(data_root)
    cfg.update({"corpid": corpid, "agentid": agentid, "token": token})
    cfg.setdefault("allowed_users", [])
    cfg["pairing_code"] = new_pairing_code()
    _save_wc_cfg(data_root, cfg)
    _key_path(data_root).write_text(
        json.dumps({"corpsecret": corpsecret, "aes_key": aes_key}), encoding="utf-8"
    )
    return {"ok": True, "pairing_code": cfg["pairing_code"]}


def status(data_root: Path) -> dict[str, Any]:
    cfg = _wc_cfg(data_root)
    return {
        "enabled": bool(cfg.get("enabled")),
        "configured": bool(cfg.get("corpid")) and _key_path(data_root).exists(),
        "paired_users": len(cfg.get("allowed_users") or []),
        "pairing_code": cfg.get("pairing_code"),
    }


def _secrets(data_root: Path) -> dict[str, str]:
    p = _key_path(data_root)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def verify_callback(
    data_root: Path, msg_signature: str, timestamp: str, nonce: str, echostr: str
) -> str | None:
    cfg = _wc_cfg(data_root)
    sec = _secrets(data_root)
    if not cfg.get("token") or not sec.get("aes_key"):
        return None
    if signature(cfg["token"], timestamp, nonce, echostr) != msg_signature:
        return None
    try:
        return decrypt_msg(echostr, cfg.get("corpid", ""), sec["aes_key"])
    except Exception as e:
        logger.warning("wecom verify decrypt failed: %s", e)
        return None


async def get_access_token(data_root: Path) -> str | None:
    cfg = _wc_cfg(data_root)
    sec = _secrets(data_root)
    if not cfg.get("corpid") or not sec.get("corpsecret"):
        return None
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(
            f"{API}/gettoken",
            params={"corpid": cfg["corpid"], "corpsecret": sec["corpsecret"]},
        )
        data = r.json()
        return data.get("access_token") if data.get("errcode") == 0 else None


async def send_text(data_root: Path, touser: str, text: str) -> bool:
    token = await get_access_token(data_root)
    cfg = _wc_cfg(data_root)
    if not token:
        return False
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(
            f"{API}/message/send",
            params={"access_token": token},
            json={
                "touser": touser,
                "msgtype": "text",
                "agentid": cfg.get("agentid"),
                "text": {"content": text[:2000]},
            },
        )
        return r.json().get("errcode") == 0


async def _upload_media(
    data_root: Path, file_path: Path, media_type: str = "image"
) -> str | None:
    """media/upload → media_id。media_type: image|file|voice|video"""
    token = await get_access_token(data_root)
    if not token:
        return None
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    async with httpx.AsyncClient(timeout=60.0) as c:
        with file_path.open("rb") as f:
            r = await c.post(
                f"{API}/media/upload",
                params={"access_token": token, "type": media_type},
                files={"media": (file_path.name, f, mime)},
            )
        data = r.json()
        if data.get("errcode", 0) not in (0, None) and not data.get("media_id"):
            logger.warning("wecom upload failed: %s", data)
            return None
        return data.get("media_id")


async def send_image(data_root: Path, touser: str, file_path: Path) -> bool:
    mid = await _upload_media(data_root, file_path, "image")
    if not mid:
        return False
    token = await get_access_token(data_root)
    cfg = _wc_cfg(data_root)
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(
            f"{API}/message/send",
            params={"access_token": token},
            json={
                "touser": touser,
                "msgtype": "image",
                "agentid": cfg.get("agentid"),
                "image": {"media_id": mid},
            },
        )
        return r.json().get("errcode") == 0


async def send_file(data_root: Path, touser: str, file_path: Path) -> bool:
    mid = await _upload_media(data_root, file_path, "file")
    if not mid:
        return False
    token = await get_access_token(data_root)
    cfg = _wc_cfg(data_root)
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(
            f"{API}/message/send",
            params={"access_token": token},
            json={
                "touser": touser,
                "msgtype": "file",
                "agentid": cfg.get("agentid"),
                "file": {"media_id": mid},
            },
        )
        return r.json().get("errcode") == 0


async def _download_media(data_root: Path, media_id: str) -> bytes | None:
    token = await get_access_token(data_root)
    if not token or not media_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.get(
                f"{API}/media/get",
                params={"access_token": token, "media_id": media_id},
            )
            ct = r.headers.get("content-type", "")
            if "json" in ct or r.content[:1] == b"{":
                logger.warning("wecom media get error: %s", r.text[:200])
                return None
            return r.content
    except Exception as e:
        logger.warning("wecom download media failed: %s", e)
        return None


async def handle_callback_body(
    data_root: Path, msg_signature: str, timestamp: str, nonce: str, body: bytes
) -> dict[str, Any]:
    s = load_app_settings(data_root)
    if not (s.channels or {}).get("master_enabled"):
        return {"handled": False, "reason": "master off"}
    cfg = (s.channels or {}).get("wecom") or {}
    if not cfg.get("enabled"):
        return {"handled": False, "reason": "wecom off"}
    sec = _secrets(data_root)

    try:
        root = ET.fromstring(body.decode())
        encrypt = root.findtext("Encrypt", "")
        if signature(cfg["token"], timestamp, nonce, encrypt) != msg_signature:
            return {"handled": False, "reason": "bad signature"}
        plain = decrypt_msg(encrypt, cfg.get("corpid", ""), sec["aes_key"])
        msg = ET.fromstring(plain)
    except Exception as e:
        logger.warning("wecom callback parse failed: %s", e)
        return {"handled": False, "reason": "parse"}

    msg_type = msg.findtext("MsgType") or ""
    user = msg.findtext("FromUserName", "")
    text = (msg.findtext("Content") or "").strip()
    atts: list[Attachment] = []

    if msg_type == "image":
        mid = msg.findtext("MediaId") or ""
        raw = await _download_media(data_root, mid)
        if raw:
            a = save_inbound_bytes(data_root, raw, filename="wecom.jpg", kind_hint="image")
            if a:
                atts.append(a)
        text = text or "（发来了图片）"
    elif msg_type == "file":
        mid = msg.findtext("MediaId") or ""
        fname = msg.findtext("FileName") or "file.bin"
        raw = await _download_media(data_root, mid)
        if raw:
            a = save_inbound_bytes(data_root, raw, filename=fname, kind_hint="file")
            if a:
                atts.append(a)
        text = text or f"（发来了文件：{fname}）"
    elif msg_type != "text":
        return {"handled": False, "reason": f"unsupported MsgType={msg_type}"}

    if not user or (not text and not atts):
        return {"handled": False}

    allowed = cfg.get("allowed_users") or []
    if user not in allowed:
        code = cfg.get("pairing_code")
        if code and text and code in text.upper():
            allowed.append(user)
            cfg["allowed_users"] = allowed
            _save_wc_cfg(data_root, cfg)
            await send_text(data_root, user, "绑定好啦，以后在这里说话他都会记得。")
            return {"handled": True, "paired": True}
        await send_text(data_root, user, "还没配对。在念匣设置里拿配对码发给我。")
        return {"handled": True, "paired": False}

    from ..memory import ProfileStore
    from . import bound_profile_id

    pid = bound_profile_id(data_root, "wecom")
    store = ProfileStore(data_root, pid)
    sid = store.resolve_chat_session_id()
    req = ChatRequest(
        profile_id=pid,
        session_id=sid,
        message=text or "（发来了附件）",
        tier="L1",
        attachments=atts,
    )
    out = await run_chat_collect_async(store, req, enable_tools=True)
    reply = out["reply"]
    cleaned, paths = extract_outbound_media(reply, data_root)
    paths = paths + collect_tool_images(out.get("image_paths") or [], data_root)

    ok = True
    if cleaned:
        ok = await send_text(data_root, user, cleaned) and ok
    for p in paths[:5]:
        try:
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                ok = await send_image(data_root, user, p) and ok
            else:
                ok = await send_file(data_root, user, p) and ok
        except Exception as e:
            logger.warning("wecom send media failed: %s", e)
            await send_text(data_root, user, f"（文件 {p.name} 发送失败）")
            ok = False

    return {"handled": True, "reply": cleaned or reply, "sent": ok, "media": len(paths)}
