"""FastAPI 应用工厂 + 静态壳服务。"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import get_settings
from ..memory import ProfileStore
from ..runtime.store import load_app_settings
from ..storage import data_lock
from .routes import backup, cards, channels, chat, media, memory, settings as settings_route, system

logger = logging.getLogger("nianxia")


def create_app() -> FastAPI:
    cfg = get_settings()

    # 启动：建目录 + 默认角色 + 设置；单 writer 锁（网盘双开降损，拿不到锁仅告警）
    cfg.data_root.mkdir(parents=True, exist_ok=True)
    lock = data_lock(cfg.data_root)
    try:
        lock.acquire()
        logger.info("data lock acquired: %s", cfg.data_root)
    except Exception:
        logger.warning("另一个念匣实例可能正在使用同一数据目录：%s", cfg.data_root)

    ProfileStore(cfg.data_root, "default").load_persona()
    load_app_settings(cfg.data_root)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 通道任务（TG 长轮询）+ 氛围预取：随应用拉起，退出时回收
        import asyncio as _asyncio

        from ..channels.telegram import start_channel_tasks, stop_channel_tasks
        from ..runtime.ambient import ambient_loop

        await start_channel_tasks(cfg.data_root)
        amb_task = _asyncio.create_task(
            ambient_loop(
                cfg.data_root,
                lambda: (load_app_settings(cfg.data_root).ambient or {}),
            )
        )
        yield
        amb_task.cancel()
        await stop_channel_tasks()

    app = FastAPI(title="nianxia-core", version=__version__, lifespan=lifespan)

    # Tauri 壳（tauri://localhost / http://tauri.localhost）与 vite dev 跨源访问本机 core
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router)
    app.include_router(settings_route.router)
    app.include_router(memory.router)
    app.include_router(chat.router)
    app.include_router(backup.router)
    app.include_router(channels.router)
    app.include_router(media.router)
    app.include_router(cards.router)

    # 桌面壳静态服务（vite build 产物存在时直接由 core 托管）
    # __file__ = core/src/nianxia_core/api/app.py → parents[4] = 仓根
    dist = Path(__file__).resolve().parents[4] / "shells" / "desktop" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="shell")
        logger.info("serving desktop shell from %s", dist)

    @app.on_event("shutdown")
    def _release() -> None:
        try:
            lock.release()
        except Exception:
            pass

    return app


app = create_app()
