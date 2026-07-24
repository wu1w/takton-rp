"""Pydantic 数据模型（与 DATA_SCHEMA 对齐的骨架子集）。"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_ts() -> float:
    return time.time()


class PersonaIdentity(BaseModel):
    short: str = ""
    full: str = ""
    speech_style: list[str] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)
    greeting_style: str = ""


class Persona(BaseModel):
    schema_version: int = 1
    id: str
    name: str = "念念"
    created_at: float = Field(default_factory=now_ts)
    locked: bool = True
    identity: PersonaIdentity = Field(default_factory=PersonaIdentity)
    active_card_id: str | None = None  # 启用的角色卡；有卡时人设以卡为准


class LoreEntry(BaseModel):
    """设定书条目（酒馆 World Info 的精简版）：关键词触发的动态注入。

    Lite 取舍：只保留 触发词/内容/常驻/顺序/开关，砍掉互斥组/递归/概率等重机制。
    """

    schema_version: int = 1
    id: str = Field(default_factory=lambda: new_id("lore"))
    keys: list[str] = Field(default_factory=list)  # 触发词（命中任一即注入；大小写不敏感）
    content: str = ""  # 注入正文（自包含的一段设定）
    constant: bool = False  # 常驻：不看关键词每轮都注入
    order: int = 100  # 小的排前面（越靠后影响力越大）
    enabled: bool = True


class CharacterCard(BaseModel):
    """角色卡 — 兼容 chara_card_v2（猫箱/SillyTavern/Chub 生态可直接导入）。

    小白向字段名用中文注释对齐：description=人设描述 personality=性格
    scenario=场景 first_mes=开场白 mes_example=示例对话。
    """

    schema_version: int = 1
    spec: str = "chara_card_v2"
    id: str = Field(default_factory=lambda: new_id("card"))
    name: str
    avatar: str = ""  # media/cards/<id>.png 相对路径，可空
    description: str = ""  # 人设描述（背景/外貌/与世界的关系）
    personality: str = ""  # 性格关键词/段落
    scenario: str = ""  # 场景设定（故事背景/当下处境）
    first_mes: str = ""  # 开场白（新会话第一条角色消息）
    mes_example: str = ""  # 示例对话（{{user}}/{{char}} 占位符）
    system_prompt: str = ""  # 高级：追加的角色专属系统提示
    post_history_instructions: str = ""  # 作者备注：注入历史尾部
    creator_notes: str = ""
    tags: list[str] = Field(default_factory=list)
    alternate_greetings: list[str] = Field(default_factory=list)
    voice: str = ""  # 朗读音色（edge-tts voice id，空=默认晓晓）
    lorebook: list[LoreEntry] = Field(default_factory=list)  # 设定书 Lite（随卡走）
    # 生图锁脸：切换角色时跟随；优先 last_portrait，其次 avatar，再 face_prompt 文本锁
    face_prompt: str = ""  # 外貌锁提示词（中/英均可）；空则从 description 抽外貌句
    last_portrait: str = ""  # media/portraits/<card_id>_last.png 等相对路径
    source: Literal["builtin", "imported", "custom"] = "custom"
    created_at: float = Field(default_factory=now_ts)

    def render_vars(self, user_name: str = "你") -> "CharacterCard":
        """{{char}}/{{user}} 占位符替换（RP 社区约定）。"""
        def sub(s: str) -> str:
            return s.replace("{{char}}", self.name).replace("{{user}}", user_name)
        return self.model_copy(update={
            "description": sub(self.description),
            "personality": sub(self.personality),
            "scenario": sub(self.scenario),
            "first_mes": sub(self.first_mes),
            "mes_example": sub(self.mes_example),
            "post_history_instructions": sub(self.post_history_instructions),
        })


class Fact(BaseModel):
    schema_version: int = 1
    id: str = Field(default_factory=lambda: new_id("fact"))
    text: str
    pinned: bool = False
    source: Literal["user", "extracted", "system"] = "user"
    created_at: float = Field(default_factory=now_ts)
    superseded_by: str | None = None
    # 角色隔离：与启用的角色卡绑定；空=旧数据（加载时归入当时 active_card）
    card_id: str | None = None


class Bond(BaseModel):
    schema_version: int = 1
    stage: str = "初识"
    met_at: float = Field(default_factory=now_ts)
    last_session_at: float | None = None
    open_loops: list[dict[str, Any]] = Field(default_factory=list)


class ChatMessage(BaseModel):
    schema_version: int = 1
    id: str = Field(default_factory=lambda: new_id("msg"))
    role: Literal["user", "assistant", "system"]
    content: str
    ts: float = Field(default_factory=now_ts)
    device_time: dict[str, Any] | None = None
    # Swipes（借鉴酒馆）：assistant 回复的变体池；content 始终等于 swipes[swipe_idx]
    swipes: list[str] = []
    swipe_idx: int = 0


class Attachment(BaseModel):
    """对话附件：图片（走视觉）或文本文件（内联进上下文）。"""

    kind: Literal["image", "file"]
    name: str
    url: str  # /v1/media/uploads/<stored>（media_file 服务）
    text: str | None = None  # 文本附件的内联内容（上传时截断提取）


class ChatRequest(BaseModel):
    profile_id: str = "default"
    session_id: str | None = None
    message: str
    tier: Literal["L0", "L1", "L2"] = "L0"
    attachments: list[Attachment] = []


class SessionSummary(BaseModel):
    """一段会话的冷路径压缩摘要（append-only 存 summaries.jsonl）。"""

    schema_version: int = 1
    id: str = Field(default_factory=lambda: new_id("sum"))
    session_id: str
    covers_upto: float  # 覆盖到哪条消息的 ts（其前不再重复摘要）
    text: str
    engine: str = "l1"  # 生成它的引擎；无引擎时根本不会产生摘要
    created_at: float = Field(default_factory=now_ts)


class Epoch(BaseModel):
    """岁月年表的一段（封纪产物，epochs.jsonl append-only）。

    冷路径把已成往事的会话封存成一两句年表；
    封纪后不重复封（covers_to 游标），无引擎不封（不编造往事）。
    """

    schema_version: int = 1
    id: str = Field(default_factory=lambda: new_id("epoch"))
    covers_from: float
    covers_to: float
    text: str
    engine: str = "l1"
    created_at: float = Field(default_factory=now_ts)


class GrowthProposal(BaseModel):
    """他的领悟：冷路径策展出的软约定候选（growth.jsonl）。

    生命周期：pending →（用户确认）adopted /（拒绝）rejected。
    adopted 且 kind=soft_rule → 装配进【软约定】块。
    """

    schema_version: int = 1
    id: str = Field(default_factory=lambda: new_id("grow"))
    text: str
    kind: Literal["soft_rule", "fact"] = "soft_rule"
    status: Literal["pending", "adopted", "rejected"] = "pending"
    confidence: float = 0.5
    source_session_id: str = ""
    source_excerpt: str = ""  # 溯源：原对话片段（UI 可回看）
    created_at: float = Field(default_factory=now_ts)
    resolved_at: float | None = None
    card_id: str | None = None  # 角色隔离：软约定随角色走


class MediaEndpoint(BaseModel):
    preset_id: str = ""
    base_url: str = ""
    model: str = ""
    enabled: bool = False
    api_key_set: bool = False


class AppSettings(BaseModel):
    schema_version: int = 1
    memory: dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": True,
            "growth_enabled": True,
            "growth_daily_cap": 3,
        }
    )
    ambient: dict[str, Any] = Field(
        default_factory=lambda: {
            "mode": "real",
            "weather_enabled": True,
            "headlines_enabled": True,
            "device_time_enabled": True,
            "city": None,
        }
    )
    clock: dict[str, Any] = Field(
        default_factory=lambda: {"auto_sync": True, "apply_compensation": False}
    )
    media: dict[str, Any] = Field(
        default_factory=lambda: {
            "llm": MediaEndpoint().model_dump(),
            "image": MediaEndpoint().model_dump(),
            "tts": MediaEndpoint(preset_id="edge_tts", enabled=True).model_dump(),
        }
    )
    channels: dict[str, Any] = Field(
        default_factory=lambda: {"master_enabled": False, "allow_setup_tools": True}
    )
    safety: dict[str, Any] = Field(default_factory=lambda: {"enabled": True})
    wizard: dict[str, Any] = Field(default_factory=lambda: {"done": False})
