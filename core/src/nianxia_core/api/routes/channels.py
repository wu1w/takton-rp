"""通道路由：状态 / 总开关 / TG · QQ官方 · 微信 iLink。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...channels.telegram import (
    get_adapter,
    load_token,
    new_pairing_code,
    _save_tg_cfg,
    _tg_cfg,
)
from ...config import get_settings
from ...runtime.store import load_app_settings, save_app_settings

router = APIRouter(prefix="/v1/channels", tags=["channels"])


@router.get("/status")
def status() -> dict:
    from ...channels.qqbot import status as qq_status
    from ...channels.weixin import status as wx_status

    root = get_settings().data_root
    s = load_app_settings(root)
    wx = wx_status(root)
    return {
        "master_enabled": bool((s.channels or {}).get("master_enabled")),
        "telegram": get_adapter(root).status(),
        "qqbot": qq_status(root),
        "onebot": qq_status(root),  # 兼容
        "weixin": wx,
        "wecom": wx,  # 兼容旧前端字段名 → 指向微信
    }


class MasterIn(BaseModel):
    enabled: bool


@router.post("/master")
def set_master(body: MasterIn) -> dict:
    root = get_settings().data_root
    s = load_app_settings(root)
    channels = dict(s.channels or {})
    channels["master_enabled"] = body.enabled
    s.channels = channels
    save_app_settings(root, s)
    return {"ok": True, "master_enabled": body.enabled}


# ---------- 通道→角色绑定（方案 A） ----------


class BindIn(BaseModel):
    card_id: str | None = None  # None=解绑，回到跟随 App 的 default profile


@router.post("/{channel}/bind")
def bind_channel(channel: str, body: BindIn) -> dict:
    """把通道绑到一张角色卡：内部建专属 profile（ch_<channel>），记忆/人设与 App 隔离。"""
    from ...channels import CHANNEL_KEYS
    from ...memory import ProfileStore
    from ...runtime.cards import CardStore

    if channel not in CHANNEL_KEYS:
        raise HTTPException(status_code=404, detail=f"未知通道：{channel}")
    root = get_settings().data_root
    s = load_app_settings(root)
    channels = dict(s.channels or {})
    cfg = dict(channels.get(channel) or {})

    if body.card_id:
        card = CardStore(root).get(body.card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="角色卡不存在")
        pid = f"ch_{channel}"
        ps = ProfileStore(root, pid)  # 布局在构造时自动建
        persona = ps.load_persona()
        persona.active_card_id = card.id
        ps.save_persona(persona)
        cfg["profile_id"] = pid
        channels[channel] = cfg
        s.channels = channels
        save_app_settings(root, s)
        return {"ok": True, "profile_id": pid, "card_name": card.name}

    cfg.pop("profile_id", None)  # 解绑 → 跟随 App
    channels[channel] = cfg
    s.channels = channels
    save_app_settings(root, s)
    return {"ok": True, "profile_id": "default", "card_name": None}


@router.get("/bindings")
def channel_bindings() -> dict:
    """各通道当前绑定：profile_id + 生效角色卡名（未绑定=default/跟随 App 当前卡）。"""
    from ...channels import CHANNEL_KEYS
    from ...channels import bound_profile_id
    from ...memory import ProfileStore
    from ...runtime.cards import CardStore

    root = get_settings().data_root
    cs = CardStore(root)
    s = load_app_settings(root)
    out: dict = {}
    for ch in CHANNEL_KEYS:
        raw_cfg = (s.channels or {}).get(ch) or {}
        bound = bool((raw_cfg.get("profile_id") or "").strip())
        pid = bound_profile_id(root, ch)
        card_name = None
        persona = ProfileStore(root, pid).load_persona()
        if persona.active_card_id:
            c = cs.get(persona.active_card_id)
            card_name = c.name if c else None
        out[ch] = {"bound": bound, "profile_id": pid, "card_name": card_name}
    return out


class TgSetupIn(BaseModel):
    token: str


@router.post("/telegram/setup")
async def tg_setup(body: TgSetupIn) -> dict:
    root = get_settings().data_root
    try:
        result = await get_adapter(root).setup(body.token)
    except Exception as e:
        return {"ok": False, "error": f"token 验证失败：{e}"}
    return result


class EnableIn(BaseModel):
    enabled: bool


@router.post("/telegram/enable")
def tg_enable(body: EnableIn) -> dict:
    root = get_settings().data_root
    if body.enabled and not load_token(root):
        return {"ok": False, "error": "先 setup token"}
    cfg = _tg_cfg(root)
    cfg["enabled"] = body.enabled
    _save_tg_cfg(root, cfg)
    return {"ok": True, "enabled": body.enabled}


@router.post("/telegram/pairing/rotate")
def tg_rotate_code() -> dict:
    root = get_settings().data_root
    cfg = _tg_cfg(root)
    cfg["pairing_code"] = new_pairing_code()
    _save_tg_cfg(root, cfg)
    return {"ok": True, "pairing_code": cfg["pairing_code"]}


# ---------- QQ 官方机器人 ----------


class QqSetupIn(BaseModel):
    app_id: str
    app_secret: str


@router.post("/qqbot/setup")
async def qq_setup(body: QqSetupIn) -> dict:
    from ...channels.qqbot import get_adapter as get_qq

    return await get_qq(get_settings().data_root).setup_validate(body.app_id, body.app_secret)


@router.post("/qqbot/enable")
def qq_enable(body: EnableIn) -> dict:
    from ...channels.qqbot import _qq_cfg, _save_qq_cfg, status as qq_status

    root = get_settings().data_root
    st = qq_status(root)
    if body.enabled and not st.get("configured"):
        return {"ok": False, "error": "先填写 AppID + AppSecret"}
    cfg = _qq_cfg(root)
    cfg["enabled"] = body.enabled
    _save_qq_cfg(root, cfg)
    return {"ok": True, "enabled": body.enabled}


@router.post("/qqbot/pairing/rotate")
def qq_rotate() -> dict:
    from ...channels.qqbot import _qq_cfg, _save_qq_cfg

    root = get_settings().data_root
    cfg = _qq_cfg(root)
    cfg["pairing_code"] = new_pairing_code()
    _save_qq_cfg(root, cfg)
    return {"ok": True, "pairing_code": cfg["pairing_code"]}


@router.post("/onebot/setup")
async def ob_setup_compat(body: QqSetupIn) -> dict:
    return await qq_setup(body)


@router.post("/onebot/enable")
def ob_enable_compat(body: EnableIn) -> dict:
    return qq_enable(body)


# ---------- 微信个人号（iLink） ----------


@router.post("/weixin/qr/start")
async def wx_qr_start() -> dict:
    from ...channels.weixin import get_adapter as get_wx

    return await get_wx(get_settings().data_root).qr_start()


class WxQrPollIn(BaseModel):
    qrcode: str
    redirect_base: str = ""


@router.post("/weixin/qr/poll")
async def wx_qr_poll(body: WxQrPollIn) -> dict:
    from ...channels.weixin import get_adapter as get_wx

    base = body.redirect_base.strip() or None
    return await get_wx(get_settings().data_root).qr_poll(body.qrcode, base_url=base)


@router.post("/weixin/enable")
def wx_enable(body: EnableIn) -> dict:
    from ...channels.weixin import _save_wx_cfg, _wx_cfg, status as wx_status

    root = get_settings().data_root
    st = wx_status(root)
    if body.enabled and not st.get("configured"):
        return {"ok": False, "error": "先扫码登录微信"}
    cfg = _wx_cfg(root)
    cfg["enabled"] = body.enabled
    _save_wx_cfg(root, cfg)
    return {"ok": True, "enabled": body.enabled}


@router.post("/weixin/pairing/rotate")
def wx_rotate() -> dict:
    from ...channels.weixin import _save_wx_cfg, _wx_cfg

    root = get_settings().data_root
    cfg = _wx_cfg(root)
    cfg["pairing_code"] = new_pairing_code()
    _save_wx_cfg(root, cfg)
    return {"ok": True, "pairing_code": cfg["pairing_code"]}


# 旧企微路径：引导迁移到微信
@router.post("/wecom/setup")
async def wecom_setup_deprecated() -> dict:
    return {
        "ok": False,
        "error": "企业微信已改为「微信机器人」。请在设置里用微信扫码登录。",
    }


@router.post("/wecom/enable")
def wecom_enable_compat(body: EnableIn) -> dict:
    return wx_enable(body)
