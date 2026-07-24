"""Telegram 通道适配器（Bot API 长轮询）· 文本 + 图片 + 文件。

对标 Hermes：入站 photo/document 落盘；出站 sendPhoto/sendDocument。
"""

from __future__ import annotations

import asyncio
import logging
import secrets as pysecrets
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

logger = logging.getLogger(__name__)

BOT_API = "https://api.telegram.org"

ApiCall = Callable[[str, str, dict], Awaitable[dict]]


async def _http_api_call(token: str, method: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=40.0) as c:
        # file uploads use multipart
        if method in ("sendPhoto", "sendDocument") and isinstance(
            payload.get("photo") or payload.get("document"), (bytes, tuple)
        ):
            data = {k: v for k, v in payload.items() if k not in ("photo", "document")}
            files = {}
            if "photo" in payload:
                files["photo"] = ("image.png", payload["photo"], "image/png")
            if "document" in payload:
                name = payload.get("_filename") or "file.bin"
                files["document"] = (name, payload["document"], "application/octet-stream")
                data.pop("_filename", None)
            r = await c.post(f"{BOT_API}/bot{token}/{method}", data=data, files=files)
        else:
            r = await c.post(f"{BOT_API}/bot{token}/{method}", json=payload)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram {method} not ok: {data}")
        return data.get("result", {})


def _key_path(data_root: Path) -> Path:
    p = data_root / "secrets" / "channels"
    p.mkdir(parents=True, exist_ok=True)
    return p / "telegram.key"


def load_token(data_root: Path) -> str | None:
    p = _key_path(data_root)
    if p.exists():
        t = p.read_text(encoding="utf-8").strip()
        return t or None
    return None


def save_token(data_root: Path, token: str) -> None:
    _key_path(data_root).write_text(token.strip(), encoding="utf-8")


def _tg_cfg(data_root: Path) -> dict[str, Any]:
    s = load_app_settings(data_root)
    return (s.channels or {}).get("telegram") or {}


def _save_tg_cfg(data_root: Path, cfg: dict[str, Any]) -> None:
    s = load_app_settings(data_root)
    channels = dict(s.channels or {})
    channels["telegram"] = cfg
    s.channels = channels
    save_app_settings(data_root, s)


def new_pairing_code() -> str:
    return pysecrets.token_hex(3).upper()


