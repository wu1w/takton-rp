"""app-settings 与密钥读取（骨架：密钥文件 secrets/llm.key，后续接 keyring）。"""

from __future__ import annotations

from pathlib import Path

from ..models import AppSettings
from ..storage.files import read_json, write_json


def settings_path(data_root: Path) -> Path:
    return Path(data_root) / "app-settings.json"


def load_app_settings(data_root: Path) -> AppSettings:
    raw = read_json(settings_path(data_root))
    if raw:
        return AppSettings(**raw)
    s = AppSettings()
    save_app_settings(data_root, s)
    return s


def save_app_settings(data_root: Path, s: AppSettings) -> None:
    write_json(settings_path(data_root), s.model_dump())


def get_llm_api_key(data_root: Path) -> str | None:
    p = Path(data_root) / "secrets" / "llm.key"
    if p.exists():
        key = p.read_text(encoding="utf-8").strip()
        return key or None
    return None


def set_llm_api_key(data_root: Path, key: str) -> None:
    p = Path(data_root) / "secrets" / "llm.key"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(key.strip(), encoding="utf-8")
