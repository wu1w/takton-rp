"""设置路由：app-settings 读写 + LLM Key（不回显）。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ...config import get_settings
from ...models import AppSettings
from ...runtime.store import (
    load_app_settings,
    save_app_settings,
    set_llm_api_key,
    get_llm_api_key,
)

router = APIRouter(prefix="/v1", tags=["settings"])


@router.get("/settings")
def read_settings() -> dict:
    s = load_app_settings(get_settings().data_root)
    data = s.model_dump()
    data["data_root"] = str(get_settings().data_root)
    data["media"]["llm"]["api_key_set"] = bool(get_llm_api_key(get_settings().data_root))
    return data


@router.put("/settings")
def write_settings(s: AppSettings) -> dict:
    save_app_settings(get_settings().data_root, s)
    return {"ok": True}


class LlmKeyIn(BaseModel):
    api_key: str


@router.post("/settings/llm-key")
def set_llm_key(body: LlmKeyIn) -> dict:
    set_llm_api_key(get_settings().data_root, body.api_key)
    return {"ok": True}