class TelegramAdapter:
    def __init__(
        self,
        data_root: Path,
        profile_id: str = "default",
        api_call: ApiCall | None = None,
    ):
        self.data_root = data_root
        self.profile_id = profile_id
        self.api_call = api_call or _http_api_call
        self._offset = 0
        self._stop = asyncio.Event()
        self.running = False

    def status(self) -> dict[str, Any]:
        cfg = _tg_cfg(self.data_root)
        return {
            "enabled": bool(cfg.get("enabled")),
            "paired_chats": len(cfg.get("allowed_chat_ids") or []),
            "pairing_code": cfg.get("pairing_code"),
            "running": self.running,
            "has_token": bool(load_token(self.data_root)),
        }

    async def setup(self, token: str) -> dict[str, Any]:
        me = await self.api_call(token.strip(), "getMe", {})
        save_token(self.data_root, token.strip())
        cfg = _tg_cfg(self.data_root)
        cfg.setdefault("allowed_chat_ids", [])
        cfg["pairing_code"] = new_pairing_code()
        cfg["bot_username"] = me.get("username", "")
        _save_tg_cfg(self.data_root, cfg)
        return {"ok": True, "bot": me.get("username"), "pairing_code": cfg["pairing_code"]}

    async def _reply_text(self, token: str, chat_id: int, text: str) -> None:
        try:
            await self.api_call(token, "sendMessage", {"chat_id": chat_id, "text": text[:4000]})
        except Exception as e:
            logger.warning("telegram sendMessage failed: %s", e)

    async def _reply_media(self, token: str, chat_id: int, paths: list[Path], caption: str = "") -> None:
        for i, p in enumerate(paths[:5]):
            try:
                data = p.read_bytes()
                cap = caption if i == 0 else ""
                if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                    await self.api_call(
                        token,
                        "sendPhoto",
                        {"chat_id": chat_id, "photo": data, "caption": cap[:1024]},
                    )
                else:
                    await self.api_call(
                        token,
                        "sendDocument",
                        {
                            "chat_id": chat_id,
                            "document": data,
                            "_filename": p.name,
                            "caption": cap[:1024],
                        },
                    )
            except Exception as e:
                logger.warning("telegram send media failed: %s", e)
                await self._reply_text(token, chat_id, f"（文件 {p.name} 发送失败：{e}）")

    async def _download_file(self, token: str, file_id: str) -> bytes | None:
        try:
            meta = await self.api_call(token, "getFile", {"file_id": file_id})
            fpath = meta.get("file_path")
            if not fpath:
                return None
            url = f"{BOT_API}/file/bot{token}/{fpath}"
            async with httpx.AsyncClient(timeout=60.0) as c:
                r = await c.get(url)
                r.raise_for_status()
                return r.content
        except Exception as e:
            logger.warning("telegram download failed: %s", e)
            return None

    async def _extract_inbound(self, token: str, msg: dict) -> tuple[str, list[Attachment]]:
        text = (msg.get("text") or msg.get("caption") or "").strip()
        atts: list[Attachment] = []
        if msg.get("photo"):
            # largest size last
            photo = msg["photo"][-1]
            raw = await self._download_file(token, photo["file_id"])
            if raw:
                a = save_inbound_bytes(
                    self.data_root, raw, filename="photo.jpg", kind_hint="image"
                )
                if a:
                    atts.append(a)
        if msg.get("document"):
            doc = msg["document"]
            raw = await self._download_file(token, doc["file_id"])
            if raw:
                a = save_inbound_bytes(
                    self.data_root,
                    raw,
                    filename=doc.get("file_name") or "document.bin",
                    kind_hint="image" if (doc.get("mime_type") or "").startswith("image/") else "file",
                )
                if a:
                    atts.append(a)
        return text, atts

    async def _handle_message(self, token: str, msg: dict) -> None:
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return
        text, atts = await self._extract_inbound(token, msg)
        if not text and not atts:
            return

        cfg = _tg_cfg(self.data_root)
        allowed = cfg.get("allowed_chat_ids") or []

        if chat_id not in allowed:
            code = cfg.get("pairing_code")
            if code and text and code in text.upper():
                allowed.append(chat_id)
                cfg["allowed_chat_ids"] = allowed
                _save_tg_cfg(self.data_root, cfg)
                await self._reply_text(token, chat_id, "绑定好啦，以后在这里说话他都会记得。")
            else:
                await self._reply_text(
                    token, chat_id, "还没配对。在念匣设置里拿配对码发给我（形如 A1B2C3）。"
                )
            return

        from ..memory import ProfileStore
        from . import bound_profile_id

        pid = bound_profile_id(self.data_root, "telegram", self.profile_id)
        store = ProfileStore(self.data_root, pid)
        # 通道会话跟桌面角色会话：用当前 active card 专属 session
        sid = store.resolve_chat_session_id()
        req = ChatRequest(
            profile_id=pid,
            session_id=sid,
            message=text or ("（发来了附件）" if atts else ""),
            tier="L1",
            attachments=atts,
        )
        # 通道开工具，才能画画并把图发回去
        out = await run_chat_collect_async(store, req, enable_tools=True)
        reply = out["reply"]
        cleaned, paths = extract_outbound_media(reply, self.data_root)
        paths = paths + collect_tool_images(out.get("image_paths") or [], self.data_root)
        if cleaned:
            await self._reply_text(token, chat_id, cleaned)
        if paths:
            await self._reply_media(token, chat_id, paths)

    async def poll_loop(self) -> None:
        token = load_token(self.data_root)
        if not token:
            logger.warning("telegram: no token, loop not started")
            return
        self.running = True
        backoff = 1
        logger.info("telegram poll loop started")
        try:
            while not self._stop.is_set():
                settings = load_app_settings(self.data_root)
                cfg = (settings.channels or {}).get("telegram") or {}
                if not settings.channels.get("master_enabled") or not cfg.get("enabled"):
                    await asyncio.sleep(3)
                    continue
                try:
                    updates = await self.api_call(
                        token, "getUpdates", {"offset": self._offset, "timeout": 25}
                    )
                    backoff = 1
                    for u in updates if isinstance(updates, list) else []:
                        self._offset = max(self._offset, u.get("update_id", 0) + 1)
                        if msg := u.get("message"):
                            await self._handle_message(token, msg)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("telegram poll error: %s (backoff %ss)", e, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
        finally:
            self.running = False

    def stop(self) -> None:
        self._stop.set()


_adapter: TelegramAdapter | None = None
_task: asyncio.Task | None = None


def get_adapter(data_root: Path) -> TelegramAdapter:
    global _adapter
    if _adapter is None:
        _adapter = TelegramAdapter(data_root)
    return _adapter


async def start_channel_tasks(data_root: Path) -> None:
    """应用启动时拉起 TG 长轮询 + QQ WS + 微信 iLink 长轮询（幂等）。"""
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(get_adapter(data_root).poll_loop())
    try:
        from .qqbot import start_qqbot_task

        await start_qqbot_task(data_root)
    except Exception as e:
        logger.warning("qqbot start failed: %s", e)
    try:
        from .weixin import start_weixin_task

        await start_weixin_task(data_root)
    except Exception as e:
        logger.warning("weixin start failed: %s", e)


async def stop_channel_tasks() -> None:
    global _task
    if _adapter:
        _adapter.stop()
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    try:
        from .qqbot import stop_qqbot_task

        await stop_qqbot_task()
    except Exception:
        pass
    try:
        from .weixin import stop_weixin_task

        await stop_weixin_task()
    except Exception:
        pass
