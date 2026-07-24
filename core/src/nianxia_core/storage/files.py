"""数据目录布局与原子写入。

data_root/
  app-settings.json
  profiles/<id>/
    persona.json
    facts.jsonl
    bond.json
    growth.jsonl
    epochs.jsonl
    sessions/<session_id>.jsonl
  _cache/
  .nianxia.lock
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def profile_dir(data_root: Path, profile_id: str) -> Path:
    return data_root / "profiles" / profile_id


def sessions_dir(data_root: Path, profile_id: str) -> Path:
    return profile_dir(data_root, profile_id) / "sessions"


def ensure_layout(data_root: Path, profile_id: str) -> Path:
    p = profile_dir(data_root, profile_id)
    (p / "sessions").mkdir(parents=True, exist_ok=True)
    (data_root / "_cache").mkdir(parents=True, exist_ok=True)
    return p


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path: Path, obj: Any) -> None:
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


def read_jsonl(path: Path) -> list[Any]:
    if not path.exists():
        return []
    out: list[Any] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
