"""后端包下载器：下载 → sha256 校验 → 解压到 vendor/llama/<backend>/ → 写 backend.json。

- manifest 锁死 llama_tag + 每资产 sha256（backend_manifest.json，发版纪律对齐 Takton）
- 流式下载 + .part 防半截；sha 不符必报错（不装来路不明的二进制）
- CUDA 两个资产（本体+cudart）合并解压到同一目录
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import tarfile
import threading
import time
import zipfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

MANIFEST_PATH = Path(__file__).parent / "backend_manifest.json"
_state: dict[str, dict] = {}
_lock = threading.Lock()
_CHUNK = 1024 * 1024


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _sys_key() -> str:
    return {"Windows": "windows", "Darwin": "darwin"}.get(platform.system(), "windows")


def pack_status(backend: str | None = None) -> dict:
    with _lock:
        if backend:
            return dict(_state.get(backend) or {"state": "idle"})
        return {b: dict(s) for b, s in _state.items()}


def _set(backend: str, **kw) -> None:
    with _lock:
        _state.setdefault(backend, {}).update(kw)


def _download_one(url: str, part: Path, backend: str, offset_base: int, total_all: int) -> int:
    """下载单资产到 .part，返回字节数。全局进度按 offset_base+done 报。"""
    done = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    with httpx.stream("GET", url, follow_redirects=True, timeout=120, headers=headers) as r:
        r.raise_for_status()
        mode = "ab" if done else "wb"
        with part.open(mode) as f:
            for chunk in r.iter_bytes(_CHUNK):
                f.write(chunk)
                done += len(chunk)
                _set(backend, bytes_done=offset_base + done, bytes_total=total_all)
    return done


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                # 防 zip-slip
                target = (dest / info.filename).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise ValueError(f"unsafe path in archive: {info.filename}")
            z.extractall(dest)
    else:  # .tar.gz
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="data")


def _install_pack(vendor_root: Path, backend: str) -> None:
    manifest = load_manifest()
    spec = manifest["backends"].get(backend, {}).get(_sys_key())
    if not spec:
        raise RuntimeError(f"后端 {backend} 在本平台（{_sys_key()}）没有资产")

    tmp = vendor_root / "_dl"
    tmp.mkdir(parents=True, exist_ok=True)
    dest = vendor_root / "llama" / backend

    total_all = 0  # 先下载，content-length 逐个累加不现实；用完成后累计
    done_all = 0
    archives: list[tuple[Path, str, str]] = []  # (path, sha, name)
    for a in spec:
        part = tmp / (a["name"] + ".part")
        final = tmp / a["name"]
        if final.exists() and _sha256(final) == a["sha256"]:
            logger.info("asset cached: %s", a["name"])
        else:
            _set(backend, state="downloading", current=a["name"])
            _download_one(a["url"], part, backend, done_all, total_all)
            part.replace(final)
            if _sha256(final) != a["sha256"]:
                final.unlink(missing_ok=True)
                raise RuntimeError(f"{a['name']} sha256 校验失败（已删除，请重试）")
        size = final.stat().st_size
        done_all += size
        total_all = done_all
        archives.append((final, a["sha256"], a["name"]))

    _set(backend, state="extracting")
    if dest.exists():
        import shutil

        shutil.rmtree(dest)
    for archive, _, _ in archives:
        _extract(archive, dest)

    (dest / "backend.json").write_text(
        json.dumps(
            {
                "backend": backend,
                "llama_tag": manifest["llama_tag"],
                "installed_at": int(time.time()),
                "assets": [{"name": n, "sha256": s} for _, s, n in archives],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    _set(backend, state="done", bytes_done=done_all, bytes_total=done_all)


def start_pack_download(vendor_root: Path, backend: str) -> dict:
    cur = pack_status(backend).get("state")
    if cur == "downloading" or cur == "extracting":
        return {"ok": False, "error": "该后端正在下载中"}
    _set(backend, state="downloading", bytes_done=0, bytes_total=0, error=None, current=None)

    def run() -> None:
        try:
            _install_pack(vendor_root, backend)
        except Exception as e:  # 如实报错，不假装装好
            logger.error("backend pack %s failed: %s", backend, e)
            _set(backend, state="error", error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "backend": backend}
