"""存储包：文件布局 + 单 writer 锁。"""

from __future__ import annotations

from pathlib import Path

from filelock import FileLock


def data_lock(data_root: Path) -> FileLock:
    """网盘双开降损：同一 data_root 只允许一个活跃 writer。"""
    data_root.mkdir(parents=True, exist_ok=True)
    return FileLock(str(data_root / ".nianxia.lock"), timeout=0)
