"""通道媒体公共层：入站落盘 + 出站路径解析（对标 Hermes gateway 思路的精简版）。

- 入站：任意通道把图片/文件 bytes 落到 data_root/media/inbox/
- 出站：把 media/ 相对路径或绝对路径解析成可读文件；聊天回复里识别 MEDIA:path
"""

from __future__ import annotations

import mimetypes
import re
import time
from pathlib import Path
from typing import Any

from ..models import Attachment

_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_MEDIA_TAG = re.compile(r"MEDIA:([^\s]+)")
_MD_IMG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def inbox_dir(data_root: Path) -> Path:
    d = Path(data_root) / "media" / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_inbound_bytes(
    data_root: Path,
    data: bytes,
    *,
    filename: str = "file.bin",
    kind_hint: str = "",
) -> Attachment | None:
    if not data:
        return None
    name = Path(filename or "file.bin").name
    ext = Path(name).suffix.lower()
    mime = mimetypes.guess_type(name)[0] or ""
    is_image = (
        kind_hint == "image"
        or ext in _IMG_EXT
        or mime.startswith("image/")
        or data[:8].startswith(b"\x89PNG")
        or data[:3] == b"\xff\xd8\xff"
    )
    kind = "image" if is_image else "file"
    if kind == "file" and ext not in {
        ".txt",
        ".md",
        ".csv",
        ".log",
        ".json",
        ".yaml",
        ".yml",
        ".py",
        ".js",
        ".ts",
        ".html",
        ".css",
        ".xml",
        ".toml",
        ".ini",
        ".pdf",
        ".zip",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
    }:
        # 仍保存，文本类才内联
        pass
    stored = f"{int(time.time())}_{name}"
    path = inbox_dir(data_root) / stored
    path.write_bytes(data)
    text = None
    if kind == "file" and ext in {
        ".txt",
        ".md",
        ".csv",
        ".log",
        ".json",
        ".yaml",
        ".yml",
        ".py",
        ".js",
        ".ts",
        ".html",
        ".css",
        ".xml",
        ".toml",
        ".ini",
    }:
        try:
            text = data.decode("utf-8", errors="replace")[:3000]
        except Exception:
            text = None
    return Attachment(
        kind=kind,  # type: ignore[arg-type]
        name=name,
        url=f"/v1/media/file?rel=media/inbox/{stored}",
        text=text,
    )


def resolve_local_media(data_root: Path, rel_or_path: str) -> Path | None:
    """把 MEDIA 标签 / 相对路径 / file URL 解析成本地绝对路径。"""
    raw = (rel_or_path or "").strip().strip("\"'")
    if not raw:
        return None
    if raw.startswith("file://"):
        raw = raw[7:]
    if raw.startswith("/v1/media/file?rel="):
        raw = raw.split("rel=", 1)[-1]
    p = Path(raw)
    if p.is_file():
        return p.resolve()
    cand = (Path(data_root) / raw).resolve()
    media_root = (Path(data_root) / "media").resolve()
    if str(cand).startswith(str(media_root)) and cand.is_file():
        return cand
    return None


def extract_outbound_media(text: str, data_root: Path) -> tuple[str, list[Path]]:
    """从回复正文抽出本地媒体路径，返回 (清洗后正文, 文件列表)。"""
    files: list[Path] = []
    cleaned = text or ""

    def take(path_s: str) -> None:
        p = resolve_local_media(data_root, path_s)
        if p and p not in files:
            files.append(p)

    for m in _MEDIA_TAG.finditer(cleaned):
        take(m.group(1))
    cleaned = _MEDIA_TAG.sub("", cleaned)
    for m in _MD_IMG.finditer(cleaned):
        take(m.group(1))
    # 也识别绝对/相对 media 路径裸串
    for m in re.finditer(r"(media/[^\s\"']+\.(?:png|jpg|jpeg|webp|gif))", cleaned, re.I):
        take(m.group(1))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, files


def collect_tool_images(events_image_paths: list[str], data_root: Path) -> list[Path]:
    out: list[Path] = []
    for rel in events_image_paths:
        p = resolve_local_media(data_root, rel)
        if p and p not in out:
            out.append(p)
    return out


def run_chat_collect(
    store: Any,
    req: Any,
    *,
    enable_tools: bool = False,
) -> dict[str, Any]:
    """跑一轮聊天，汇总文本 + 工具产出的图片路径。"""
    import asyncio
    import json

    from ..runtime.companion import run_chat

    parts: list[str] = []
    images: list[str] = []
    error_text = ""

    async def _go() -> None:
        nonlocal error_text
        async for chunk in run_chat(req, store, enable_tools=enable_tools):
            event = ""
            data_line = ""
            for line in chunk.splitlines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_line = line[5:].strip()
            if not data_line:
                continue
            try:
                payload = json.loads(data_line)
            except Exception:
                continue
            if event == "delta":
                parts.append(payload.get("text", ""))
            elif event == "error":
                error_text = payload.get("message", "")
            elif event == "tool_result" and payload.get("image_path"):
                images.append(payload["image_path"])

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        pass
    # always run in new loop-safe way
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # nested: use create_task pattern via asyncio.run_coroutine_threadsafe not available
        # callers are already async
        raise RuntimeError("use run_chat_collect_async from async context")
    asyncio.run(_go())
    reply = ("".join(parts).strip() or error_text or "……").strip()
    return {"reply": reply, "image_paths": images}


async def run_chat_collect_async(
    store: Any,
    req: Any,
    *,
    enable_tools: bool = False,
) -> dict[str, Any]:
    import json

    from ..runtime.companion import run_chat

    parts: list[str] = []
    images: list[str] = []
    error_text = ""
    async for chunk in run_chat(req, store, enable_tools=enable_tools):
        event = ""
        data_line = ""
        for line in chunk.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_line = line[5:].strip()
        if not data_line:
            continue
        try:
            payload = json.loads(data_line)
        except Exception:
            continue
        if event == "delta":
            parts.append(payload.get("text", ""))
        elif event == "error":
            error_text = payload.get("message", "")
        elif event == "tool_result" and payload.get("image_path"):
            images.append(payload["image_path"])
    reply = ("".join(parts).strip() or error_text or "……").strip()
    return {"reply": reply, "image_paths": images}
