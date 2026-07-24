"""微信个人号机器人（iLink Bot API）— 对齐 Hermes weixin。

- 扫码登录：get_bot_qrcode → get_qrcode_status → 落盘 account_id + token
- 入站：long-poll getupdates
- 出站：sendmessage（须带 context_token）
- 媒体：AES-128-ECB CDN 上下传
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
import secrets
import struct
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

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

ILINK_BASE = "https://ilinkai.weixin.qq.com"
CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"
ILINK_APP_ID = "bot"
CHANNEL_VERSION = "2.2.0"
ILINK_APP_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0

EP_GET_UPDATES = "ilink/bot/getupdates"
EP_SEND_MESSAGE = "ilink/bot/sendmessage"
EP_GET_UPLOAD_URL = "ilink/bot/getuploadurl"
EP_GET_BOT_QR = "ilink/bot/get_bot_qrcode"
EP_GET_QR_STATUS = "ilink/bot/get_qrcode_status"

ITEM_TEXT, ITEM_IMAGE, ITEM_FILE = 1, 2, 4
MSG_TYPE_BOT, MSG_STATE_FINISH = 2, 2
MEDIA_IMAGE, MEDIA_FILE = 1, 3

ApiFn = Callable[[str, str, dict | None, str | None], Awaitable[dict]]  # method, endpoint, payload, token


def _wx_cfg(data_root: Path) -> dict[str, Any]:
    s = load_app_settings(data_root)
    return (s.channels or {}).get("weixin") or {}


def _save_wx_cfg(data_root: Path, cfg: dict[str, Any]) -> None:
    s = load_app_settings(data_root)
    channels = dict(s.channels or {})
    channels["weixin"] = cfg
    s.channels = channels
    save_app_settings(data_root, s)


def _secrets_path(data_root: Path) -> Path:
    p = data_root / "secrets" / "channels"
    p.mkdir(parents=True, exist_ok=True)
    return p / "weixin.key"


def _load_secrets(data_root: Path) -> dict[str, str]:
    p = _secrets_path(data_root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_secrets(data_root: Path, data: dict[str, str]) -> None:
    _secrets_path(data_root).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _ctx_path(data_root: Path) -> Path:
    p = data_root / "secrets" / "channels" / "weixin_context.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_ctx(data_root: Path) -> dict[str, str]:
    p = _ctx_path(data_root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_ctx(data_root: Path, m: dict[str, str]) -> None:
    _ctx_path(data_root).write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")


def _sync_path(data_root: Path) -> Path:
    return data_root / "secrets" / "channels" / "weixin_sync.json"


def status(data_root: Path) -> dict[str, Any]:
    cfg = _wx_cfg(data_root)
    sec = _load_secrets(data_root)
    ad = get_adapter(data_root)
    return {
        "enabled": bool(cfg.get("enabled")),
        "configured": bool(sec.get("token") and sec.get("account_id")),
        "account_id": sec.get("account_id") or cfg.get("account_id") or "",
        "paired_users": len(cfg.get("allowed_users") or []),
        "pairing_code": cfg.get("pairing_code"),
        "running": bool(ad.running),
        # 兼容旧 status 键：前端曾用 wecom
        "kind": "weixin",
    }


def _headers(token: str | None, body: str) -> dict[str, str]:
    uin = base64.b64encode(str(struct.unpack(">I", secrets.token_bytes(4))[0]).encode()).decode()
    h = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": uin,
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    n = block - (len(data) % block)
    return data + bytes([n]) * n


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    n = data[-1]
    if 1 <= n <= 16 and data.endswith(bytes([n]) * n):
        return data[:-n]
    return data


def _aes_enc(plain: bytes, key: bytes) -> bytes:
    c = AES.new(key, AES.MODE_ECB)
    return c.encrypt(_pkcs7_pad(plain))


def _aes_dec(cipher: bytes, key: bytes) -> bytes:
    c = AES.new(key, AES.MODE_ECB)
    return _pkcs7_unpad(c.decrypt(cipher))


def _parse_aes_key(b64: str) -> bytes:
    raw = base64.b64decode(b64)
    if len(raw) == 16:
        return raw
    if len(raw) == 32:
        t = raw.decode("ascii", errors="ignore")
        if all(ch in "0123456789abcdefABCDEF" for ch in t):
            return bytes.fromhex(t)
    raise ValueError("bad aes key")


def _extract_text(item_list: list) -> str:
    parts: list[str] = []
    for it in item_list or []:
        if not isinstance(it, dict):
            continue
        if it.get("type") == ITEM_TEXT:
            t = ((it.get("text_item") or {}).get("text") or "").strip()
            if t:
                parts.append(t)
    return "\n".join(parts).strip()


class WeixinAdapter:
    def __init__(self, data_root: Path, profile_id: str = "default", api_fn: ApiFn | None = None):
        self.data_root = data_root
        self.profile_id = profile_id
        self.api_fn = api_fn
        self.running = False
        self._stop = asyncio.Event()
        self._base_url = ILINK_BASE
        self._cdn = CDN_BASE

    def _creds(self) -> tuple[str, str, str]:
        sec = _load_secrets(self.data_root)
        return (
            sec.get("account_id") or "",
            sec.get("token") or "",
            (sec.get("base_url") or ILINK_BASE).rstrip("/"),
        )

    async def _api(
        self,
        method: str,
        endpoint: str,
        payload: dict | None = None,
        *,
        token: str | None = None,
        base_url: str | None = None,
        timeout: float = 40.0,
    ) -> dict:
        if self.api_fn:
            return await self.api_fn(method, endpoint, payload, token)
        base = (base_url or self._base_url).rstrip("/")
        url = f"{base}/{endpoint}"
        if method.upper() == "GET":
            headers = {
                "iLink-App-Id": ILINK_APP_ID,
                "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
            }
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(url, headers=headers)
                r.raise_for_status()
                return r.json()
        body_obj = {**(payload or {}), "base_info": {"channel_version": CHANNEL_VERSION}}
        body = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":"))
        headers = _headers(token, body)
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(url, content=body.encode("utf-8"), headers=headers)
            if r.status_code >= 400:
                raise RuntimeError(f"iLink {endpoint} HTTP {r.status_code}: {r.text[:200]}")
            return r.json() if r.content else {}

    # ---------- QR login ----------
    async def qr_start(self, bot_type: str = "3") -> dict[str, Any]:
        try:
            data = await self._api("GET", f"{EP_GET_BOT_QR}?bot_type={bot_type}", timeout=35.0)
        except Exception as e:
            return {"ok": False, "error": f"获取二维码失败：{e}"}
        qrcode = str(data.get("qrcode") or "")
        qr_url = str(data.get("qrcode_img_content") or "")
        if not qrcode:
            return {"ok": False, "error": f"二维码响应异常：{data}"}
        return {
            "ok": True,
            "qrcode": qrcode,
            "qrcode_url": qr_url or qrcode,
            "scan_hint": "请用微信扫码，并在手机上确认登录",
        }

    async def qr_poll(self, qrcode: str, base_url: str | None = None) -> dict[str, Any]:
        """轮询扫码状态。confirmed 时自动落盘凭证。"""
        try:
            data = await self._api(
                "GET",
                f"{EP_GET_QR_STATUS}?qrcode={qrcode}",
                base_url=base_url or ILINK_BASE,
                timeout=35.0,
            )
        except Exception as e:
            return {"ok": False, "status": "error", "error": str(e)}
        st = str(data.get("status") or "wait")
        out: dict[str, Any] = {"ok": True, "status": st, "raw_keys": list(data.keys())}
        if st == "scaned_but_redirect" and data.get("redirect_host"):
            out["redirect_base"] = f"https://{data['redirect_host']}"
        if st == "confirmed":
            account_id = str(data.get("ilink_bot_id") or "")
            token = str(data.get("bot_token") or "")
            base = str(data.get("baseurl") or ILINK_BASE).rstrip("/")
            user_id = str(data.get("ilink_user_id") or "")
            if not account_id or not token:
                return {"ok": False, "status": "confirmed", "error": "凭证不完整"}
            _save_secrets(
                self.data_root,
                {
                    "account_id": account_id,
                    "token": token,
                    "base_url": base,
                    "user_id": user_id,
                },
            )
            cfg = _wx_cfg(self.data_root)
            cfg["account_id"] = account_id
            cfg.setdefault("allowed_users", [])
            if not cfg.get("pairing_code"):
                cfg["pairing_code"] = new_pairing_code()
            _save_wx_cfg(self.data_root, cfg)
            out.update(
                {
                    "account_id": account_id,
                    "pairing_code": cfg["pairing_code"],
                    "configured": True,
                }
            )
        return out

    # ---------- send ----------
    async def send_text(self, to_user: str, text: str, context_token: str | None = None) -> bool:
        account_id, token, base = self._creds()
        if not token:
            return False
        ctx = context_token or _load_ctx(self.data_root).get(to_user)
        msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to_user,
            "client_id": f"nx-{uuid.uuid4().hex}",
            "message_type": MSG_TYPE_BOT,
            "message_state": MSG_STATE_FINISH,
            "item_list": [{"type": ITEM_TEXT, "text_item": {"text": (text or "")[:4000]}}],
        }
        if ctx:
            msg["context_token"] = ctx
        try:
            resp = await self._api(
                "POST", EP_SEND_MESSAGE, {"msg": msg}, token=token, base_url=base
            )
            ret, err = resp.get("ret"), resp.get("errcode")
            if (ret not in (0, None)) or (err not in (0, None)):
                # session expired → retry without token once
                if err == -14 or ret == -14:
                    msg.pop("context_token", None)
                    resp = await self._api(
                        "POST", EP_SEND_MESSAGE, {"msg": msg}, token=token, base_url=base
                    )
                    ret, err = resp.get("ret"), resp.get("errcode")
                if (ret not in (0, None)) or (err not in (0, None)):
                    logger.warning("weixin send text fail: %s", resp)
                    return False
            return True
        except Exception as e:
            logger.warning("weixin send text error: %s", e)
            return False

    async def send_media(self, to_user: str, path: Path, caption: str = "") -> bool:
        account_id, token, base = self._creds()
        if not token or not path.is_file():
            return False
        try:
            plain = path.read_bytes()
            is_img = path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
            media_type = MEDIA_IMAGE if is_img else MEDIA_FILE
            filekey = secrets.token_hex(16)
            aes_key = secrets.token_bytes(16)
            rawsize = len(plain)
            md5 = hashlib.md5(plain).hexdigest()
            filesize = ((rawsize + 1 + 15) // 16) * 16
            up = await self._api(
                "POST",
                EP_GET_UPLOAD_URL,
                {
                    "filekey": filekey,
                    "media_type": media_type,
                    "to_user_id": to_user,
                    "rawsize": rawsize,
                    "rawfilemd5": md5,
                    "filesize": filesize,
                    "aeskey": aes_key.hex(),
                },
                token=token,
                base_url=base,
                timeout=60.0,
            )
            upload_param = str(up.get("upload_param") or "")
            upload_full = str(up.get("upload_full_url") or "")
            if upload_full:
                upload_url = upload_full
            elif upload_param:
                upload_url = (
                    f"{self._cdn.rstrip('/')}/upload"
                    f"?encrypted_query_param={quote(upload_param, safe='')}"
                    f"&filekey={quote(filekey, safe='')}"
                )
            else:
                logger.warning("weixin getuploadurl empty: %s", up)
                return False
            cipher = _aes_enc(plain, aes_key)
            async with httpx.AsyncClient(timeout=120.0) as c:
                r = await c.post(upload_url, content=cipher)
                r.raise_for_status()
                # response may be plain text query param
                enc_q = r.text.strip().strip('"')
                try:
                    j = r.json()
                    enc_q = j.get("encrypted_query_param") or j.get("encrypt_query_param") or enc_q
                except Exception:
                    pass
            if not enc_q:
                logger.warning("weixin upload no query param")
                return False
            aes_for_api = base64.b64encode(aes_key.hex().encode("ascii")).decode("ascii")
            if is_img:
                item = {
                    "type": ITEM_IMAGE,
                    "image_item": {
                        "media": {
                            "encrypt_query_param": enc_q,
                            "aes_key": aes_for_api,
                            "encrypt_type": 1,
                        }
                    },
                }
            else:
                item = {
                    "type": ITEM_FILE,
                    "file_item": {
                        "media": {
                            "encrypt_query_param": enc_q,
                            "aes_key": aes_for_api,
                            "encrypt_type": 1,
                        },
                        "file_name": path.name,
                    },
                }
            if caption:
                await self.send_text(to_user, caption)
            ctx = _load_ctx(self.data_root).get(to_user)
            msg: dict[str, Any] = {
                "from_user_id": "",
                "to_user_id": to_user,
                "client_id": f"nx-{uuid.uuid4().hex}",
                "message_type": MSG_TYPE_BOT,
                "message_state": MSG_STATE_FINISH,
                "item_list": [item],
            }
            if ctx:
                msg["context_token"] = ctx
            await self._api("POST", EP_SEND_MESSAGE, {"msg": msg}, token=token, base_url=base)
            return True
        except Exception as e:
            logger.warning("weixin send media error: %s", e)
            return False

    async def _download_media_item(self, item: dict) -> Attachment | None:
        try:
            t = item.get("type")
            key = {
                ITEM_IMAGE: "image_item",
                3: "voice_item",
                ITEM_FILE: "file_item",
                5: "video_item",
            }.get(t)
            if not key:
                return None
            blob = item.get(key) or {}
            media = blob.get("media") or {}
            eq = media.get("encrypt_query_param") or media.get("encrypted_query_param")
            full = media.get("full_url") or media.get("url")
            aes_b64 = media.get("aes_key")
            raw: bytes
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as c:
                if eq:
                    url = f"{self._cdn.rstrip('/')}/download?encrypted_query_param={quote(str(eq), safe='')}"
                    r = await c.get(url)
                    r.raise_for_status()
                    raw = r.content
                elif full:
                    r = await c.get(str(full))
                    r.raise_for_status()
                    raw = r.content
                else:
                    return None
            if aes_b64:
                try:
                    raw = _aes_dec(raw, _parse_aes_key(str(aes_b64)))
                except Exception as e:
                    logger.warning("weixin media decrypt fail: %s", e)
            name = blob.get("file_name") or ("image.jpg" if t == ITEM_IMAGE else "file.bin")
            kind = "image" if t == ITEM_IMAGE else "file"
            return save_inbound_bytes(self.data_root, raw, filename=name, kind_hint=kind)
        except Exception as e:
            logger.warning("weixin media in fail: %s", e)
            return None

    async def handle_inbound_message(self, message: dict) -> dict[str, Any]:
        """处理一条 iLink 消息（可单测注入）。"""
        s = load_app_settings(self.data_root)
        if not (s.channels or {}).get("master_enabled"):
            return {"handled": False, "reason": "master off"}
        cfg = _wx_cfg(self.data_root)
        if not cfg.get("enabled"):
            return {"handled": False, "reason": "weixin off"}

        account_id, token, base = self._creds()
        sender = str(message.get("from_user_id") or "").strip()
        if not sender or sender == account_id:
            return {"handled": False}

        ctx = str(message.get("context_token") or "").strip()
        if ctx:
            m = _load_ctx(self.data_root)
            m[sender] = ctx
            _save_ctx(self.data_root, m)

        items = message.get("item_list") or []
        text = _extract_text(items)
        atts: list[Attachment] = []
        for it in items:
            if isinstance(it, dict) and it.get("type") != ITEM_TEXT:
                a = await self._download_media_item(it)
                if a:
                    atts.append(a)

        allowed = list(cfg.get("allowed_users") or [])
        if sender not in allowed:
            code = cfg.get("pairing_code")
            if code and text and code in text.upper():
                allowed.append(sender)
                cfg["allowed_users"] = allowed
                _save_wx_cfg(self.data_root, cfg)
                await self.send_text(sender, "绑定好啦，以后在这里说话他都会记得。", ctx)
                return {"handled": True, "paired": True}
            await self.send_text(sender, "还没配对。在念匣设置里拿配对码发给我。", ctx)
            return {"handled": True, "paired": False}

        if not text and not atts:
            return {"handled": False}

        from ..memory import ProfileStore
        from . import bound_profile_id

        pid = bound_profile_id(self.data_root, "weixin", self.profile_id)
        store = ProfileStore(self.data_root, pid)
        sid = store.resolve_chat_session_id()
        req = ChatRequest(
            profile_id=pid,
            session_id=sid,
            message=text or ("（发来了附件）" if atts else ""),
            tier="L1",
            attachments=atts,
        )
        out = await run_chat_collect_async(store, req, enable_tools=True)
        reply = out["reply"]
        cleaned, paths = extract_outbound_media(reply, self.data_root)
        paths = paths + collect_tool_images(out.get("image_paths") or [], self.data_root)
        if cleaned:
            await self.send_text(sender, cleaned, ctx)
        for p in paths[:5]:
            await self.send_media(sender, p)
        return {"handled": True, "reply": cleaned or reply, "media": len(paths)}

    async def _poll_loop(self) -> None:
        account_id, token, base = self._creds()
        if not token:
            logger.warning("weixin: no token, poll not started")
            return
        self._base_url = base
        sync_buf = ""
        sp = _sync_path(self.data_root)
        if sp.exists():
            try:
                sync_buf = json.loads(sp.read_text(encoding="utf-8")).get("get_updates_buf") or ""
            except Exception:
                pass
        self.running = False
        backoff = 2
        try:
            while not self._stop.is_set():
                s = load_app_settings(self.data_root)
                cfg = _wx_cfg(self.data_root)
                if not (s.channels or {}).get("master_enabled") or not cfg.get("enabled"):
                    self.running = False
                    await asyncio.sleep(3)
                    continue
                try:
                    # refresh creds
                    account_id, token, base = self._creds()
                    self._base_url = base
                    if not token:
                        await asyncio.sleep(5)
                        continue
                    resp = await self._api(
                        "POST",
                        EP_GET_UPDATES,
                        {"get_updates_buf": sync_buf},
                        token=token,
                        base_url=base,
                        timeout=40.0,
                    )
                    self.running = True
                    ret, err = resp.get("ret"), resp.get("errcode")
                    if (ret not in (0, None)) or (err not in (0, None)):
                        if err == -14 or ret == -14:
                            logger.error("weixin session expired; sleep 10min")
                            self.running = False
                            await asyncio.sleep(600)
                            continue
                        logger.warning("weixin getupdates fail: %s", resp)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 60)
                        continue
                    backoff = 2
                    nb = str(resp.get("get_updates_buf") or "")
                    if nb:
                        sync_buf = nb
                        sp.write_text(
                            json.dumps({"get_updates_buf": sync_buf}), encoding="utf-8"
                        )
                    for msg in resp.get("msgs") or []:
                        if isinstance(msg, dict):
                            asyncio.create_task(self._safe_msg(msg))
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.running = False
                    logger.warning("weixin poll error: %s", e)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
        finally:
            self.running = False

    async def _safe_msg(self, msg: dict) -> None:
        try:
            await self.handle_inbound_message(msg)
        except Exception as e:
            logger.warning("weixin handle msg error: %s", e)

    def stop(self) -> None:
        self._stop.set()


_adapter: WeixinAdapter | None = None
_task: asyncio.Task | None = None


def get_adapter(data_root: Path) -> WeixinAdapter:
    global _adapter
    if _adapter is None or _adapter.data_root != data_root:
        _adapter = WeixinAdapter(data_root)
    return _adapter


async def start_weixin_task(data_root: Path) -> None:
    global _task
    ad = get_adapter(data_root)
    if _task is None or _task.done():
        ad._stop = asyncio.Event()
        _task = asyncio.create_task(ad._poll_loop())


async def stop_weixin_task() -> None:
    global _task
    if _adapter:
        _adapter.stop()
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
