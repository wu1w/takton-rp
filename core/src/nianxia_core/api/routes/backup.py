"""备份与导出路由。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from ...backup import export_backup, export_memoir, import_backup, list_backups
from ...config import get_settings
from ...memory import ProfileStore

router = APIRouter(prefix="/v1", tags=["backup"])


class ExportIn(BaseModel):
    include_secrets: bool = False


@router.post("/backup/export")
def do_export(body: ExportIn) -> dict:
    out = export_backup(get_settings().data_root, include_secrets=body.include_secrets)
    return {"ok": True, "path": str(out), "size": out.stat().st_size}


@router.get("/backup/list")
def do_list() -> dict:
    return {"items": list_backups(get_settings().data_root)}


class ImportIn(BaseModel):
    path: str


@router.post("/backup/import")
def do_import(body: ImportIn) -> dict:
    result = import_backup(Path(body.path), get_settings().data_root)
    return result


@router.get("/profiles/{profile_id}/export/memoir")
def do_memoir(profile_id: str) -> dict:
    store = ProfileStore(get_settings().data_root, profile_id)
    out = export_memoir(store)
    return {"ok": True, "path": str(out), "size": out.stat().st_size}
