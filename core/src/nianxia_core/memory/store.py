"""ProfileStore — 每角色物理隔离的 json/jsonl 读写（PRD M9）。"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ..models import Bond, ChatMessage, Epoch, Fact, GrowthProposal, Persona, SessionSummary
from ..storage.files import (
    append_jsonl,
    atomic_write,
    ensure_layout,
    read_json,
    read_jsonl,
    sessions_dir,
    write_json,
)

DEFAULT_PROFILE_ID = "default"
# 无角色卡时的「默认陪伴」会话 / 记忆命名空间
PERSONA_SCOPE = "__persona__"


def session_id_for_card(card_id: str | None) -> str:
    """一个角色（卡）对应唯一会话 id（猫箱模型：角色=会话）。"""
    if not card_id:
        return f"ses_{PERSONA_SCOPE}"
    # card_id 形如 card_xxx → ses_card_xxx
    return f"ses_{card_id}"


class ProfileStore:
    def __init__(self, data_root: Path, profile_id: str = DEFAULT_PROFILE_ID):
        self.data_root = Path(data_root)
        self.profile_id = profile_id
        self.dir = ensure_layout(self.data_root, profile_id)

    # ---------- persona ----------
    @property
    def persona_path(self) -> Path:
        return self.dir / "persona.json"

    def load_persona(self) -> Persona:
        raw = read_json(self.persona_path)
        if raw:
            return Persona(**raw)
        persona = Persona(id=self.profile_id)
        self.save_persona(persona)
        return persona

    def save_persona(self, persona: Persona) -> None:
        write_json(self.persona_path, persona.model_dump())

    def active_card_id(self) -> str | None:
        return self.load_persona().active_card_id

    def memory_scope(self, card_id: str | None | object = ...) -> str:
        """记忆/软约定的隔离键。默认=当前启用卡；无卡 → PERSONA_SCOPE。"""
        if card_id is ...:
            card_id = self.active_card_id()
        return card_id or PERSONA_SCOPE

    # ---------- facts ----------
    @property
    def facts_path(self) -> Path:
        return self.dir / "facts.jsonl"

    def _migrate_orphan_facts(self, scope: str) -> None:
        """旧数据无 card_id：一次性归入首次触达时的启用角色，避免串角。"""
        marker = self.dir / ".facts_card_scoped"
        if marker.exists():
            return
        rows = read_jsonl(self.facts_path)
        if not any(not r.get("card_id") for r in rows):
            marker.write_text(scope, encoding="utf-8")
            return
        for r in rows:
            if not r.get("card_id"):
                r["card_id"] = scope
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        atomic_write(self.facts_path, text)
        marker.write_text(scope, encoding="utf-8")

    def list_facts(
        self,
        include_superseded: bool = False,
        card_id: str | None | object = ...,
    ) -> list[Fact]:
        scope = self.memory_scope(card_id)
        # 只在「按当前启用角色」路径做孤儿迁移，避免旁路 card_id 抢绑
        if card_id is ...:
            self._migrate_orphan_facts(scope)
        facts = [Fact(**r) for r in read_jsonl(self.facts_path)]
        facts = [f for f in facts if (f.card_id or PERSONA_SCOPE) == scope]
        if not include_superseded:
            facts = [f for f in facts if f.superseded_by is None]
        return facts

    def add_fact(
        self,
        text: str,
        pinned: bool = False,
        source: str = "user",
        card_id: str | None | object = ...,
    ) -> Fact:
        scope = self.memory_scope(card_id)
        cid = None if scope == PERSONA_SCOPE else scope
        fact = Fact(text=text, pinned=pinned, source=source, card_id=cid)  # type: ignore[arg-type]
        append_jsonl(self.facts_path, fact.model_dump())
        return fact

    def search_facts(
        self,
        query: str,
        limit: int = 8,
        card_id: str | None | object = ...,
    ) -> list[Fact]:
        q = query.strip().lower()
        if not q:
            return []
        hits = [f for f in self.list_facts(card_id=card_id) if q in f.text.lower()]
        return hits[:limit]

    def _rewrite_facts(self, facts: list[Fact]) -> None:
        text = "".join(
            __import__("json").dumps(f.model_dump(), ensure_ascii=False) + "\n"
            for f in facts
        )
        from ..storage.files import atomic_write

        atomic_write(self.facts_path, text)

    def set_pinned(self, fact_id: str, pinned: bool) -> bool:
        facts = [Fact(**r) for r in read_jsonl(self.facts_path)]
        found = False
        for f in facts:
            if f.id == fact_id:
                f.pinned = pinned
                found = True
        if found:
            self._rewrite_facts(facts)
        return found

    def supersede_fact(self, fact_id: str, by: str = "user_deleted") -> bool:
        """软删除：标记 superseded（append-only 语义的骨架实现为改写标记）。"""
        facts = [Fact(**r) for r in read_jsonl(self.facts_path)]
        found = False
        for f in facts:
            if f.id == fact_id and f.superseded_by is None:
                f.superseded_by = by
                found = True
        if found:
            self._rewrite_facts(facts)
        return found

    # ---------- growth（他的领悟） ----------
    @property
    def growth_path(self) -> Path:
        return self.dir / "growth.jsonl"

    def _migrate_orphan_growth(self, scope: str) -> None:
        marker = self.dir / ".growth_card_scoped"
        if marker.exists():
            return
        rows = read_jsonl(self.growth_path)
        if not any(not r.get("card_id") for r in rows):
            marker.write_text(scope, encoding="utf-8")
            return
        for r in rows:
            if not r.get("card_id"):
                r["card_id"] = scope
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        atomic_write(self.growth_path, text)
        marker.write_text(scope, encoding="utf-8")

    def list_growth(
        self,
        status: str | None = None,
        card_id: str | None | object = ...,
    ) -> list[GrowthProposal]:
        scope = self.memory_scope(card_id)
        if card_id is ...:
            self._migrate_orphan_growth(scope)
        items = [GrowthProposal(**r) for r in read_jsonl(self.growth_path)]
        items = [g for g in items if (g.card_id or PERSONA_SCOPE) == scope]
        if status:
            items = [g for g in items if g.status == status]
        return items

    def add_growth(self, g: GrowthProposal) -> GrowthProposal:
        if not g.card_id:
            scope = self.memory_scope()
            g.card_id = None if scope == PERSONA_SCOPE else scope
        append_jsonl(self.growth_path, g.model_dump())
        return g

    def set_growth_status(self, growth_id: str, status: str) -> bool:
        import time

        items = [GrowthProposal(**r) for r in read_jsonl(self.growth_path)]
        found = False
        for g in items:
            if g.id == growth_id and g.status == "pending":
                g.status = status  # type: ignore[assignment]
                g.resolved_at = time.time()
                found = True
        if found:
            text = "".join(
                json.dumps(g.model_dump(), ensure_ascii=False) + "\n"
                for g in items
            )
            atomic_write(self.growth_path, text)
        return found

    def growth_count_today(self, card_id: str | None | object = ...) -> int:
        import time

        day_start = time.time() - (time.time() % 86400)
        return sum(1 for g in self.list_growth(card_id=card_id) if g.created_at >= day_start)

    # ---------- sessions（角色=会话） ----------
    def session_path(self, session_id: str) -> Path:
        return sessions_dir(self.data_root, self.profile_id) / f"{session_id}.jsonl"

    def resolve_chat_session_id(self, card_id: str | None | object = ...) -> str:
        """当前应打开的会话 id（无则创建并可选写入开场白）。"""
        if card_id is ...:
            card_id = self.active_card_id()
        sid = session_id_for_card(card_id if isinstance(card_id, str) or card_id is None else None)
        path = self.session_path(sid)
        if not path.exists():
            self._seed_card_session(sid, card_id if isinstance(card_id, str) else None)
        return sid

    def _seed_card_session(self, session_id: str, card_id: str | None) -> str:
        """新建角色会话：有开场白则落第一条 assistant。返回 greeting。"""
        greeting = ""
        path = self.session_path(session_id)
        if card_id:
            try:
                from ..runtime.cards import CardStore

                card = CardStore(self.data_root).get(card_id)
                if card and card.first_mes:
                    greeting = card.render_vars(user_name="你").first_mes
                    self.append_message(
                        session_id, ChatMessage(role="assistant", content=greeting)
                    )
                    return greeting
            except Exception:
                pass
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        return greeting

    def get_or_create_card_session(self, card_id: str | None) -> dict[str, Any]:
        """启用角色时用：返回 session_id + 是否新建 + greeting。"""
        sid = session_id_for_card(card_id)
        path = self.session_path(sid)
        created = not path.exists()
        greeting = ""
        if created:
            greeting = self._seed_card_session(sid, card_id)
        else:
            msgs = self.recent_messages(sid, limit=1)
            if msgs and msgs[0].role == "assistant":
                greeting = msgs[0].content
        return {"session_id": sid, "created": created, "greeting": greeting}

    def latest_session_id(self) -> str | None:
        """兼容旧接口：返回当前启用角色的会话（总会创建）。"""
        return self.resolve_chat_session_id()

    def list_sessions(self) -> list[dict[str, Any]]:
        """会话列表（新→旧）。角色模型下主要给搜索/调试用。"""
        import re

        out: list[dict[str, Any]] = []
        paths = sorted(
            (self.dir / "sessions").glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for p in paths:
            rows = read_jsonl(p)
            first_user = next((r for r in rows if r.get("role") == "user"), None)
            content = (first_user or {}).get("content") or ""
            if isinstance(content, list):
                content = " ".join(
                    seg.get("text", "")
                    for seg in content
                    if isinstance(seg, dict) and seg.get("type") == "text"
                )
            clean = re.sub(r"\[(?:图片|文件|语音|视频)\][^\[]*", "", str(content))
            clean = re.sub(r"\s+", " ", clean).strip()
            stem = p.stem
            card_id = None
            if stem.startswith("ses_card_"):
                card_id = stem[len("ses_"):]  # ses_card_xxx → card_xxx
            elif stem == f"ses_{PERSONA_SCOPE}":
                card_id = None
            out.append(
                {
                    "session_id": stem,
                    "card_id": card_id,
                    "updated_at": p.stat().st_mtime,
                    "msg_count": len(rows),
                    "preview": clean[:30],
                }
            )
        return out

    def delete_session(self, session_id: str) -> bool:
        p = self.session_path(session_id)
        if p.exists():
            p.unlink()
            return True
        return False

    # ---------- summaries（会话压缩摘要） ----------
    @property
    def summaries_path(self) -> Path:
        return self.dir / "summaries.jsonl"

    def list_summaries(self) -> list[SessionSummary]:
        return [SessionSummary(**r) for r in read_jsonl(self.summaries_path)]

    def add_summary(self, s: SessionSummary) -> SessionSummary:
        append_jsonl(self.summaries_path, s.model_dump())
        return s

    def summary_covered_upto(self, session_id: str) -> float:
        """该会话已摘要覆盖到的 ts；之后的消息才是未压缩区。"""
        return max(
            (s.covers_upto for s in self.list_summaries() if s.session_id == session_id),
            default=0.0,
        )

    # ---------- bond ----------
    @property
    def bond_path(self) -> Path:
        return self.dir / "bond.json"

    def load_bond(self) -> Bond:
        raw = read_json(self.bond_path)
        if raw:
            return Bond(**raw)
        bond = Bond()
        self.save_bond(bond)
        return bond

    def save_bond(self, bond: Bond) -> None:
        write_json(self.bond_path, bond.model_dump())

    def add_open_loop(self, loop: dict) -> None:
        bond = self.load_bond()
        bond.open_loops.append(loop)
        self.save_bond(bond)

    def close_open_loop(self, loop_id: str) -> bool:
        bond = self.load_bond()
        for l in bond.open_loops:
            if l.get("id") == loop_id and l.get("status", "open") == "open":
                l["status"] = "completed"
                self.save_bond(bond)
                return True
        return False

    # ---------- epochs（岁月年表） ----------
    @property
    def epochs_path(self) -> Path:
        return self.dir / "epochs.jsonl"

    def list_epochs(self) -> list[Epoch]:
        return [Epoch(**r) for r in read_jsonl(self.epochs_path)]

    def add_epoch(self, e: Epoch) -> Epoch:
        append_jsonl(self.epochs_path, e.model_dump())
        return e

    def epoch_covered_upto(self) -> float:
        epochs = self.list_epochs()
        return max((e.covers_to for e in epochs), default=0.0)

    def append_message(self, session_id: str, msg: ChatMessage) -> None:
        append_jsonl(self.session_path(session_id), msg.model_dump())

    def recent_messages(self, session_id: str, limit: int = 12) -> list[ChatMessage]:
        rows = read_jsonl(self.session_path(session_id))
        return [ChatMessage(**r) for r in rows[-limit:]]

    def update_message(self, session_id: str, message_id: str, **fields: Any) -> ChatMessage | None:
        """按 id 更新消息字段（swipes/content 等），整文件重写。"""
        path = self.session_path(session_id)
        rows = read_jsonl(path)
        updated: ChatMessage | None = None
        for i, r in enumerate(rows):
            if r.get("id") == message_id:
                r.update(fields)
                rows[i] = r
                updated = ChatMessage(**r)
                break
        if updated is None:
            return None
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8",
        )
        return updated

    def truncate_after(self, session_id: str, message_id: str) -> int:
        """删除 message_id 之后的所有消息（不含自身）；返回删除条数。"""
        path = self.session_path(session_id)
        rows = read_jsonl(path)
        idx = next((i for i, r in enumerate(rows) if r.get("id") == message_id), None)
        if idx is None:
            return 0
        kept = rows[: idx + 1]
        removed = len(rows) - len(kept)
        if removed:
            path.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept),
                encoding="utf-8",
            )
        return removed

    @staticmethod
    def new_session_id() -> str:
        return f"ses_{uuid.uuid4().hex[:12]}"


def list_profiles(data_root: Path) -> list[dict[str, Any]]:
    root = Path(data_root) / "profiles"
    if not root.exists():
        return []
    out = []
    for p in sorted(root.iterdir()):
        if p.is_dir():
            raw = read_json(p / "persona.json") or {}
            out.append({"id": p.name, "name": raw.get("name", p.name)})
    return out


def touch_bond(store: ProfileStore) -> None:
    bond = store.load_bond()
    bond.last_session_at = time.time()
    store.save_bond(bond)
