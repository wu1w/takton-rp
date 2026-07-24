"""媒体路由：图片/语音生成 + 媒体文件服务（路径防逃逸）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import time

from ...config import get_settings
from ...inference.image import generate_image
from ...inference.tts import synthesize
from ...runtime.store import load_app_settings

router = APIRouter(prefix="/v1/media", tags=["media"])


@router.get("/file")
def media_file(rel: str) -> FileResponse:
    """只服务 data_root/media/ 下的文件，防路径逃逸。"""
    root = get_settings().data_root
    target = (root / rel).resolve()
    media_dir = (root / "media").resolve()
    if not str(target).startswith(str(media_dir)) or not target.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(target)


_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_TXT_EXT = {".txt", ".md", ".csv", ".log", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".html", ".css", ".xml", ".toml", ".ini"}
_MAX_BYTES = 10 * 1024 * 1024  # 单附件 10MB
_TXT_INLINE = 3000  # 文本附件内联上限


@router.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    """对话附件上传：图片存 media/uploads/，文本类顺便提取内联内容。"""
    root = get_settings().data_root
    name = Path(file.filename or "unnamed").name  # 剥路径防穿越
    ext = Path(name).suffix.lower()
    if ext in _IMG_EXT:
        kind = "image"
    elif ext in _TXT_EXT:
        kind = "file"
    else:
        raise HTTPException(400, f"暂不支持的文件类型 {ext or '(无扩展名)'}：图片或文本类文件")

    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > _MAX_BYTES:
        raise HTTPException(400, f"文件超过 {_MAX_BYTES // 1024 // 1024}MB 上限")

    up = root / "media" / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    stored = f"{int(time.time())}_{name}"
    (up / stored).write_bytes(data)

    text = None
    if kind == "file":
        try:
            text = data.decode("utf-8", errors="replace")[:_TXT_INLINE]
        except Exception:
            text = None

    return {
        "ok": True,
        "kind": kind,
        "name": name,
        "url": f"/v1/media/file?rel=media/uploads/{stored}",
        "size": len(data),
        "text": text,
    }


class ImageIn(BaseModel):
    prompt: str
    card_id: str | None = None  # 指定角色锁脸；空=当前启用卡
    face_lock: bool = True
    compose: str = "half"  # full|half|portrait


@router.post("/image")
def image(body: ImageIn) -> dict:
    root = get_settings().data_root
    cfg = dict((load_app_settings(root).media or {}).get("image") or {})
    if body.compose:
        cfg["compose"] = body.compose
    card = None
    if body.face_lock:
        from ...memory.store import ProfileStore
        from ...runtime.cards import CardStore

        cid = body.card_id
        if not cid:
            cid = ProfileStore(root, "default").active_card_id()
        if cid:
            card = CardStore(root).get(cid)
    return generate_image(
        root, cfg, body.prompt, card=card, face_lock=body.face_lock, compose=body.compose
    )


class TtsIn(BaseModel):
    text: str
    voice: str = ""  # 角色卡音色（edge-tts voice id），空=默认


@router.post("/tts")
async def tts(body: TtsIn) -> dict:
    root = get_settings().data_root
    tts_cfg = (load_app_settings(root).media or {}).get("tts") or {}
    if not tts_cfg.get("enabled"):
        return {"ok": False, "error": "语音朗读未开启（设置 · 语音朗读）"}
    r = await synthesize(root, body.text, voice=body.voice or "zh-CN-XiaoxiaoNeural")
    if r.get("ok") and r.get("path"):
        r["url"] = f"/v1/media/file?rel={r['path']}"
    return r


class InferPersonaIn(BaseModel):
    rel: str  # data_root 相对路径（media/...），待读的角色形象图


@router.post("/infer-persona")
async def infer_persona(body: InferPersonaIn) -> dict:
    """视觉补人设：L0（mmproj）读角色形象图 → 写人设草稿。没视觉能力如实报错。"""
    import base64
    import mimetypes

    import httpx

    from ...inference.l0 import L0Sidecar

    root = get_settings().data_root
    target = (root / body.rel).resolve()
    media_root = (root / "media").resolve()
    if not str(target).startswith(str(media_root)) or not target.is_file():
        raise HTTPException(404, "图片不存在")

    sidecar = L0Sidecar(root)
    if sidecar.find_mmproj() is None:
        return {"ok": False, "error": "本地小模型没有视觉组件（mmproj），暂时读不了图"}
    if not sidecar.is_running() and not sidecar.start():
        return {"ok": False, "error": "本地小模型没跑起来，稍后再试"}

    mime = mimetypes.guess_type(target.name)[0] or "image/png"
    b64 = base64.b64encode(target.read_bytes()).decode()
    prompt = (
        "你是角色卡撰写助手。看这张角色形象图，用中文输出两段，不要别的废话：\n"
        "【外貌】100字内外貌/穿着/气质描述，第三人称。\n"
        "【性格】根据神态气质推测3-5个性格关键词，附一句话说明。"
    )
    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(
                "http://127.0.0.1:7421/v1/chat/completions",
                json={
                    "model": "l0",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                            ],
                        }
                    ],
                    "max_tokens": 800,
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},  # 草稿任务不需要思考
                },
            )
            r.raise_for_status()
            msg = (r.json().get("choices") or [{}])[0].get("message", {})
            text = msg.get("content") or msg.get("reasoning_content") or ""
    except Exception as e:
        return {"ok": False, "error": f"读图失败：{e}"}
    if not text.strip():
        return {"ok": False, "error": "小模型没给出描述，换张清晰的图试试"}
    return {"ok": True, "draft": text.strip()}
