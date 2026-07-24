"""Budget Assembler — PRD §5.3 装配优先级的骨架实现。

顺序（高→低，永不砍 1–4）：
1. 系统指令 + 安全策略
2. 核心 Persona + 硬规则/锁定
3. 钉选事实 + bond 核心
4. 设备时间块（运行时现场采样注入）
5. 近聊滑窗（走 messages，不进 system）
6. 摘要 + open loops
7. Ambient 背景（可空；骨架期不预取）
8. Epochs 纪略 + 非钉选活跃事实（最低，先砍）

热路径纯规则 + 读盘，无 LLM（延迟宪法 P11）。
"""

from __future__ import annotations

from typing import Any

from ..clock import clock
from ..models import CharacterCard
from .openloops import RECALL_GAP_SECONDS
from .recall import recall_relevant
from .store import ProfileStore

BASE_POLICY = (
    "你是念匣中的一个本地陪伴角色。你不是通用助手，不要暴露模型与厂商身份；"
    "不医疗诊断、不诱导依赖、尊重用户的硬规则；回答贴合人设短版。"
)


def assemble(
    store: ProfileStore,
    tier: str = "L0",
    query: str = "",
    include_device_time: bool = True,
    session_id: str | None = None,
    ambient: dict[str, Any] | None = None,
    scale: float = 1.0,
) -> dict[str, Any]:
    """装配 system 块。scale<1 时按优先级收缩软块（溢出重试用；1–4 硬块永不砍）。"""
    persona = store.load_persona()
    bond = store.load_bond()
    facts = store.list_facts()
    pinned = [f for f in facts if f.pinned]
    loose = [f for f in facts if not f.pinned]

    # 角色卡：有启用卡时，人设块以卡为准（兼容 chara_card_v2 占位符）
    card: CharacterCard | None = None
    raw_card: CharacterCard | None = None
    if persona.active_card_id:
        from ..runtime.cards import CardStore

        raw_card = CardStore(store.data_root).get(persona.active_card_id)
        if raw_card is not None:
            card = raw_card.render_vars(user_name="你")

    blocks: list[str] = []

    # 1 policy
    blocks.append(BASE_POLICY)

    # 2 persona + 硬规则（100% 必装）；有卡 → 卡人设+场景+示例+卡专属提示
    if card is not None:
        card_lines = [f"【角色】{card.name}"]
        if card.description:
            card_lines.append("人设：" + card.description)
        if card.personality:
            card_lines.append("性格：" + card.personality)
        card_lines.append("（严格保持此角色：不得漂移，不得暴露模型与厂商身份）")
        blocks.append("\n".join(card_lines))
        if card.scenario:
            blocks.append("【场景】\n" + card.scenario)
        if card.system_prompt:
            blocks.append(card.system_prompt)
    else:
        persona_lines = [f"【人设】{persona.name}"]
        if persona.identity.short:
            persona_lines.append(persona.identity.short)
        if persona.identity.speech_style:
            persona_lines.append("说话方式：" + "、".join(persona.identity.speech_style))
        if persona.identity.boundaries:
            persona_lines.append("硬规则（必须遵守）：" + "；".join(persona.identity.boundaries))
        if persona.locked:
            persona_lines.append("（人设已锁定：不得漂移，不得自行改写以上条目）")
        blocks.append("\n".join(persona_lines))

    # 3 钉选 + bond
    core_lines: list[str] = []
    if pinned:
        core_lines.append("【钉选记忆】（用户亲自钉下，永远优先）")
        core_lines.extend(f"- {f.text}" for f in pinned)
    core_lines.append(f"【关系】阶段：{bond.stage}")
    blocks.append("\n".join(core_lines))

    # 3.5 软约定（用户确认过的领悟；效力仅次于钉选；scale≤0.3 整砍）
    adopted = [
        g for g in store.list_growth(status="adopted") if g.kind == "soft_rule"
    ]
    if adopted and scale > 0.3:
        blocks.append(
            "【软约定】（用户确认过的相处方式，默认遵守）\n"
            + "\n".join(f"- {g.text}" for g in adopted[: max(1, int(6 * scale))])
        )

    # 4 设备时间（现场快照；日志与 prompt 同源；可在设置中关闭注入）
    snap = clock.snapshot()
    if include_device_time:
        blocks.append(clock.system_block())

    # 6 open loops（重逢承接：距上次会话 ≥6h 才注入，连聊不刷屏）
    import time as _time

    gap_ok = (
        bond.last_session_at is None
        or (_time.time() - bond.last_session_at) >= RECALL_GAP_SECONDS
    )
    loops = (
        [l for l in bond.open_loops if l.get("status", "open") == "open"]
        if gap_ok
        else []
    )
    if loops and scale > 0.5:
        blocks.append(
            "【未完话头】（自然承接，不要硬提）\n"
            + "\n".join(f"- {l.get('topic', '')}" for l in loops[:3])
        )

    # 6.5 氛围谈资（只读 cache；无 cache 绝不编造；可提可不提）
    ambient = ambient or {}
    if scale > 0.5 and (ambient.get("weather_enabled") or ambient.get("headlines_enabled")):
        from ..runtime.ambient import fresh_cache

        cache = fresh_cache(store.data_root)
        if cache:
            amb_lines: list[str] = []
            if ambient.get("weather_enabled") and cache.get("weather"):
                amb_lines.append(f"- 天气：{cache['weather']}")
            if ambient.get("headlines_enabled") and cache.get("headlines"):
                amb_lines.append("- 今日谈资：" + "；".join(cache["headlines"][:3]))
            if amb_lines:
                blocks.append(
                    "【氛围素材】（可提可不提，绝不硬塞；用户没兴趣就别说）\n"
                    + "\n".join(amb_lines)
                )

    # 6.2 前情摘要（冷路径产物；有才有，按档限量；scale≤0.3 整砍）
    summaries = store.list_summaries()
    if summaries and scale > 0.3:
        sum_budget = {"L0": (1, 300), "L1": (2, 500), "L2": (3, 800)}.get(tier, (1, 300))
        count, chars = sum_budget
        count = max(1, int(count * scale))
        chars = max(120, int(chars * scale))
        picked = sorted(summaries, key=lambda s: s.created_at, reverse=True)[:count]
        lines = []
        for s in reversed(picked):  # 旧→新排列
            text = s.text if len(s.text) <= chars else s.text[:chars] + "…"
            lines.append(f"- {text}")
        blocks.append("【前情摘要】（早前聊过的压缩记录）\n" + "\n".join(lines))

    # 6.3 岁月年表（封纪产物；最新一段；scale≤0.5 整砍）
    epochs = store.list_epochs()
    if epochs and scale > 0.5:
        blocks.append(f"【岁月年表】（你们共同走过的日子）\n- {epochs[-1].text}")

    # 6.5 唤起的相关记忆：本轮消息与旧记忆相关时注入（运行时按需，非每轮）
    recalled = []
    if query and scale > 0.3:
        recalled = recall_relevant(query, loose, lambda f: f.text, limit=max(1, int(3 * scale)))
        if recalled:
            blocks.append(
                "【唤起的相关记忆】（与当前话题相关，自然使用，不要背诵）\n"
                + "\n".join(f"- {f.text}" for f, _ in recalled)
            )

    # 6.6 设定书（卡内 lorebook：关键词命中或常驻注入；子串匹配适配中文；scale≤0.3 整砍）
    if raw_card is not None and raw_card.lorebook and scale > 0.3:
        scan = query or ""
        if session_id:
            try:
                scan += "\n" + "\n".join(
                    m.content
                    for m in store.recent_messages(session_id, limit=8)
                    if isinstance(m.content, str)
                )
            except Exception:
                pass  # 读历史失败不挡装配
        low = scan.casefold()
        hits = [
            e
            for e in raw_card.lorebook
            if e.enabled
            and e.content.strip()
            and (e.constant or any(k.strip() and k.casefold() in low for k in e.keys))
        ]
        if hits:
            hits.sort(key=lambda e: e.order)
            cap = max(1, int(5 * scale))
            blocks.append(
                "【设定书】（与当前话题相关的世界设定，自然使用，不要背诵）\n"
                + "\n".join(f"- {e.content}" for e in hits[:cap])
            )

    # 8 非钉选活跃事实（最低优先，先砍；scale≤0.3 整砍）
    loose_budget = {"L0": 4, "L1": 12, "L2": 20}.get(tier, 4)
    loose_budget = max(1, int(loose_budget * scale))
    if loose and scale > 0.3:
        blocks.append(
            "【记得的事】\n" + "\n".join(f"- {f.text}" for f in loose[:loose_budget])
        )

    return {
        "system": "\n\n".join(b for b in blocks if b.strip()),
        "device_time": snap,
        "card": card.model_dump() if card else None,
        # mes_example 返回原始占位符版本：渲染后 {{user}}/{{char}} 被替换会导致
        # companion 的 _parse_mes_example 解析不到 → few-shot 静默失效
        "mes_example": raw_card.mes_example if raw_card else "",
        "post_history_instructions": card.post_history_instructions if card else "",
        "memory_usage": {
            "pinned": len(pinned),
            "recalled": [f.id for f, _ in recalled],
            "loose_used": min(len(loose), loose_budget),
            "open_loops": len(loops),
        },
    }
