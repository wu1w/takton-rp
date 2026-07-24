"""QQ 官方机器人通道（AppID + AppSecret · WebSocket 网关）。

对标 Hermes qqbot：
- Token: POST https://bots.qq.com/app/getAppAccessToken {appId, clientSecret}
- 入站: Gateway WS（C2C / 群@）
- 出站: REST api.sgroup.qq.com 发文本/图片/文件
- Secret 存 secrets/channels/qqbot.key，不回显
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

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

TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
API_BASE = "https://api.sgroup.qq.com"

MSG_TYPE_TEXT = 0
MSG_TYPE_MEDIA = 7
MEDIA_TYPE_IMAGE = 1
MEDIA_TYPE_FILE = 4

# intents: C2C + GROUP_AT + PUBLIC_GUILD + DIRECT + INTERACTION
INTENTS = (1 << 25) | (1 << 30) | (1 << 12) | (1 << 26)

# 可注入的测试桩
TokenFn = Callable[[str, str], Awaitable[dict]]
ApiFn = Callable[[str, str, str, dict | None], Awaitable[dict]]  # method, path, token, body


def _key_path(data_root: Path) -> Path:
    p = data_root / "secrets" / "channels"
    p.mkdir(parents=True, exist_ok=True)
    return p / "qqbot.key"


def _qq_cfg(data_root: Path) -> dict[str, Any]:
    s = load_app_settings(data_root)
    return (s.channels or {}).get("qqbot") or (s.channels or {}).get("onebot") or {}


def _save_qq_cfg(data_root: Path, cfg: dict[str, Any]) -> None:
    s = load_app_settings(data_root)
    channels = dict(s.channels or {})
    channels["qqbot"] = cfg
    # 清理旧 onebot 展示字段，避免设置页混淆
    s.channels = channels
    save_app_settings(data_root, s)


def _load_secrets(data_root: Path) -> dict[str, str]:
    p = _key_path(data_root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def setup(data_root: Path, app_id: str, app_secret: str) -> dict[str, Any]:
    """保存 AppID（可回显）+ AppSecret（secrets）+ 配对码。"""
    app_id = (app_id or "").strip()
    app_secret = (app_secret or "").strip()
    if not app_id or not app_secret:
        return {"ok": False, "error": "需要 AppID 和 AppSecret"}
    cfg = _qq_cfg(data_root)
    cfg["app_id"] = app_id
    cfg.setdefault("allowed_users", [])
    cfg["pairing_code"] = new_pairing_code()
    # 去掉旧 OneBot 字段
    cfg.pop("http_api", None)
    cfg.pop("access_token", None)
    _save_qq_cfg(data_root, cfg)
    _key_path(data_root).write_text(
        json.dumps({"app_id": app_id, "client_secret": app_secret}, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"ok": True, "pairing_code": cfg["pairing_code"], "app_id": app_id}


def status(data_root: Path) -> dict[str, Any]:
    cfg = _qq_cfg(data_root)
    sec = _load_secrets(data_root)
    ad = get_adapter(data_root)
    return {
        "enabled": bool(cfg.get("enabled")),
        "configured": bool(cfg.get("app_id") and sec.get("client_secret")),
        "app_id": cfg.get("app_id") or "",
        "paired_users": len(cfg.get("allowed_users") or []),
        "pairing_code": cfg.get("pairing_code"),
        "running": bool(ad.running),
    }


class QQBotAdapter:
    def __init__(
        self,
        data_root: Path,
        profile_id: str = "default",
        token_fn: TokenFn | None = None,
        api_fn: ApiFn | None = None,
    ):
        self.data_root = data_root
        self.profile_id = profile_id
        self.token_fn = token_fn
        self.api_fn = api_fn
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._stop = asyncio.Event()
        self.running = False
        self._last_seq: int | None = None
        self._session_id: str | None = None
        self._heartbeat_interval = 30.0
        self._chat_type: dict[str, str] = {}  # openid -> c2c|group
        self._ws = None

    async def _ensure_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token
        sec = _load_secrets(self.data_root)
        app_id = sec.get("app_id") or _qq_cfg(self.data_root).get("app_id") or ""
        secret = sec.get("client_secret") or ""
        if not app_id or not secret:
            raise RuntimeError("未配置 AppID / AppSecret")
        if self.token_fn:
            data = await self.token_fn(app_id, secret)
        else:
            async with httpx.AsyncClient(timeout=20.0) as c:
                r = await c.post(
                    TOKEN_URL,
                    json={"appId": app_id, "clientSecret": secret},
                )
                r.raise_for_status()
                data = r.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"取 token 失败：{data}")
        self._access_token = token
        self._token_expires_at = time.time() + int(data.get("expires_in", 7200))
        return token

    async def _api(
        self, method: str, path: str, body: dict | None = None, *, timeout: float = 30.0
    ) -> dict:
        token = await self._ensure_token()
        if self.api_fn:
            return await self.api_fn(method, path, token, body)
        headers = {
            "Authorization": f"QQBot {token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.request(method, f"{API_BASE}{path}", headers=headers, json=body)
            if r.status_code >= 400:
                raise RuntimeError(f"QQ API {method} {path} → {r.status_code}: {r.text[:300]}")
            if not r.content:
                return {}
            return r.json()

    async def setup_validate(self, app_id: str, app_secret: str) -> dict[str, Any]:
        """先验证 token 再落盘。"""
        try:
            if self.token_fn:
                data = await self.token_fn(app_id.strip(), app_secret.strip())
            else:
                async with httpx.AsyncClient(timeout=20.0) as c:
                    r = await c.post(
                        TOKEN_URL,
                        json={"appId": app_id.strip(), "clientSecret": app_secret.strip()},
                    )
                    data = r.json()
            if not data.get("access_token"):
                return {"ok": False, "error": f"AppID/Secret 无效：{data}"}
        except Exception as e:
            return {"ok": False, "error": f"校验失败：{e}"}
        return setup(self.data_root, app_id, app_secret)

    async def send_text(self, chat_id: str, text: str, *, chat_type: str = "c2c") -> bool:
        body = {"content": (text or "")[:4000], "msg_type": MSG_TYPE_TEXT}
        try:
            if chat_type == "group":
                await self._api("POST", f"/v2/groups/{chat_id}/messages", body)
            else:
                await self._api("POST", f"/v2/users/{chat_id}/messages", body)
            return True
        except Exception as e:
            logger.warning("qqbot send text failed: %s", e)
            return False

    async def send_media(
        self, chat_id: str, path: Path, *, chat_type: str = "c2c", caption: str = ""
    ) -> bool:
        try:
            raw = path.read_bytes()
            b64 = base64.b64encode(raw).decode()
            is_img = path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
            file_type = MEDIA_TYPE_IMAGE if is_img else MEDIA_TYPE_FILE
            files_path = (
                f"/v2/users/{chat_id}/files"
                if chat_type != "group"
                else f"/v2/groups/{chat_id}/files"
            )
            upload_body: dict[str, Any] = {
                "file_type": file_type,
                "file_data": b64,
                "srv_send_msg": False,
            }
            if not is_img:
                upload_body["file_name"] = path.name
            upload = await self._api("POST", files_path, upload_body, timeout=120.0)
            file_info = upload.get("file_info") or (upload.get("data") or {}).get("file_info")
            if not file_info:
                logger.warning("qqbot upload no file_info: %s", str(upload)[:200])
                return False
            msg_body: dict[str, Any] = {
                "msg_type": MSG_TYPE_MEDIA,
                "media": {"file_info": file_info},
            }
            if caption:
                msg_body["content"] = caption[:1000]
            msg_path = (
                f"/v2/users/{chat_id}/messages"
                if chat_type != "group"
                else f"/v2/groups/{chat_id}/messages"
            )
            await self._api("POST", msg_path, msg_body, timeout=60.0)
            return True
        except Exception as e:
            logger.warning("qqbot send media failed: %s", e)
            return False

    async def _process_attachments(self, attachments: Any) -> list[Attachment]:
        atts: list[Attachment] = []
        if not isinstance(attachments, list):
            return atts
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as c:
            for item in attachments:
                if not isinstance(item, dict):
                    continue
                url = item.get("url") or ""
                ct = (item.get("content_type") or "").lower()
                name = item.get("filename") or item.get("name") or "file.bin"
                if not url:
                    continue
                try:
                    r = await c.get(url)
                    r.raise_for_status()
                    kind = "image" if ct.startswith("image/") or name.lower().endswith(
                        (".png", ".jpg", ".jpeg", ".webp", ".gif")
                    ) else "file"
                    a = save_inbound_bytes(
                        self.data_root, r.content, filename=name, kind_hint=kind
                    )
                    if a:
                        atts.append(a)
                except Exception as e:
                    logger.warning("qqbot download attachment failed: %s", e)
        return atts

    async def handle_inbound(
        self,
        *,
        chat_id: str,
        user_id: str,
        text: str,
        chat_type: str = "c2c",
        attachments: list[Attachment] | None = None,
    ) -> dict[str, Any]:
        """配对 + 聊天管线（可供单测直接调用，不经 WS）。"""
        s = load_app_settings(self.data_root)
        if not (s.channels or {}).get("master_enabled"):
            return {"handled": False, "reason": "master off"}
        cfg = _qq_cfg(self.data_root)
        if not cfg.get("enabled"):
            return {"handled": False, "reason": "qqbot off"}

        text = (text or "").strip()
        atts = attachments or []
        self._chat_type[chat_id] = chat_type

        allowed = list(cfg.get("allowed_users") or [])
        if user_id not in allowed:
            code = cfg.get("pairing_code")
            if code and text and code in text.upper():
                allowed.append(user_id)
                cfg["allowed_users"] = allowed
                _save_qq_cfg(self.data_root, cfg)
                await self.send_text(chat_id, "绑定好啦，以后在这里说话他都会记得。", chat_type=chat_type)
                return {"handled": True, "paired": True}
            await self.send_text(
                chat_id, "还没配对。在念匣设置里拿配对码发给我。", chat_type=chat_type
            )
            return {"handled": True, "paired": False}

        if not text and not atts:
            return {"handled": False}

        from ..memory import ProfileStore
        from . import bound_profile_id

        pid = bound_profile_id(self.data_root, "qqbot", self.profile_id)
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
            await self.send_text(chat_id, cleaned, chat_type=chat_type)
        for i, p in enumerate(paths[:5]):
            cap = cleaned if i == 0 and not cleaned else ""
            await self.send_media(chat_id, p, chat_type=chat_type, caption=cap)
        return {"handled": True, "reply": cleaned or reply, "media": len(paths)}

    async def _on_dispatch_message(self, event_type: str, d: dict) -> None:
        if not isinstance(d, dict):
            return
        author = d.get("author") or {}
        content = (d.get("content") or "").strip()
        # 去掉群 @ 前缀
        if content.startswith("/"):
            pass
        # simple strip <@!id>
        import re

        content = re.sub(r"<@!?\d+>", "", content).strip()

        atts = await self._process_attachments(d.get("attachments"))

        if event_type == "C2C_MESSAGE_CREATE":
            user_openid = str(author.get("user_openid") or author.get("id") or "")
            if not user_openid:
                return
            await self.handle_inbound(
                chat_id=user_openid,
                user_id=user_openid,
                text=content,
                chat_type="c2c",
                attachments=atts,
            )
        elif event_type == "GROUP_AT_MESSAGE_CREATE":
            group_openid = str(d.get("group_openid") or "")
            member = str(author.get("member_openid") or author.get("id") or "")
            if not group_openid:
                return
            await self.handle_inbound(
                chat_id=group_openid,
                user_id=member or group_openid,
                text=content,
                chat_type="group",
                attachments=atts,
            )

    async def _ws_loop(self) -> None:
        """官方 Gateway 长连接。"""
        try:
            import websockets
            from websockets.exceptions import ConnectionClosed
        except ImportError:
            logger.error("qqbot: 需要 websockets 包（uvicorn[standard] 通常已带）")
            return

        self.running = False
        backoff = 2
        try:
            while not self._stop.is_set():
                s = load_app_settings(self.data_root)
                cfg = _qq_cfg(self.data_root)
                if not (s.channels or {}).get("master_enabled") or not cfg.get("enabled"):
                    self.running = False
                    await asyncio.sleep(3)
                    continue
                try:
                    token = await self._ensure_token()
                    gw = await self._api("GET", "/gateway")
                    url = gw.get("url")
                    if not url:
                        raise RuntimeError(f"gateway 无 url: {gw}")
                    async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
                        self._ws = ws
                        self.running = True
                        backoff = 2
                        hb_task = asyncio.create_task(self._heartbeat(ws))
                        try:
                            async for raw in ws:
                                if self._stop.is_set():
                                    break
                                try:
                                    payload = json.loads(raw)
                                except Exception:
                                    continue
                                await self._handle_payload(ws, payload, token)
                        finally:
                            self.running = False
                            hb_task.cancel()
                            try:
                                await hb_task
                            except asyncio.CancelledError:
                                pass
                            self._ws = None
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.running = False
                    logger.warning("qqbot ws error: %s (backoff %ss)", e, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
        finally:
            self.running = False

    async def _heartbeat(self, ws) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(self._heartbeat_interval)
            try:
                await ws.send(json.dumps({"op": 1, "d": self._last_seq}))
            except Exception:
                return

    async def _handle_payload(self, ws, payload: dict, token: str) -> None:
        op = payload.get("op")
        t = payload.get("t")
        s = payload.get("s")
        d = payload.get("d")
        if isinstance(s, int):
            if self._last_seq is None or s > self._last_seq:
                self._last_seq = s

        if op == 10:  # Hello
            interval_ms = (d or {}).get("heartbeat_interval", 30000) if isinstance(d, dict) else 30000
            self._heartbeat_interval = max(5.0, interval_ms / 1000.0 * 0.8)
            if self._session_id and self._last_seq is not None:
                await ws.send(
                    json.dumps(
                        {
                            "op": 6,
                            "d": {
                                "token": f"QQBot {token}",
                                "session_id": self._session_id,
                                "seq": self._last_seq,
                            },
                        }
                    )
                )
            else:
                await ws.send(
                    json.dumps(
                        {
                            "op": 2,
                            "d": {
                                "token": f"QQBot {token}",
                                "intents": INTENTS,
                                "shard": [0, 1],
                                "properties": {
                                    "$os": "windows",
                                    "$browser": "nianxia",
                                    "$device": "nianxia",
                                },
                            },
                        }
                    )
                )
            return

        if op == 0 and t:
            if t == "READY" and isinstance(d, dict):
                self._session_id = d.get("session_id")
                logger.info("qqbot READY session=%s", self._session_id)
            elif t in {
                "C2C_MESSAGE_CREATE",
                "GROUP_AT_MESSAGE_CREATE",
                "DIRECT_MESSAGE_CREATE",
            }:
                asyncio.create_task(self._on_dispatch_message(t, d if isinstance(d, dict) else {}))
            return

        if op == 7:  # reconnect
            await ws.close()
            return
        if op == 9:  # invalid session
            if not d:
                self._session_id = None
                self._last_seq = None
            await ws.close()

    def stop(self) -> None:
        self._stop.set()


_adapter: QQBotAdapter | None = None
_task: asyncio.Task | None = None


def get_adapter(data_root: Path) -> QQBotAdapter:
    global _adapter
    if _adapter is None or _adapter.data_root != data_root:
        _adapter = QQBotAdapter(data_root)
    return _adapter


async def start_qqbot_task(data_root: Path) -> None:
    global _task
    ad = get_adapter(data_root)
    if _task is None or _task.done():
        ad._stop = asyncio.Event()
        _task = asyncio.create_task(ad._ws_loop())


async def stop_qqbot_task() -> None:
    global _task
    if _adapter:
        _adapter.stop()
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
