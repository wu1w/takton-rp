"""氛围预取（D0）：天气/谈资 cache。

硬闸（P7-B）：
- 热路径只读 cache，绝不联网；
- 无 cache / cache 过期 → 装配不注入，绝不编造天气谈资；
- 后台任务每 30 分钟刷新（仅当开关开着）；
- must_mention=false：注入文案明确「可提可不提，不要硬塞」。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TTL_SECONDS = 30 * 60
_REFRESH_INTERVAL = 30 * 60


def cache_path(data_root: Path) -> Path:
    d = data_root / "_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / "ambient.json"


def read_cache(data_root: Path) -> dict[str, Any] | None:
    p = cache_path(data_root)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_cache(data_root: Path, data: dict[str, Any]) -> None:
    cache_path(data_root).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fresh_cache(data_root: Path) -> dict[str, Any] | None:
    """未过期才返回；过期等同没有。"""
    c = read_cache(data_root)
    if not c:
        return None
    if time.time() - float(c.get("fetched_at", 0)) > TTL_SECONDS:
        return None
    return c


async def fetch_weather(city: str) -> str | None:
    """wttr.in 免 key。失败返回 None（绝不编造）。"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                f"https://wttr.in/{city}",
                params={"format": "j1"},
                headers={"User-Agent": "nianxia/0.1"},
            )
            r.raise_for_status()
            cur = r.json()["current_condition"][0]
            desc = (cur.get("lang_zh") or [{}])[0].get("value") or cur["weatherDesc"][0]["value"]
            return f"{city}：{desc}，{cur['temp_C']}°C，体感 {cur['FeelsLikeC']}°C，湿度 {cur['humidity']}%"
    except Exception as e:
        logger.info("weather fetch failed: %s", e)
        return None


async def fetch_headlines() -> list[str]:
    """百度热搜 RSS → 前 5 条标题。失败返回 []。"""
    try:
        import re

        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get("https://rsshub.app/baidu/top", headers={"User-Agent": "nianxia/0.1"})
            r.raise_for_status()
            titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", r.text)
            if not titles:
                titles = re.findall(r"<title>(.*?)</title>", r.text)
            return [t.strip() for t in titles[1:6] if t.strip()]
    except Exception as e:
        logger.info("headlines fetch failed: %s", e)
        return []


async def refresh_once(data_root: Path, ambient_cfg: dict[str, Any]) -> dict[str, Any]:
    """按开关刷新一次；只写真实抓到的数据。"""
    data: dict[str, Any] = {"fetched_at": time.time()}
    if ambient_cfg.get("weather_enabled"):
        city = str(ambient_cfg.get("weather_city") or "上海")
        w = await fetch_weather(city)
        if w:
            data["weather"] = w
    if ambient_cfg.get("headlines_enabled"):
        h = await fetch_headlines()
        if h:
            data["headlines"] = h
    write_cache(data_root, data)
    return data


async def ambient_loop(data_root: Path, get_cfg) -> None:
    """后台刷新循环（get_cfg() 返回最新 ambient 配置）。"""
    while True:
        try:
            cfg = get_cfg() or {}
            if cfg.get("weather_enabled") or cfg.get("headlines_enabled"):
                await refresh_once(data_root, cfg)
        except Exception as e:
            logger.warning("ambient refresh failed: %s", e)
        await asyncio.sleep(_REFRESH_INTERVAL)
