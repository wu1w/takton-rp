"""TTS 实际调用（M11）：edge-tts（免 Key，走微软服务）。

未安装 edge-tts 或网络失败 → 如实报错，不返回假音频。
"""

from __future__ import annotations

import time
from pathlib import Path


async def synthesize(
    data_root: Path, text: str, voice: str = "zh-CN-XiaoxiaoNeural"
) -> dict:
    try:
        import edge_tts
    except ImportError:
        return {"ok": False, "error": "未安装 edge-tts（core 目录 uv pip install edge-tts）"}

    text = text.strip()[:600]
    if not text:
        return {"ok": False, "error": "文本为空"}
    out_dir = data_root / "media"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"tts-{int(time.time())}.mp3"
    try:
        await edge_tts.Communicate(text, voice).save(str(out))
    except Exception as e:
        return {"ok": False, "error": f"朗读失败：{e}"}
    return {"ok": True, "path": f"media/{out.name}"}
