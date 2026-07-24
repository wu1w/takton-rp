"""内置记忆工具：给 LLM 看的工具声明 + 本地执行器。

原则（PRD D0）：
- 模型「知道自己有记忆能力」，需要时自己调用；
- 全部本地读写，热路径无网络；
- 人话痕迹通过 SSE tool 事件透给前端。
"""

from __future__ import annotations

from typing import Any

from .store import ProfileStore

MEMORY_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "memory.remember",
            "description": (
                "把用户明确希望记住的事情写进长期记忆。"
                "当用户说「记住」「以后都要」「别忘了」，或主动告诉你重要的个人信息、"
                "约定、禁忌时调用。写入后长期生效。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要记住的内容，一句话"},
                    "pinned": {
                        "type": "boolean",
                        "description": "是否钉选（特别重要、永远优先时为 true）",
                        "default": False,
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory.recall_search",
            "description": (
                "在长期记忆里搜索。当聊天涉及以前谈过或记过的内容，"
                "但你不确定细节时使用，不要凭印象编造。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory.list_open_loops",
            "description": "查看你们之间还没聊完的话头（用户之前说「下次再说」的事）。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "media.generate_image",
            "description": (
                "当用户明确要求画画/生成图片时调用。prompt 用英文描述画面。"
                "画好后图会作为消息附件展示，你只需自然回应一句。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "英文画面描述"},
                },
                "required": ["prompt"],
            },
        },
    },
]

TOOL_HUMAN_NAMES = {
    "memory.remember": "记下这件事",
    "memory.recall_search": "回想",
    "memory.list_open_loops": "看未完话头",
    "media.generate_image": "画画",
}


def execute_memory_tool(
    store: ProfileStore, name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """执行记忆工具，返回 {result, human}：result 给模型，human 给前端痕迹。"""
    if name == "memory.remember":
        text = str(args.get("text", "")).strip()
        if not text:
            return {"result": {"ok": False, "error": "empty text"}, "human": "没记住（内容为空）"}
        pinned = bool(args.get("pinned", False))
        fact = store.add_fact(text, pinned=pinned, source="extracted")
        return {
            "result": {"ok": True, "fact_id": fact.id, "pinned": pinned},
            "human": f"记下了：{text}" + ("（钉选）" if pinned else ""),
        }

    if name == "memory.recall_search":
        query = str(args.get("query", "")).strip()
        hits = store.search_facts(query, limit=5)
        items = [{"text": f.text, "pinned": f.pinned} for f in hits]
        return {
            "result": {"ok": True, "items": items, "count": len(items)},
            "human": f"回想「{query}」→ {len(items)} 条",
        }

    if name == "memory.list_open_loops":
        bond = store.load_bond()
        loops = [l for l in bond.open_loops if l.get("status", "open") == "open"]
        return {
            "result": {"ok": True, "items": loops[:5], "count": len(loops)},
            "human": f"未完话头 {len(loops)} 个",
        }

    if name == "media.generate_image":
        from ..inference.image import generate_image
        from ..runtime.cards import CardStore
        from ..runtime.store import load_app_settings

        prompt = str(args.get("prompt", "")).strip()
        if not prompt:
            return {"result": {"ok": False, "error": "empty prompt"}, "human": "没画（描述为空）"}
        image_cfg = (load_app_settings(store.data_root).media or {}).get("image") or {}
        # 当前启用角色 → 锁脸提示词 + last_portrait
        card = None
        cid = store.active_card_id()
        if cid:
            card = CardStore(store.data_root).get(cid)
        r = generate_image(
            store.data_root,
            image_cfg,
            prompt,
            card=card,
            face_lock=True,
        )
        if r.get("ok"):
            who = card.name if card else "（无角色）"
            return {
                "result": {
                    "ok": True,
                    "path": r["path"],
                    "face_lock": r.get("face_lock"),
                    "last_portrait": r.get("last_portrait"),
                },
                "human": f"画好了（锁脸：{who}）",
                "image_path": r["path"],
            }
        return {"result": r, "human": f"没画成：{r.get('error', '未知原因')}"}

    return {"result": {"ok": False, "error": f"unknown tool {name}"}, "human": "未知工具"}
