"""L0 本地小模型 sidecar：Qwen3.5-2B via llama-server。

- 模型发现：data_root/models/*.gguf（主模型）+ 可选 *mmproj*.gguf（视觉）
- 二进制发现：环境变量 NIANXIA_LLAMA_SERVER > PATH llama-server > 仓内 vendor/
- 端口：7421（core 7420 邻居），只绑 127.0.0.1
- 本类只做真实发现与进程管理；没有模型/二进制就如实报 not_installed
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

L0_PORT = 7421


def vendor_root() -> Path:
    """vendor/ 根目录：冻结（PyInstaller/Tauri 安装态）取 exe 同级，开发态取仓根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "vendor"
    return Path(__file__).resolve().parents[4] / "vendor"


class L0Sidecar:
    def __init__(self, data_root: Path):
        self.models_dir = data_root / "models"
        self._proc: subprocess.Popen | None = None
        self._candidates: list[str] | None = None

    # ---------- 发现 ----------
    def find_model(self) -> Path | None:
        if not self.models_dir.exists():
            return None
        ggufs = sorted(self.models_dir.glob("*.gguf"), key=lambda p: p.stat().st_size, reverse=True)
        mains = [g for g in ggufs if "mmproj" not in g.name.lower()]
        return mains[0] if mains else None

    def find_mmproj(self) -> Path | None:
        if not self.models_dir.exists():
            return None
        for g in self.models_dir.glob("*.gguf"):
            if "mmproj" in g.name.lower():
                return g
        return None

    def candidates(self) -> list[str]:
        """后端候选链（探测排序，末位 cpu）。"""
        from .gpudetect import backend_candidates, detect_gpu_names

        if self._candidates is None:
            self._candidates = backend_candidates(detect_gpu_names())
        return self._candidates

    def _vendor_binary(self, backend: str) -> str | None:
        vendor = vendor_root() / "llama" / backend
        for cand in (vendor / "llama-server.exe", vendor / "llama-server"):
            if cand.exists():
                return str(cand)
        return None

    def find_binary(self) -> tuple[str, str] | tuple[None, None]:
        """返回 (binary_path, backend)。优先级：环境变量 > vendor候选链 > PATH(cpu)。"""
        env = os.environ.get("NIANXIA_LLAMA_SERVER")
        if env and Path(env).exists():
            return env, "env"
        for backend in self.candidates():
            found = self._vendor_binary(backend)
            if found:
                return found, backend
        found = shutil.which("llama-server")
        if found:
            return found, "cpu"
        return None, None

    # ---------- 状态 ----------
    def status(self) -> dict[str, Any]:
        model = self.find_model()
        binary, backend = self.find_binary()
        return {
            "installed": bool(model and binary),
            "backend": backend,
            "candidates": self.candidates(),
            "model_path": str(model) if model else None,
            "mmproj_path": str(self.find_mmproj()) if self.find_mmproj() else None,
            "binary": binary,
            "running": self.is_running(),
            "port": L0_PORT,
        }

    def is_running(self) -> bool:
        try:
            r = httpx.get(f"http://127.0.0.1:{L0_PORT}/health", timeout=1.5)
            return r.status_code == 200
        except Exception:
            return False

    # ---------- 生命周期 ----------
    _GPU_BACKENDS = {"cuda", "hip", "rocm", "sycl", "vulkan", "metal"}

    def _try_start(self, binary: str, backend: str, ctx: int) -> bool:
        model = self.find_model()
        if not model:
            return False
        args = [
            binary,
            "--model", str(model),
            "--host", "127.0.0.1",
            "--port", str(L0_PORT),
            "--ctx-size", str(ctx),
            "--flash-attn", "on",
        ]
        if backend in self._GPU_BACKENDS:
            args += ["--n-gpu-layers", "99"]
        mmproj = self.find_mmproj()
        if mmproj:
            args += ["--mmproj", str(mmproj)]
        logger.info("starting L0 sidecar[%s]: %s", backend, " ".join(args))
        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # 就绪等待（最长 60s，大模型加载慢）
        import time

        deadline = time.time() + 60
        while time.time() < deadline:
            if self._proc.poll() is not None:
                logger.error("llama-server[%s] exited early: %s", backend, self._proc.returncode)
                return False
            if self.is_running():
                self._active_backend = backend
                return True
            time.sleep(0.5)
        self.stop()
        return False

    def start(self, ctx: int = 4096) -> bool:
        """按候选链逐级试：启动失败自动降级（CUDA→HIP→SYCL→Vulkan→CPU）。"""
        if self.is_running():
            return True
        if not self.find_model():
            return False

        tried: list[str] = []
        env = os.environ.get("NIANXIA_LLAMA_SERVER")
        if env and Path(env).exists():
            return self._try_start(env, "env", ctx)

        for backend in self.candidates():
            binary = self._vendor_binary(backend)
            if not binary:
                continue
            tried.append(backend)
            if self._try_start(binary, backend, ctx):
                logger.info("L0 up on backend=%s (tried: %s)", backend, tried)
                return True
            logger.warning("backend %s failed, falling back…", backend)

        found = shutil.which("llama-server")
        if found:
            return self._try_start(found, "cpu", ctx)
        logger.error("no usable llama-server (tried: %s)", tried)
        return False

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None


class L0Client:
    """指向本地 sidecar 的 OpenAI-compatible 客户端（与 L1 同协议）。"""

    engine_name = "l0"

    def __init__(self, port: int = L0_PORT, timeout: float = 120.0):
        from .router import L1CloudClient

        self._inner = L1CloudClient(
            base_url=f"http://127.0.0.1:{port}/v1", api_key="local", model="l0", timeout=timeout
        )

    async def stream_events(self, messages, tools=None):
        async for ev in self._inner.stream_events(messages, tools=tools):
            yield ev

    async def complete(self, messages, max_tokens=400):
        return await self._inner.complete(messages, max_tokens=max_tokens)


_sidecar: L0Sidecar | None = None


def get_sidecar(data_root: Path) -> L0Sidecar:
    global _sidecar
    if _sidecar is None or _sidecar.models_dir != data_root / "models":
        _sidecar = L0Sidecar(data_root)
    return _sidecar
