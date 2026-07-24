"""全局设置与 data_root 解析。

多平台纪律（技术手册 §6）：
- 业务代码禁止写死盘符/家目录；统一走这里。
- 角色数据真源在「用户可见」的 Documents/念匣（可改到网盘目录）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import platformdirs
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIRNAME = "念匣"


def default_data_root() -> Path:
    try:
        docs = Path(platformdirs.user_documents_path())
    except Exception:
        docs = Path.home() / "Documents"
    return docs / APP_DIRNAME


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NIANXIA_")

    app_name: str = "nianxia-core"
    host: str = "127.0.0.1"
    port: int = 7420
    data_root: Path = default_data_root()
    # L0 sidecar（Qwen3.5-2B llama-server）；骨架期仅记录路径
    l0_base_url: str = "http://127.0.0.1:7421"
    # 局域网开放：默认仅 loopback（手册 X7）
    allow_lan: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
