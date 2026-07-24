"""python -m nianxia_core — 启动 core。"""

from __future__ import annotations

import uvicorn

from .config import get_settings


def main() -> None:
    cfg = get_settings()
    uvicorn.run(
        "nianxia_core.api.app:app",
        host=cfg.host,
        port=cfg.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
