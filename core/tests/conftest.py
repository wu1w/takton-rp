"""测试引导：把 src 注入 sys.path。

背景：Windows GBK 环境下 editable install 的 .pth 若含中文路径
（如 E:\\项目\\...）会被 site 静默跳过，导致 nianxia_core 不可导入。
这里直接注入，保证任何机器上 pytest 都能跑。
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
