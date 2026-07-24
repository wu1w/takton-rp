"""QQ OneBot 通道（OneBot 11 HTTP 上报 + HTTP API 发送）· 文本 + 图片 + 文件。"""

from __future__ import annotations

import base64
import logging
import re
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
from . import display_name
from .telegram import new_pairing_code

logger = logging.getLogger(__name__)

SendFn = Callable[[str, dict], Awaitable[dict]]


async def _http_send(http_api: str, payload: dict, token: str = "") -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{http_api.rstrip('/')}/send_msg", json=payload, headers=headers)
        r.raise_for_status()
        return r.json()


def _ob_cfg(data_root: Path) -> dict[str, Any]:
    s = load_app_settings(data_root)
    return (s.channels or {}).get("onebot") or {}


def _save_ob_cfg(data_root: Path, cfg: dict[str, Any]) -> None:
    s = load_app_settings(data_root)
    channels = dict(s.channels or {})
    channels["onebot"] = cfg
    s.channels = channels
    save_app_settings(data_root, s)


def setup(data_root: Path, http_api: str, access_token: str = "") -> dict[str, Any]:
    cfg = _ob_cfg(data_root)
    cfg["http_api"] = http_api.rstrip("/")
    cfg["access_token"] = access_token
    cfg.setdefault("allowed_users", [])
    cfg["pairing_code"] = new_pairing_code()
    _save_ob_cfg(data_root, cfg)
    return {"ok": True, "pairing_code": cfg["pairing_code"]}


def status(data_root: Path) -> dict[str, Any]:
    cfg = _ob_cfg(data_root)
    return {
        "enabled": bool(cfg.get("enabled")),
        "configured": bool(cfg.get("http_api")),
        "paired_users": len(cfg.get("allowed_users") or []),
        "pairing_code": cfg.get("pairing_code"),
        "http_api": cfg.get("http_api") or "",
    }


def _parse_message_segments(message: Any) -> tuple[str, list[dict[str, Any]]]:
    """解析 OneBot message 字段 → (纯文本, 媒体段列表)。"""
    texts: list[str] = []
    media: list[dict[str, Any]] = []
    if isinstance(message, str):
        # CQ 码
        for m in re.finditer(r"\[CQ:image,([^\]]+)\]", message):
            params = dict(re.findall(r"(\w+)=([^,\]]+)", m.group(1)))
            media.append({"type": "image", "data": params})
        for m in re.finditer(r"\[CQ:file,([^\]]+)\]", message):
            params = dict(re.findall(r"(\w+)=([^,\]]+)", m.group(1)))
            media.append({"type": "file", "data": params})
        plain = re.sub(r"\[CQ:[^\]]+\]", "", message).strip()
        if plain:
            texts.append(plain)
        return " ".join(texts), media
    if isinstance(message, list):
        for seg in message:
            if not isinstance(seg, dict):
                continue
            t = seg.get("type")
            d = seg.get("data") or {}
            if t == "text":
                texts.append(str(d.get("text") or ""))
            elif t in ("image", "file", "record"):
                media.append({"type": t, "data": d})
        return "".join(texts).strip(), media
    return "", []


async def _fetch_url(url: str) -> bytes | None:
    if not url:
        return None
    try:
        # file:// local path
        if url.startswith("file://"):
            p = Path(url[7:])
            return p.read_bytes() if p.is_file() else None
        if Path(url).is_file():
            return Path(url).read_bytes()
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.content
    except Exception as e:
        logger.warning("onebot fetch media failed: %s", e)
        return None


