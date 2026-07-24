"""聊天路由：POST /v1/chat/stream（SSE）+ 会话历史。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...config import get_settings
from ...memory import ProfileStore
from ...models import ChatRequest
from ...runtime import run_chat
from ...runtime.companion import run_regen, run_swipe

router = APIRouter(prefix="/v1", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


class SwipeRequest(BaseModel):
    profile_id: str = "default"
    session_id: str
    message_id: str
    direction: str = "new"  # prev | next | new
    tier: str = "L0"


class RegenRequest(BaseModel):
    profile_id: str = "default"
    session_id: str
    tier: str = "L0"


class EditRequest(BaseModel):
    profile_id: str = "default"
    session_id: str
    message_id: str
    content: str


@router.post("/chat/stream")
def chat_stream(req: ChatRequest):
    store = ProfileStore(get_settings().data_root, req.profile_id)
    return StreamingResponse(
        run_chat(req, store),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/chat/swipe")
def chat_swipe(req: SwipeRequest):
    """Swipes 重抽：prev/next 切变体；new 重新生成一个变体。"""
    store = ProfileStore(get_settings().data_root, req.profile_id)
    return StreamingResponse(
        run_swipe(req.profile_id, req.session_id, req.message_id, req.direction, req.tier, store),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/chat/regen")
def chat_regen(req: RegenRequest):
    """重生成：以最后一条 user 消息为提示续写新回复（编辑消息后使用）。"""
    store = ProfileStore(get_settings().data_root, req.profile_id)
    return StreamingResponse(
        run_regen(req.profile_id, req.session_id, req.tier, store),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/chat/edit")
def chat_edit(req: EditRequest) -> dict:
    """编辑自己的消息：更新内容并截断其后的所有消息（配合 /chat/regen 重走生成）。"""
    store = ProfileStore(get_settings().data_root, req.profile_id)
    msgs = store.recent_messages(req.session_id, limit=500)
    target = next((m for m in msgs if m.id == req.message_id), None)
    if target is None:
        raise HTTPException(404, "消息不存在")
    if target.role != "user":
        raise HTTPException(400, "只能编辑自己的消息")
    if not req.content.strip():
        raise HTTPException(400, "内容不能为空")
    store.update_message(req.session_id, req.message_id, content=req.content.strip())
    removed = store.truncate_after(req.session_id, req.message_id)
    return {"ok": True, "removed": removed}


@router.get("/profiles/{profile_id}/sessions/latest")
def latest_session(profile_id: str) -> dict:
    """当前启用角色的专属会话（角色=会话；没有消息也返回 session_id）。"""
    store = ProfileStore(get_settings().data_root, profile_id)
    sid = store.resolve_chat_session_id()
    msgs = store.recent_messages(sid, limit=100)
    return {
        "session_id": sid,
        "items": [m.model_dump() for m in msgs],
        "card_id": store.active_card_id(),
    }


@router.get("/profiles/{profile_id}/sessions")
def list_sessions(profile_id: str) -> dict:
    store = ProfileStore(get_settings().data_root, profile_id)
    return {"items": store.list_sessions()}


@router.get("/profiles/{profile_id}/sessions/{session_id}")
def get_session(profile_id: str, session_id: str) -> dict:
    store = ProfileStore(get_settings().data_root, profile_id)
    msgs = store.recent_messages(session_id, limit=500)
    return {"session_id": session_id, "items": [m.model_dump() for m in msgs]}


@router.delete("/profiles/{profile_id}/sessions/{session_id}")
def delete_session(profile_id: str, session_id: str) -> dict:
    store = ProfileStore(get_settings().data_root, profile_id)
    return {"ok": store.delete_session(session_id)}


@router.get("/profiles/{profile_id}/search")
def search_messages(profile_id: str, q: str) -> dict:
    """跨会话搜索聊天记录（猫箱用户求而不得的功能）。返回命中消息+定位。"""
    store = ProfileStore(get_settings().data_root, profile_id)
    q = q.strip()
    if not q:
        return {"items": []}
    ql = q.lower()
    items: list[dict] = []
    for s in store.list_sessions():
        sid = s["session_id"]
        msgs = store.recent_messages(sid, limit=2000)
        for idx, m in enumerate(msgs):
            if ql in (m.content or "").lower():
                start = max(0, (m.content or "").lower().find(ql) - 20)
                snippet = ("…" if start > 0 else "") + (m.content or "")[start : start + 60]
                items.append(
                    {
                        "session_id": sid,
                        "session_preview": s.get("preview", ""),
                        "idx": idx,
                        "role": m.role,
                        "snippet": snippet,
                        "ts": m.ts,
                    }
                )
                if len(items) >= 50:
                    return {"items": items}
    return {"items": items}


class BranchReq(BaseModel):
    upto: int  # 保留到第 N 条（含），从下一刻重开


@router.post("/profiles/{profile_id}/sessions/{session_id}/branch")
def branch_session(profile_id: str, session_id: str, req: BranchReq) -> dict:
    """会话分支：复制前 N 条消息到新会话（旧会话原样保留，可回溯多结局）。"""
    store = ProfileStore(get_settings().data_root, profile_id)
    msgs = store.recent_messages(session_id, limit=5000)
    if not msgs:
        raise HTTPException(status_code=404, detail="会话不存在或为空")
    upto = max(0, min(req.upto, len(msgs) - 1))
    new_sid = ProfileStore.new_session_id()
    for m in msgs[: upto + 1]:
        store.append_message(new_sid, m)
    return {"ok": True, "session_id": new_sid, "msg_count": upto + 1}
