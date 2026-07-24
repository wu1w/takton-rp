"""系统路由：health / clock。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ... import __version__
from ...clock import clock
from ...config import get_settings

router = APIRouter(prefix="/v1", tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "schema_version": 1}


@router.get("/clock")
def clock_now() -> dict:
    return clock.snapshot()


@router.get("/engine/status")
def engine_status() -> dict:
    """引擎真实状态：L0 sidecar（模型/二进制/运行中）+ L1（是否配好）。"""
    from ...inference import get_sidecar
    from ...runtime.store import get_llm_api_key, load_app_settings

    root = get_settings().data_root
    l0 = get_sidecar(root).status()
    media = load_app_settings(root).media or {}
    llm = media.get("llm") or {}
    l1_ready = bool(
        llm.get("base_url") and llm.get("model") and get_llm_api_key(root)
    )
    return {
        "l0": l0,
        "l1": {
            "configured": l1_ready,
            "base_url": llm.get("base_url") or "",
            "model": llm.get("model") or "",
        },
    }


class L0DownloadIn(BaseModel):
    url: str | None = None


@router.post("/engine/l0/download")
def l0_download(body: L0DownloadIn) -> dict:
    from ...inference.downloader import start

    return start(get_settings().data_root, body.url)


@router.get("/engine/l0/download/status")
def l0_download_status() -> dict:
    from ...inference.downloader import status

    return status()


@router.post("/engine/l0/download/cancel")
def l0_download_cancel() -> dict:
    from ...inference.downloader import cancel

    return cancel()


# ---------- L0 后端包（CUDA/HIP/SYCL/Vulkan/CPU/Metal，manifest 锁 sha256） ----------
@router.post("/engine/l0/backend/{backend}")
def l0_backend_install(backend: str) -> dict:
    from fastapi import HTTPException

    from ...inference.backend_packs import load_manifest, start_pack_download
    from ...inference.l0 import vendor_root

    if backend not in load_manifest()["backends"]:
        raise HTTPException(status_code=400, detail=f"未知后端: {backend}")
    return start_pack_download(vendor_root(), backend)


@router.get("/engine/l0/backend/status")
def l0_backend_status() -> dict:
    from ...inference.backend_packs import pack_status
    from ...inference.l0 import vendor_root

    installed = []
    vdir = vendor_root() / "llama"
    if vdir.exists():
        installed = [p.name for p in vdir.iterdir() if p.is_dir() and (p / "backend.json").exists()]
    return {"packs": pack_status(), "installed": installed}
