"""L0 模型下载器：HTTP 流式下载 + .part 断点续传 + 进度查询。

- 默认源：HF Qwen3.5-2B-GGUF Q5_K_M（可在请求里换 URL）
- 完成才改名 .part → .gguf，半截文件不会被当成模型
- 线程执行，状态内存可查；失败如实标 error，不假装完成
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import httpx

DEFAULT_MODEL_URL = (
    "https://huggingface.co/bartowski/Qwen_Qwen3.5-2B-GGUF/resolve/main/Qwen_Qwen3.5-2B-Q5_K_M.gguf"
)

_state: dict[str, Any] = {
    "status": "idle",  # idle/downloading/done/error/cancelled
    "done_bytes": 0,
    "total_bytes": 0,
    "filename": "",
    "error": "",
}
_cancel = threading.Event()
_thread: threading.Thread | None = None


def status() -> dict[str, Any]:
    return dict(_state)


def _reset(filename: str) -> None:
    _state.update(
        status="downloading", done_bytes=0, total_bytes=0, filename=filename, error=""
    )


def _download(data_root: Path, url: str, filename: str) -> None:
    models = data_root / "models"
    models.mkdir(parents=True, exist_ok=True)
    part = models / f"{filename}.part"
    final = models / filename

    headers = {}
    done = part.stat().st_size if part.exists() else 0
    if done:
        headers["Range"] = f"bytes={done}-"
    _reset(filename)
    _state["done_bytes"] = done

    try:
        with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=60.0) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0) + done
            _state["total_bytes"] = total
            mode = "ab" if done else "wb"
            with part.open(mode) as f:
                for chunk in r.iter_bytes(1024 * 256):
                    if _cancel.is_set():
                        _state["status"] = "cancelled"
                        return
                    f.write(chunk)
                    _state["done_bytes"] += len(chunk)
        part.rename(final)
        _state["status"] = "done"
    except Exception as e:
        _state["status"] = "error"
        _state["error"] = str(e)


def start(data_root: Path, url: str | None = None) -> dict[str, Any]:
    global _thread
    if _state.get("status") == "downloading":
        return {"ok": False, "error": "已有下载在进行"}
    url = (url or DEFAULT_MODEL_URL).strip()
    filename = url.rstrip("/").split("/")[-1] or "model.gguf"
    if not filename.endswith(".gguf"):
        filename += ".gguf"
    _cancel.clear()
    _reset(filename)  # 同步重置，避免竞态读到上一轮状态
    _thread = threading.Thread(target=_download, args=(data_root, url, filename), daemon=True)
    _thread.start()
    return {"ok": True, "filename": filename, "url": url}


def cancel() -> dict[str, Any]:
    _cancel.set()
    return {"ok": True}
