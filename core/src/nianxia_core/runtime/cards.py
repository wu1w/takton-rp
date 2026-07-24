"""角色卡库：CRUD + chara_card_v2 导入导出（PNG tEXt / JSON）。

存储：data_root/cards/<id>.json；头像 data_root/media/cards/<id>.png。
导入兼容：
- PNG 角色卡（SillyTavern/Chub 格式）：tEXt chunk keyword="chara"，base64 JSON
- JSON：v2（{"spec": "chara_card_v2", "data": {...}}）或 v1 平铺
"""

from __future__ import annotations

import base64
import json
import logging
import struct
import zlib
from pathlib import Path
from typing import Any

from ..models import CharacterCard
from ..storage.files import read_json, write_json

logger = logging.getLogger(__name__)


class CardStore:
    def __init__(self, data_root: Path):
        self.root = data_root / "cards"
        self.root.mkdir(parents=True, exist_ok=True)
        self.media_dir = data_root / "media" / "cards"
        self.media_dir.mkdir(parents=True, exist_ok=True)

    # ---------- CRUD ----------
    def _path(self, card_id: str) -> Path:
        return self.root / f"{card_id}.json"

    def list(self) -> list[CharacterCard]:
        cards = []
        for p in sorted(self.root.glob("*.json")):
            raw = read_json(p)
            if raw:
                try:
                    cards.append(CharacterCard(**raw))
                except Exception as e:  # 坏卡不拖垮整个库
                    logger.warning("坏卡跳过 %s: %s", p.name, e)
        return cards

    def get(self, card_id: str) -> CharacterCard | None:
        raw = read_json(self._path(card_id))
        return CharacterCard(**raw) if raw else None

    def save(self, card: CharacterCard) -> CharacterCard:
        write_json(self._path(card.id), card.model_dump())
        return card

    def delete(self, card_id: str) -> bool:
        p = self._path(card_id)
        avatar = self.media_dir / f"{card_id}.png"
        ok = p.exists()
        p.unlink(missing_ok=True)
        avatar.unlink(missing_ok=True)
        return ok

    def save_avatar(self, card_id: str, data: bytes) -> str:
        """存头像，返回 media 相对路径。"""
        (self.media_dir / f"{card_id}.png").write_bytes(data)
        return f"media/cards/{card_id}.png"

    # ---------- 导入 ----------
    def import_card(self, data: bytes, filename: str) -> CharacterCard:
        """PNG（含头像）或 JSON → 落库卡。"""
        lower = filename.lower()
        if lower.endswith(".png") or data[:8] == b"\x89PNG\r\n\x1a\n":
            payload, avatar_png = parse_card_png(data)
            card = card_from_payload(payload, source="imported")
            if avatar_png:
                card.avatar = self.save_avatar(card.id, avatar_png)
        else:
            payload = json.loads(data.decode("utf-8"))
            card = card_from_payload(payload, source="imported")
        return self.save(card)

    def export_card(self, card_id: str) -> dict[str, Any] | None:
        """导出 chara_card_v2 标准 JSON。"""
        card = self.get(card_id)
        if card is None:
            return None
        d = card.model_dump()
        d.pop("id", None)
        d.pop("avatar", None)
        d.pop("source", None)
        d.pop("created_at", None)
        d.pop("schema_version", None)
        return {"spec": "chara_card_v2", "spec_version": "2.0", "data": d}


def card_from_payload(payload: dict[str, Any], source: str = "imported") -> CharacterCard:
    """v2（包 data）或 v1 平铺 → CharacterCard。未知字段忽略。"""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    fields = {k: v for k, v in data.items() if k in CharacterCard.model_fields and k not in ("id", "spec")}
    if not fields.get("name"):
        raise ValueError("角色卡缺少 name")
    return CharacterCard(**fields, source=source)  # type: ignore[arg-type]


def parse_card_png(data: bytes) -> tuple[dict[str, Any], bytes]:
    """解析 PNG tEXt chunk 中的 chara（base64 JSON）。返回 (payload, 原图bytes)。"""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG 文件")
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        if ctype == b"tEXt":
            keyword, _, text = chunk.partition(b"\x00")
            if keyword == b"chara":
                payload = json.loads(base64.b64decode(text).decode("utf-8"))
                return payload, data
        pos += 12 + length  # length + type + data + crc
        if ctype == b"IEND":
            break
    raise ValueError("这张 PNG 里没有角色卡数据（缺少 chara 块）")


def build_card_png(card: CharacterCard, png_bytes: bytes) -> bytes:
    """把卡 JSON 注入 PNG（tEXt chara chunk，插到 IEND 前）——供导出 PNG 卡。"""
    payload = {"spec": "chara_card_v2", "spec_version": "2.0",
               "data": card.model_dump(exclude={"id", "avatar", "source", "created_at", "schema_version"})}
    b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    text_chunk = b"chara\x00" + b64
    chunk = struct.pack(">I", len(text_chunk)) + b"tEXt" + text_chunk
    chunk += struct.pack(">I", zlib.crc32(b"tEXt" + text_chunk) & 0xFFFFFFFF)
    iend_pos = data_find_iend(png_bytes)
    return png_bytes[:iend_pos] + chunk + png_bytes[iend_pos:]


def data_find_iend(data: bytes) -> int:
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        if data[pos + 4 : pos + 8] == b"IEND":
            return pos
        pos += 12 + length
    raise ValueError("PNG 缺少 IEND")


# ---------- 内置默认卡（产品内容，开箱即有） ----------
BUILTIN_CARD = CharacterCard(
    id="card_builtin_default",
    name="念念",
    description=(
        "念念是住在念匣里的本地陪伴角色。她的世界就是这台电脑和与你的对话；"
        "没有联网、没有别的身份，记得你说过的每一件小事。"
    ),
    personality="温柔、知性、耐心；对外话少得体，对熟悉的人放松爱聊；诚实，做不到的事会直说。",
    scenario="你在自己的电脑上打开了念匣，念念在屏幕那头陪你度过日常。",
    first_mes="（屏幕亮起，她抬起头，眼里带笑）你来啦。今天过得怎么样？",
    mes_example="{{user}}: 今天好累\n{{char}}: （轻轻靠过来）辛苦啦。先喝口水，慢慢说，我在听。",
    tags=["陪伴", "温柔", "默认"],
    source="builtin",
)


def ensure_builtin(store: CardStore) -> None:
    """首启写内置卡（不覆盖用户改动）。"""
    if store.get(BUILTIN_CARD.id) is None:
        store.save(BUILTIN_CARD)
