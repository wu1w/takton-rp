"""备份 · 恢复 · 回忆读本。

- 导出：data_root → zip + manifest.json（默认剥离 secrets/）
- 恢复：校验 manifest（应用名/schema 版本）后解包覆盖
- 回忆读本：markdown，封面（名+相识天+轮次）+ 钉选 + 软约定 + 按会话正文
"""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from typing import Any

from . import __version__
from .memory import ProfileStore

SCHEMA_VERSION = 1


def _manifest(data_root: Path, include_secrets: bool) -> dict[str, Any]:
    profiles_dir = data_root / "profiles"
    profiles = sorted(p.name for p in profiles_dir.iterdir() if p.is_dir()) if profiles_dir.exists() else []
    return {
        "app": "nianxia",
        "schema_version": SCHEMA_VERSION,
        "core_version": __version__,
        "created_at": time.time(),
        "profiles": profiles,
        "include_secrets": include_secrets,
    }


def export_backup(data_root: Path, include_secrets: bool = False) -> Path:
    out_dir = data_root / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"nianxia-backup-{stamp}.zip"

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(_manifest(data_root, include_secrets), ensure_ascii=False, indent=2))
        for p in sorted(data_root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(data_root)
            if rel.parts[0] in ("backups", "_cache", "exports"):
                continue
            if rel.parts[0] == "secrets" and not include_secrets:
                continue
            if p.name == ".nianxia.lock":
                continue
            z.write(p, str(rel))
    return out


def list_backups(data_root: Path) -> list[dict[str, Any]]:
    out_dir = data_root / "backups"
    if not out_dir.exists():
        return []
    return [
        {"name": p.name, "path": str(p), "size": p.stat().st_size, "created_at": p.stat().st_mtime}
        for p in sorted(out_dir.glob("nianxia-backup-*.zip"), key=lambda x: x.stat().st_mtime, reverse=True)
    ]


def import_backup(zip_path: Path, data_root: Path) -> dict[str, Any]:
    """校验 manifest 后解包覆盖。非法包直接拒绝。"""
    with zipfile.ZipFile(zip_path) as z:
        try:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        except (KeyError, json.JSONDecodeError):
            return {"ok": False, "error": "这不是念匣备份包（缺 manifest）"}
        if manifest.get("app") != "nianxia":
            return {"ok": False, "error": "manifest 应用名不符"}
        if int(manifest.get("schema_version", 0)) > SCHEMA_VERSION:
            return {"ok": False, "error": "备份来自更新的版本，请升级念匣后再恢复"}
        data_root.mkdir(parents=True, exist_ok=True)
        for name in z.namelist():
            if name == "manifest.json":
                continue
            # 防 zip-slip
            target = (data_root / name).resolve()
            if not str(target).startswith(str(data_root.resolve())):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))
    return {"ok": True, "profiles": manifest.get("profiles", [])}


def export_memoir(store: ProfileStore) -> Path:
    """回忆读本 markdown（真实数据，无粉饰）。"""
    import datetime as dt

    persona = store.load_persona()
    bond = store.load_bond()
    facts = store.list_facts()
    pinned = [f for f in facts if f.pinned]
    adopted = [g for g in store.list_growth(status="adopted")]
    summaries = store.list_summaries()

    met_days = max(1, int((time.time() - bond.met_at) // 86400) + 1)
    sessions = store.list_sessions()
    total_msgs = sum(s["msg_count"] for s in sessions)

    lines = [
        f"# 与 {persona.name} 的回忆",
        "",
        f"> 相识第 {met_days} 天 · {len(sessions)} 段会话 · {total_msgs} 条消息",
        f"> 导出于 {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "## 他一直记得的事",
        "",
    ]
    if pinned:
        lines += [f"- {f.text}" for f in pinned]
    else:
        lines.append("（还没有钉选记忆）")
    lines += ["", "## 他确认过的相处约定", ""]
    if adopted:
        lines += [f"- {g.text}" for g in adopted]
    else:
        lines.append("（还没有确认过的约定）")

    if summaries:
        lines += ["", "## 前情摘要", ""]
        for s in summaries:
            day = dt.datetime.fromtimestamp(s.created_at).strftime("%Y-%m-%d")
            lines.append(f"- （{day}）{s.text}")

    lines += ["", "---", "", "## 会话记录", ""]
    for s in sessions:
        day = dt.datetime.fromtimestamp(s["updated_at"]).strftime("%Y-%m-%d %H:%M")
        lines += ["", f"### {day}（{s['msg_count']} 条）", ""]
        for m in store.recent_messages(s["session_id"], limit=10_000):
            who = "我" if m.role == "user" else persona.name
            lines.append(f"**{who}**：{m.content}")
            lines.append("")

    out_dir = store.data_root / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"memoir-{persona.name}-{time.strftime('%Y%m%d-%H%M%S')}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
