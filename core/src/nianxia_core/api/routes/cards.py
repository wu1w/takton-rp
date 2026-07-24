"""角色卡 API：卡库 CRUD + 导入导出 + 启用/开场白。

小白向：卡片即「你在和谁聊」。启用后新会话自动带开场白。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ...config import get_settings
from ...memory.store import ProfileStore
from ...models import CharacterCard
from ...runtime.cards import CardStore, ensure_builtin

router = APIRouter(prefix="/v1", tags=["cards"])

MAX_CARD_FILE = 20 * 1024 * 1024
_AVATAR_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def _store() -> CardStore:
    s = CardStore(get_settings().data_root)
    ensure_builtin(s)
    return s


def _card_out(card: CharacterCard) -> dict[str, Any]:
    d = card.model_dump()
    if card.avatar:
        d["avatar_url"] = f"/v1/media/file?rel={card.avatar}"
    return d


@router.get("/cards")
def list_cards() -> dict[str, Any]:
    return {"items": [_card_out(c) for c in _store().list()]}


@router.post("/cards")
def create_card(card: CharacterCard) -> dict[str, Any]:
    card.source = "custom"
    return _card_out(_store().save(card))


class DraftReq(BaseModel):
    hint: str  # 一句话设定，如「19岁猫耳咖啡店店长，外冷内热」
    name: str = ""  # 已起名则以用户为准


@router.post("/cards/draft")
async def draft_card(req: DraftReq) -> dict[str, Any]:
    """AI 代笔：一句话 → L0 扩写卡草稿（不直接落库，用户过目后保存）。"""
    from ...runtime.draft import run_draft

    return await run_draft(get_settings().data_root, req.hint, req.name)


@router.get("/cards/{card_id}")
def get_card(card_id: str) -> dict[str, Any]:
    card = _store().get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    return _card_out(card)


@router.put("/cards/{card_id}")
def update_card(card_id: str, card: CharacterCard) -> dict[str, Any]:
    store = _store()
    old = store.get(card_id)
    if old is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    card.id = card_id
    if not card.avatar:
        card.avatar = old.avatar  # 不覆盖已有头像
    if old.source == "builtin":
        card.source = "builtin"
    return _card_out(store.save(card))


@router.delete("/cards/{card_id}")
def delete_card(card_id: str) -> dict[str, Any]:
    store = _store()
    if store.get(card_id) is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    store.delete(card_id)
    # 若有 profile 正启用这张卡，自动解除
    root = get_settings().data_root
    for pdir in root.glob("profiles/*"):
        if pdir.is_dir():
            ps = ProfileStore(root, pdir.name)
            persona = ps.load_persona()
            if persona.active_card_id == card_id:
                persona.active_card_id = None
                ps.save_persona(persona)
    return {"ok": True}


@router.post("/cards/import")
async def import_card(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    if len(data) > MAX_CARD_FILE:
        raise HTTPException(status_code=400, detail="文件太大（>20MB）")
    try:
        card = _store().import_card(data, file.filename or "card.json")
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=f"导入失败：{e}") from e
    except Exception as e:  # JSON 解析等
        raise HTTPException(status_code=400, detail=f"这不是一张有效的角色卡（{type(e).__name__}）") from e
    return _card_out(card)


@router.post("/cards/{card_id}/avatar")
async def upload_card_avatar(card_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """上传角色形象照 → 存为卡头像。用户自己的图，不生成不编造。"""
    store = _store()
    card = store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    ext = Path(file.filename or "a.png").suffix.lower()
    if ext not in _AVATAR_EXT:
        raise HTTPException(status_code=400, detail=f"图片格式不支持 {ext}：png/jpg/jpeg/webp")
    data = await file.read()
    if not data or len(data) > MAX_CARD_FILE:
        raise HTTPException(status_code=400, detail="空文件或超过 20MB")
    root = get_settings().data_root
    out_dir = root / "media" / "cards"
    out_dir.mkdir(parents=True, exist_ok=True)
    rel = f"media/cards/{card_id}{ext}"
    (root / rel).write_bytes(data)
    card.avatar = rel
    store.save(card)
    return _card_out(card)


class AvatarFromReq(BaseModel):
    rel: str  # media/ 下的已有文件（如 AI 生成产物）


@router.post("/cards/{card_id}/avatar-from")
def card_avatar_from(card_id: str, req: AvatarFromReq) -> dict[str, Any]:
    """把 media/ 下的已有图片（AI 生成/上传）设为卡头像。"""
    store = _store()
    card = store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    root = get_settings().data_root
    src = (root / req.rel).resolve()
    media_root = (root / "media").resolve()
    if not str(src).startswith(str(media_root)) or not src.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    ext = src.suffix.lower() or ".png"
    out_dir = root / "media" / "cards"
    out_dir.mkdir(parents=True, exist_ok=True)
    rel = f"media/cards/{card_id}{ext}"
    (root / rel).write_bytes(src.read_bytes())
    card.avatar = rel
    store.save(card)
    return _card_out(card)


@router.get("/cards/{card_id}/export")
def export_card(card_id: str) -> dict[str, Any]:
    payload = _store().export_card(card_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    return payload


class ActiveCardReq(BaseModel):
    card_id: str | None = None  # None = 不用卡，回到默认 persona


@router.get("/profiles/{profile_id}/persona")
def get_persona(profile_id: str) -> dict[str, Any]:
    ps = ProfileStore(get_settings().data_root, profile_id)
    persona = ps.load_persona()
    out = persona.model_dump()
    if persona.active_card_id:
        card = _store().get(persona.active_card_id)
        if card:
            out["active_card"] = _card_out(card)
    return out


@router.post("/profiles/{profile_id}/active-card")
def set_active_card(profile_id: str, req: ActiveCardReq) -> dict[str, Any]:
    """启用角色 = 切换到该角色专属会话（猫箱模型：一角一会）。"""
    root = get_settings().data_root
    ps = ProfileStore(root, profile_id)
    persona = ps.load_persona()
    if req.card_id is not None and _store().get(req.card_id) is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    persona.active_card_id = req.card_id
    ps.save_persona(persona)
    chat = ps.get_or_create_card_session(req.card_id)
    return {
        "ok": True,
        "active_card_id": req.card_id,
        "session_id": chat["session_id"],
        "created": chat["created"],
        "greeting": chat["greeting"],
    }


@router.post("/profiles/{profile_id}/sessions")
def create_session(profile_id: str) -> dict[str, Any]:
    """兼容旧前端：返回当前启用角色的专属会话（幂等，不再每次新建）。"""
    root = get_settings().data_root
    ps = ProfileStore(root, profile_id)
    persona = ps.load_persona()
    chat = ps.get_or_create_card_session(persona.active_card_id)
    return {
        "session_id": chat["session_id"],
        "greeting": chat["greeting"],
        "created": chat["created"],
    }
