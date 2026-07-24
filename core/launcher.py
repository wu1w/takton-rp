"""PyInstaller 入口：直接传 app 对象（字符串导入对静态分析不可见）。"""

import uvicorn

from nianxia_core.api.app import app
from nianxia_core.config import get_settings

if __name__ == "__main__":
    cfg = get_settings()
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")
