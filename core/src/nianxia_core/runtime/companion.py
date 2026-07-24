"""CompanionRuntime — 单轮聊天编排（骨架）。

热路径：Policy(薄) → MemoryAssemble(纯规则+按需唤起) → 推理(可带记忆工具) → SSE 流式 → 落盘。
L1 未配置时走「占位回复」保证端到端可跑，trace 中如实标注 stub。

记忆三层可见性：
1. 装配层：钉选/唤起/设备时间进 system（trace.memory_usage 透出）
2. 工具层：模型自主调 memory.remember / recall_search / list_open_loops（tool_* 事件透出）
3. 落盘层：所有写入立即入 facts.jsonl，前端记忆页可见
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from ..clock import clock
from ..memory import ProfileStore, assemble
from ..memory.tools import MEMORY_TOOLS, TOOL_HUMAN_NAMES, execute_memory_tool
from ..models import ChatMessage, ChatRequest
from .store import load_app_settings, get_llm_api_key
from .summarize import maybe_summarize, pair_window

MAX_TOOL_LOOPS = 3


def _parse_mes_example(text: str) -> list[tuple[str, str]]:
    """mes_example（{{user}}:/{{char}}: 或 <START> 分隔）→ [(user, char), ...]。"""
    import re

    body = re.sub(r"<START>", "\n", text, flags=re.IGNORECASE).strip()
    pairs: list[tuple[str, str]] = []
    cur_role: str | None = None
    cur: list[str] = []

    def flush() -> None:
        nonlocal cur_role, cur
        line = "\n".join(cur).strip()
        if cur_role == "user" and line:
            pairs.append((line, ""))
        elif cur_role == "char" and line and pairs and pairs[-1][1] == "":
            pairs[-1] = (pairs[-1][0], line)
        cur_role, cur = None, []

    for raw in body.splitlines():
        m = re.match(r"^\s*\{\{(user|char)\}\}\s*[:：]\s*(.*)$", raw)
        if m:
            flush()
            cur_role = "user" if m.group(1) == "user" else "char"
            cur = [m.group(2)]
        elif cur_role:
            cur.append(raw)
    flush()
    return [(u, c) for u, c in pairs if c]


def _build_user_content(store: ProfileStore, req: ChatRequest, engine_name: str | None) -> tuple[str, Any]:
    """(落库文本, 发给模型的 content)。

    - 图片：有视觉能力 → OpenAI 多模态 content 数组（base64 data URL）；无 → 如实声明看不到
    - 文本附件：内联进用户消息（上传时已截断）
    """
    atts = req.attachments or []
    if not atts:
        return req.message, req.message

    import base64
    import mimetypes

    vision_ok = engine_name == "l1"  # 云模型默认按有视觉；不支持会在 API 层如实报错
    if engine_name == "l0":
        from ..inference.l0 import L0Sidecar

        vision_ok = L0Sidecar(store.data_root).find_mmproj() is not None

    text_parts = [req.message] if req.message else []
    marks: list[str] = []
    images: list[dict[str, Any]] = []
    blind: list[str] = []

    for a in atts:
        if a.kind == "image":
            marks.append(f"[图片] {a.name}")
            if not vision_ok:
                blind.append(a.name)
                continue
            rel = a.url.split("rel=", 1)[-1]
            path = (store.data_root / rel).resolve()
            media_root = (store.data_root / "media").resolve()
            if str(path).startswith(str(media_root)) and path.is_file():
                mime = mimetypes.guess_type(a.name)[0] or "image/png"
                b64 = base64.b64encode(path.read_bytes()).decode()
                images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        else:
            marks.append(f"[文件] {a.name}")
            if a.text:
                text_parts.append(f"【附件 {a.name}】\n{a.text}")

    if blind:
        text_parts.append(
            f"（用户附了图片 {'、'.join(blind)}，但我现在没有视觉能力（缺 mmproj 组件），看不到图）"
        )

    stored_text = " ".join([req.message] + marks).strip()
    if images:
        content: Any = [{"type": "text", "text": "\n\n".join(text_parts) or "请看这张图"}] + images
    else:
        content = "\n\n".join(text_parts)
    return stored_text, content


def sse(event: str, data: dict[str, Any]) -> str:
    import json

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


_ENGINE_UNAVAILABLE = (
    "还没有接入推理引擎：在「设置 · 怎么聊」里配好云钥匙（L1），"
    "或等本地小模型（L0）下载完成后，这里才是真回答。"
)


async def run_chat(
    req: ChatRequest, store: ProfileStore, enable_tools: bool = True
) -> AsyncGenerator[str, None]:
    """一轮对话（SSE 事件流）。通道调用传 enable_tools=False。"""
    session_id = req.session_id or store.resolve_chat_session_id()
    yield sse("session", {"session_id": session_id, "profile_id": req.profile_id})

    app_settings = load_app_settings(store.data_root)
    ambient = (app_settings.ambient or {}) if app_settings.ambient else {}

    # 装配（query 驱动按需唤起；设备时间与日志同源）
    assembled = assemble(
        store,
        tier=req.tier,
        query=req.message,
        include_device_time=bool(ambient.get("device_time_enabled", True)),
        session_id=session_id,
        ambient=ambient,
    )
    snap = assembled["device_time"]
    usage = assembled["memory_usage"]

    # base-safety：本地关键词兜底（不记录不上传）；命中则前置安全引导块
    safety_cfg = (app_settings.safety or {}) if app_settings.safety else {}
    safety_hit = None
    if safety_cfg.get("enabled", True):
        from .policy import check_safety, safety_block

        safety_hit = check_safety(req.message)

    yield sse(
        "trace",
        {
            "stage": "assemble",
            "memory_usage": usage,
            "device_time": snap["iso"],
            **({"safety": safety_hit} if safety_hit else {}),
        },
    )

    safety_prefix = ""
    if safety_hit:
        from .policy import safety_block

        safety_prefix = safety_block(safety_hit) + "\n\n"

    stored_text, user_content = _build_user_content(store, req, None)
    store.append_message(
        session_id,
        ChatMessage(role="user", content=stored_text, device_time=snap),
    )

    # 生成用历史：pair_window 后的存量消息 + 刚发的这条（内容可能带附件/多模态）
    history = pair_window(store.recent_messages(session_id, limit=200), req.tier)
    gen_history = history[:-1] + [ChatMessage(role="user", content=user_content)]

    box: dict[str, Any] = {"engine": "none", "client": None, "full": [], "ran_tools": False}
    async for ev in _generate_reply(
        store, session_id, req, app_settings, ambient, safety_prefix,
        query=req.message, history=gen_history, preassembled=assembled,
        enable_tools=enable_tools, box=box,
    ):
        yield ev

    engine = box["engine"]
    client = box["client"]
    reply = "".join(box["full"])
    if reply:
        store.append_message(
            session_id,
            ChatMessage(
                role="assistant", content=reply,
                swipes=[reply], swipe_idx=0,
                device_time=clock.snapshot(),
            ),
        )

    yield sse(
        "message_end",
        {"engine": engine, "chars": len(reply), "session_id": session_id},
    )

    # 冷路径（响应流完之后）：摘要压缩。无引擎则如实跳过。
    summary = await maybe_summarize(store, session_id, client)
    if summary:
        yield sse(
            "trace",
            {"stage": "summarized", "covers_upto": summary.covers_upto},
        )

    # 冷路径：Epochs 封纪（≥3 段 3 天前的会话，需真引擎）
    if client is not None:
        from .epochs import maybe_seal_epoch

        epoch = await maybe_seal_epoch(store, client)
        if epoch:
            yield sse("trace", {"stage": "epoch", "text": epoch.text[:40]})

    # 冷路径：open loop 规则预埋（0 LLM）+ 上次会话时间
    from ..memory.openloops import detect_deferral, make_loop, topic_already_open
    from ..clock import clock as _clock

    bond = store.load_bond()
    if detect_deferral(req.message):
        loop = make_loop(req.message)
        if not topic_already_open(bond.open_loops, loop["topic"]):
            store.add_open_loop(loop)
            yield sse("trace", {"stage": "open_loop", "topic": loop["topic"]})
    bond.last_session_at = _clock.now().timestamp()
    store.save_bond(bond)

    # 冷路径：Growth 领悟策展（需真引擎；日配额/去重/溯源）
    mem_cfg = (app_settings.memory or {}) if app_settings.memory else {}
    if mem_cfg.get("growth_enabled", True) and client is not None:
        from .growth import maybe_curate

        produced = await maybe_curate(
            store,
            session_id,
            client,
            daily_cap=int(mem_cfg.get("growth_daily_cap", 3)),
        )
        for g in produced:
            yield sse(
                "growth",
                {"id": g.id, "text": g.text, "status": "pending"},
            )
    yield sse("done", {})


# ---------------------------------------------------------------------------
# 共用生成管线 + Swipes/重生成（借鉴酒馆，Lite 版）
# ---------------------------------------------------------------------------


async def _generate_reply(
    store: ProfileStore,
    session_id: str,
    req: ChatRequest,
    app_settings: Any,
    ambient: dict[str, Any],
    safety_prefix: str,
    query: str,
    history: list[ChatMessage],
    preassembled: dict[str, Any] | None,
    enable_tools: bool,
    box: dict[str, Any],
) -> AsyncGenerator[str, None]:
    """共用生成管线：引擎挑选 → 装配（scale 阶梯）→ 流式+工具循环。

    history = 生成点之前的完整对话（最后一条须为 user 消息，即本轮提示）。
    结果经 box 返回：engine/client/full(增量文本)/ran_tools。
    """
    from ..inference.router import ContextOverflowError
    from ..memory.tokenmeter import estimate_messages, token_budget
    from .engine import pick_engine

    api_key = get_llm_api_key(store.data_root)
    engine_name, client = pick_engine(req.tier, store.data_root, app_settings.media, api_key)
    box["engine"] = engine_name or "none"
    box["client"] = client
    full: list[str] = box["full"]

    def build_messages(scale: float) -> list[dict[str, Any]]:
        asm = preassembled if (scale >= 1.0 and preassembled is not None) else assemble(
            store,
            tier=req.tier,
            query=query,
            include_device_time=bool(ambient.get("device_time_enabled", True)),
            session_id=session_id,
            ambient=ambient,
            scale=scale,
        )
        h = list(history)
        if scale < 1.0 and len(h) > 2:  # 历史同比收缩，保持 user 开头成对
            keep = max(2, int(len(h) * scale))
            h = h[-keep:]
            while h and h[0].role == "assistant":
                h = h[1:]
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": safety_prefix + asm["system"]}
        ]
        # 角色卡示例对话 → few-shot（scale≤0.5 砍掉换空间）
        if scale > 0.5 and asm.get("mes_example"):
            for ex_user, ex_char in _parse_mes_example(asm["mes_example"]):
                msgs.append({"role": "user", "content": ex_user})
                msgs.append({"role": "assistant", "content": ex_char})
        tail = h[-1] if h else None
        msgs += [{"role": m.role, "content": m.content} for m in (h[:-1] if tail else h)]
        # 作者备注：注入历史尾部（scale≤0.5 砍）
        if scale > 0.5 and asm.get("post_history_instructions"):
            msgs.append({"role": "system", "content": asm["post_history_instructions"]})
        if tail is not None:
            msgs.append({"role": tail.role, "content": tail.content})
        return msgs

    try:
        if client:
            budget = token_budget(engine_name)
            scales = [1.0, 0.5, 0.25]
            scale_idx = 0
            # 主动估算：超预算先降档再发（不撞墙）
            messages = build_messages(scales[scale_idx])
            while scale_idx < len(scales) - 1 and estimate_messages(messages) > budget:
                scale_idx += 1
                messages = build_messages(scales[scale_idx])
                yield sse("trace", {"stage": "context_shrink", "scale": scales[scale_idx], "reason": "proactive"})

            while True:  # 溢出重试环（撞墙后 reactive 降档）
                try:
                    for _ in range(MAX_TOOL_LOOPS):
                        tool_calls: list[dict[str, Any]] = []
                        async for ev in client.stream_events(
                            messages, tools=MEMORY_TOOLS if enable_tools else None
                        ):
                            if ev["type"] == "delta":
                                full.append(ev["text"])
                                yield sse("delta", {"text": ev["text"]})
                            elif ev["type"] == "tool_calls":
                                tool_calls = ev["calls"]

                        if not tool_calls:
                            break

                        box["ran_tools"] = True
                        # 执行工具 → 事件透出 → 结果回喂模型
                        messages.append(
                            {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": c["id"],
                                        "type": "function",
                                        "function": {
                                            "name": c["name"],
                                            "arguments": c["raw_arguments"],
                                        },
                                    }
                                    for c in tool_calls
                                ],
                            }
                        )
                        for c in tool_calls:
                            human_name = TOOL_HUMAN_NAMES.get(c["name"], c["name"])
                            yield sse(
                                "tool_call",
                                {"tool": c["name"], "human": human_name, "args": c["args"]},
                            )
                            out = execute_memory_tool(store, c["name"], c["args"])
                            yield sse(
                                "tool_result",
                                {
                                    "tool": c["name"],
                                    "human": out["human"],
                                    **({"image_path": out["image_path"]} if out.get("image_path") else {}),
                                },
                            )
                            import json as _json

                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": c["id"],
                                    "content": _json.dumps(out["result"], ensure_ascii=False),
                                }
                            )
                    break  # 正常完成，跳出重试环
                except ContextOverflowError:
                    # 已吐出内容或已执行工具就不重试（避免重复写/半截话）
                    if full or box["ran_tools"] or scale_idx >= len(scales) - 1:
                        raise
                    scale_idx += 1
                    messages = build_messages(scales[scale_idx])
                    yield sse("trace", {"stage": "context_shrink", "scale": scales[scale_idx], "reason": "reactive"})
        else:
            # 未接入任何引擎：如实报错，不伪造回复（项目红线：无 mock 数据）
            yield sse(
                "error",
                {"kind": "engine_unavailable", "message": _ENGINE_UNAVAILABLE},
            )
    except ContextOverflowError:
        yield sse("error", {"kind": "context_overflow", "message": "上下文太长了，开新会话试试"})
    except Exception as e:  # 推理失败不吞：人话错误 + 已生成内容保留
        yield sse("error", {"kind": "inference", "message": f"推理出错：{e}"})


async def run_swipe(
    profile_id: str,
    session_id: str,
    message_id: str,
    direction: str,
    tier: str,
    store: ProfileStore,
) -> AsyncGenerator[str, None]:
    """Swipes（酒馆式重抽）：

    - prev/next：在已有变体间切换（纯本地，无生成）
    - new：以该回复之前的对话为前缀重新生成一个变体，追加进 swipes
    """
    msgs = store.recent_messages(session_id, limit=500)
    target = next((m for m in msgs if m.id == message_id), None)
    if target is None or target.role != "assistant":
        yield sse("error", {"kind": "swipe", "message": "只能对角色的回复重抽"})
        return

    swipes = list(target.swipes) or [target.content]
    idx = max(0, min(target.swipe_idx, len(swipes) - 1))

    if direction in ("prev", "next"):
        idx = idx - 1 if direction == "prev" else min(idx + 1, len(swipes) - 1)
        store.update_message(
            session_id, target.id, swipes=swipes, swipe_idx=idx, content=swipes[idx]
        )
        yield sse("swipe", {
            "message_id": target.id, "content": swipes[idx],
            "swipe_idx": idx, "swipes_count": len(swipes),
        })
        return

    # direction == "new"：重新生成变体
    pos = next(i for i, m in enumerate(msgs) if m.id == message_id)
    prefix = msgs[:pos]
    while prefix and prefix[-1].role != "user":
        prefix = prefix[:-1]  # 前缀必须停在 user（生成的提示）
    if not prefix:
        yield sse("error", {"kind": "swipe", "message": "这条回复前面没有可续的对话"})
        return

    last_user = prefix[-1].content if isinstance(prefix[-1].content, str) else "继续"
    app_settings = load_app_settings(store.data_root)
    ambient = (app_settings.ambient or {}) if app_settings.ambient else {}

    safety_prefix = ""
    safety_cfg = (app_settings.safety or {}) if app_settings.safety else {}
    if safety_cfg.get("enabled", True):
        from .policy import check_safety, safety_block

        hit = check_safety(last_user)
        if hit:
            safety_prefix = safety_block(hit) + "\n\n"

    req = ChatRequest(profile_id=profile_id, session_id=session_id, message=last_user, tier=tier)
    box: dict[str, Any] = {"engine": "none", "client": None, "full": [], "ran_tools": False}
    async for ev in _generate_reply(
        store, session_id, req, app_settings, ambient, safety_prefix,
        query=last_user, history=prefix, preassembled=None,
        enable_tools=False, box=box,
    ):
        yield ev

    variant = "".join(box["full"])
    if variant:
        swipes.append(variant)
        idx = len(swipes) - 1
        store.update_message(
            session_id, target.id, swipes=swipes, swipe_idx=idx, content=variant
        )
    yield sse("swipe", {
        "message_id": target.id, "content": variant or swipes[idx],
        "swipe_idx": idx, "swipes_count": len(swipes),
    })
    yield sse("message_end", {
        "engine": box["engine"], "chars": len(variant), "session_id": session_id,
    })


async def run_regen(
    profile_id: str,
    session_id: str,
    tier: str,
    store: ProfileStore,
) -> AsyncGenerator[str, None]:
    """重生成：以当前最后一条 user 消息为提示，续写一条新的 assistant 回复。

    用途：编辑消息（截断后续）之后重新走一轮生成。
    """
    msgs = store.recent_messages(session_id, limit=500)
    if not msgs or msgs[-1].role != "user":
        yield sse("error", {"kind": "regen", "message": "最后一条不是你的消息，没法续写"})
        return

    last_user = msgs[-1].content if isinstance(msgs[-1].content, str) else "继续"
    app_settings = load_app_settings(store.data_root)
    ambient = (app_settings.ambient or {}) if app_settings.ambient else {}

    req = ChatRequest(profile_id=profile_id, session_id=session_id, message=last_user, tier=tier)
    box: dict[str, Any] = {"engine": "none", "client": None, "full": [], "ran_tools": False}
    async for ev in _generate_reply(
        store, session_id, req, app_settings, ambient, "",
        query=last_user, history=msgs, preassembled=None,
        enable_tools=True, box=box,
    ):
        yield ev

    reply = "".join(box["full"])
    if reply:
        store.append_message(
            session_id,
            ChatMessage(
                role="assistant", content=reply,
                swipes=[reply], swipe_idx=0,
                device_time=clock.snapshot(),
            ),
        )
    yield sse("message_end", {
        "engine": box["engine"], "chars": len(reply), "session_id": session_id,
    })
