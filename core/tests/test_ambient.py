"""氛围预取：cache 读写 / TTL 过期 / 装配硬闸（无 cache 不注入）。"""

import time

from nianxia_core.memory import ProfileStore, assemble
from nianxia_core.runtime.ambient import fresh_cache, read_cache, write_cache


def test_cache_ttl(tmp_path):
    assert read_cache(tmp_path) is None
    write_cache(tmp_path, {"fetched_at": time.time(), "weather": "上海：晴，25°C"})
    assert fresh_cache(tmp_path)["weather"].startswith("上海")

    # 过期等同没有
    write_cache(tmp_path, {"fetched_at": time.time() - 3600, "weather": "上海：晴，25°C"})
    assert fresh_cache(tmp_path) is None


def test_assemble_injects_only_fresh_cache(tmp_path):
    store = ProfileStore(tmp_path, "default")
    ambient = {"weather_enabled": True, "headlines_enabled": True}

    # 无 cache → 不注入（硬闸：不编造）
    a = assemble(store, ambient=ambient)
    assert "【氛围素材】" not in a["system"]

    # 有新鲜 cache → 注入
    write_cache(
        tmp_path,
        {"fetched_at": time.time(), "weather": "上海：多云，22°C", "headlines": ["新闻一", "新闻二"]},
    )
    a2 = assemble(store, ambient=ambient)
    assert "【氛围素材】" in a2["system"]
    assert "多云" in a2["system"]
    assert "新闻一" in a2["system"]

    # 开关关掉 → 即使有 cache 也不注入
    a3 = assemble(store, ambient={"weather_enabled": False, "headlines_enabled": False})
    assert "【氛围素材】" not in a3["system"]

    # cache 过期 → 不注入
    write_cache(tmp_path, {"fetched_at": time.time() - 3600, "weather": "旧天气"})
    a4 = assemble(store, ambient=ambient)
    assert "【氛围素材】" not in a4["system"]
