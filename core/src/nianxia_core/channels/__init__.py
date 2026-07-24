"""消息通道公共助手：通道→profile 绑定（方案 A）。

每个通道可在 settings.channels.<key>.profile_id 绑定独立 profile
（各有独立 persona/活跃卡/记忆）；缺省回落 default（跟随 App）。
"""

from __future__ import annotations

from pathlib import Path

from ..runtime.store import load_app_settings

CHANNEL_KEYS = ("onebot", "telegram", "qqbot", "weixin")


def bound_profile_id(data_root: Path, channel_key: str, fallback: str = "default") -> str:
    """该通道生效的 profile：配置里有绑定用绑定，否则回落 fallback（default=跟随 App）。"""
    cfg = (load_app_settings(data_root).channels or {}).get(channel_key) or {}
    pid = cfg.get("profile_id")
    return pid.strip() if isinstance(pid, str) and pid.strip() else fallback


def display_name(data_root: Path, profile_id: str) -> str:
    """群聊 @ 匹配用的名字：profile 有活跃卡用卡名，否则 persona 名。"""
    from ..memory import ProfileStore
    from ..runtime.cards import CardStore

    persona = ProfileStore(data_root, profile_id).load_persona()
    if persona.active_card_id:
        card = CardStore(data_root).get(persona.active_card_id)
        if card:
            return card.name
    return persona.name
