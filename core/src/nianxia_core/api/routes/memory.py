"""角色与记忆路由：profiles / persona / facts / recall。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ...config import get_settings
from ...memory import ProfileStore, list_profiles

router = APIRouter(prefix="/v1", tags=["memory"])


def _store(profile_id: str) -> ProfileStore:
    return ProfileStore(get_settings().data_root, profile_id)


@router.get("/profiles")
def profiles() -> dict:
    root = get_settings().data_root
    items = list_profiles(root)
    if not items:
        store = _store("default")
        persona = store.load_persona()
        items = [{"id": "default", "name": persona.name}]
    return {"items": items}


@router.get("/profiles/{profile_id}/persona")
def get_persona(profile_id: str) -> dict:
    # 注意：cards.py 有同名路由（带 active_card 富化），两处必须保持一致；
    # 若 FastAPI 注册顺序让本路由先生效，前端拿到的会是不含 active_card 的版本。
    persona = _store(profile_id).load_persona()
    out = persona.model_dump()
    if persona.active_card_id:
        from ...runtime.cards import CardStore

        card = CardStore(_store(profile_id).data_root).get(persona.active_card_id)
        if card:
            out["active_card"] = card.model_dump()
    return out


class PersonaUpdate(BaseModel):
    name: str | None = None
    short: str | None = None
    boundaries: list[str] | None = None


@router.put("/profiles/{profile_id}/persona")
def put_persona(profile_id: str, body: PersonaUpdate) -> dict:
    """写人设（向导/编辑用）。locked 字段不在此改——人设锁是底线，只能审仓改。"""
    store = _store(profile_id)
    p = store.load_persona()
    if body.name is not None and body.name.strip():
        p.name = body.name.strip()[:20]
    if body.short is not None:
        p.identity.short = body.short.strip()[:500]
    if body.boundaries is not None:
        p.boundaries = [b.strip()[:80] for b in body.boundaries if b.strip()][:10]
    store.save_persona(p)
    return p.model_dump()


@router.get("/profiles/{profile_id}/facts")
def get_facts(profile_id: str) -> dict:
    facts = _store(profile_id).list_facts()
    return {"items": [f.model_dump() for f in facts]}


class FactIn(BaseModel):
    text: str
    pinned: bool = False


@router.post("/profiles/{profile_id}/facts")
def add_fact(profile_id: str, body: FactIn) -> dict:
    fact = _store(profile_id).add_fact(body.text, pinned=body.pinned, source="user")
    return fact.model_dump()


@router.get("/profiles/{profile_id}/recall")
def recall(profile_id: str, q: str) -> dict:
    hits = _store(profile_id).search_facts(q)
    return {"items": [f.model_dump() for f in hits]}


@router.get("/profiles/{profile_id}/bond")
def bond(profile_id: str) -> dict:
    return _store(profile_id).load_bond().model_dump()


@router.post("/profiles/{profile_id}/loops/{loop_id}/close")
def close_loop(profile_id: str, loop_id: str) -> dict:
    """闭环一个未完话头（聊完了移出活跃）。"""
    return {"ok": _store(profile_id).close_open_loop(loop_id)}


@router.get("/profiles/{profile_id}/growth")
def list_growth(profile_id: str, status: str | None = None) -> dict:
    """他的领悟列表（默认全部；?status=pending/adopted/rejected 过滤）。"""
    items = _store(profile_id).list_growth(status=status)
    return {"items": [g.model_dump() for g in items]}


@router.post("/profiles/{profile_id}/growth/{growth_id}/confirm")
def confirm_growth(profile_id: str, growth_id: str) -> dict:
    """确认 → 软约定生效（下轮装配进【软约定】块）。"""
    return {"ok": _store(profile_id).set_growth_status(growth_id, "adopted")}


@router.post("/profiles/{profile_id}/growth/{growth_id}/reject")
def reject_growth(profile_id: str, growth_id: str) -> dict:
    return {"ok": _store(profile_id).set_growth_status(growth_id, "rejected")}


@router.post("/profiles/{profile_id}/growth/{growth_id}/pin")
def pin_growth(profile_id: str, growth_id: str) -> dict:
    """把领悟升级成钉选硬规则（手动永远赢）。"""
    store = _store(profile_id)
    target = next((g for g in store.list_growth() if g.id == growth_id), None)
    if not target:
        return {"ok": False}
    store.set_growth_status(growth_id, "adopted")
    store.add_fact(target.text, pinned=True, source="user")
    return {"ok": True}


@router.post("/profiles/{profile_id}/facts/{fact_id}/pin")
def toggle_pin(profile_id: str, fact_id: str, body: dict) -> dict:
    ok = _store(profile_id).set_pinned(fact_id, bool(body.get("pinned", True)))
    return {"ok": ok}


@router.delete("/profiles/{profile_id}/facts/{fact_id}")
def delete_fact(profile_id: str, fact_id: str) -> dict:
    ok = _store(profile_id).supersede_fact(fact_id)
    return {"ok": ok}


@router.get("/profiles/{profile_id}/memory/stats")
def memory_stats(profile_id: str) -> dict:
    """记忆统计：按当前启用角色隔离。"""
    import time

    store = _store(profile_id)
    facts = store.list_facts()
    pinned = [f for f in facts if f.pinned]
    # 角色模型：会话数=该角色是否已有对话（0/1），不再暴露多会话概念
    sid = store.resolve_chat_session_id()
    msgs = store.recent_messages(sid, limit=5000)
    has_chat = any(m.role == "user" for m in msgs)
    last_active = store.session_path(sid).stat().st_mtime if store.session_path(sid).exists() else time.time()
    growth_pending = sum(1 for g in store.list_growth(status="pending"))
    return {
        "facts_total": len(facts),
        "facts_pinned": len(pinned),
        "facts_loose": len(facts) - len(pinned),
        "sessions": 1 if has_chat or msgs else 0,
        "growth_pending": growth_pending,
        "last_active": last_active,
        "card_id": store.active_card_id(),
    }