async def handle_event(
    data_root: Path,
    event: dict[str, Any],
    profile_id: str = "default",
    send_fn: SendFn | None = None,
) -> dict[str, Any]:
    if event.get("post_type") != "message":
        return {"handled": False}

    s = load_app_settings(data_root)
    if not (s.channels or {}).get("master_enabled"):
        return {"handled": False, "reason": "master off"}
    cfg = (s.channels or {}).get("onebot") or {}
    if not cfg.get("enabled"):
        return {"handled": False, "reason": "onebot off"}
    # 通道→profile 绑定（方案 A）：配置优先于调用方参数
    from . import bound_profile_id

    profile_id = bound_profile_id(data_root, "onebot", profile_id)

    user_id = event.get("user_id")
    msg_type = event.get("message_type", "private")
    raw = event.get("message") if "message" in event else event.get("raw_message")
    text, media_segs = _parse_message_segments(raw)
    if not text:
        text = (event.get("raw_message") or "").strip()
        # strip CQ for pairing
        text = re.sub(r"\[CQ:[^\]]+\]", "", text).strip()

    if user_id is None:
        return {"handled": False}

    http_api = cfg.get("http_api") or ""
    token = cfg.get("access_token") or ""

    async def send(payload: dict) -> dict:
        if send_fn:
            return await send_fn(http_api, payload)
        return await _http_send(http_api, payload, token)

    def target(extra: dict) -> dict:
        base = {"message_type": msg_type, "user_id": user_id}
        if msg_type == "group":
            base = {"message_type": "group", "group_id": event.get("group_id")}
        return {**base, **extra}

    allowed = cfg.get("allowed_users") or []
    if user_id not in allowed:
        code = cfg.get("pairing_code")
        if code and text and code in text.upper():
            allowed.append(user_id)
            cfg["allowed_users"] = allowed
            _save_ob_cfg(data_root, cfg)
            await send(target({"message": "绑定好啦，以后在这里说话他都会记得。"}))
            return {"handled": True, "paired": True}
        await send(target({"message": "还没配对。在念匣设置里拿配对码发给我。"}))
        return {"handled": True, "paired": False}

    from ..memory import ProfileStore

    persona_name = display_name(data_root, profile_id)
    # 群聊：@ 或角色名 或 纯媒体
    if msg_type == "group" and persona_name not in text and not media_segs:
        return {"handled": False, "reason": "group not mentioned"}

    # 入站媒体
    atts: list[Attachment] = []
    for seg in media_segs:
        d = seg.get("data") or {}
        url = d.get("url") or d.get("file") or d.get("path") or ""
        raw_b = await _fetch_url(url)
        if not raw_b and d.get("file"):
            # base64 sometimes
            try:
                raw_b = base64.b64decode(d["file"])
            except Exception:
                raw_b = None
        if raw_b:
            fn = d.get("name") or ("image.jpg" if seg.get("type") == "image" else "file.bin")
            a = save_inbound_bytes(
                data_root,
                raw_b,
                filename=fn,
                kind_hint="image" if seg.get("type") == "image" else "file",
            )
            if a:
                atts.append(a)

    if not text and not atts:
        return {"handled": False}

    store = ProfileStore(data_root, profile_id)
    sid = store.resolve_chat_session_id()
    req = ChatRequest(
        profile_id=profile_id,
        session_id=sid,
        message=text or ("（发来了附件）" if atts else ""),
        tier="L1",
        attachments=atts,
    )
    out = await run_chat_collect_async(store, req, enable_tools=True)
    reply = out["reply"]
    cleaned, paths = extract_outbound_media(reply, data_root)
    paths = paths + collect_tool_images(out.get("image_paths") or [], data_root)

    # 发文本
    if cleaned:
        await send(target({"message": cleaned[:2000]}))
    # 发图：OneBot CQ 或 base64
    for p in paths[:5]:
        try:
            b64 = base64.b64encode(p.read_bytes()).decode()
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                msg = f"[CQ:image,file=base64://{b64}]"
            else:
                msg = f"[CQ:file,file=base64://{b64},name={p.name}]"
            await send(target({"message": msg}))
        except Exception as e:
            logger.warning("onebot send media failed: %s", e)
            await send(target({"message": f"（文件 {p.name} 发送失败）"}))

    return {"handled": True, "reply": cleaned or reply, "media": len(paths)}
