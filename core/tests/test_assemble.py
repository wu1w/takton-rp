"""装配：优先级顺序 + 永不砍项 + 设备时间。"""

from nianxia_core.memory import ProfileStore, assemble


def make_store(tmp_path):
    store = ProfileStore(tmp_path, "default")
    persona = store.load_persona()
    persona.name = "念念"
    persona.identity.short = "23 岁，外冷内软"
    persona.identity.boundaries = ["不医疗诊断", "不剧透"]
    store.save_persona(persona)
    store.add_fact("住在杭州", pinned=True)
    store.add_fact("喜欢短回复", pinned=False)
    return store


def test_assemble_order_and_never_cut(tmp_path):
    store = make_store(tmp_path)
    result = assemble(store, tier="L0")
    system = result["system"]

    # 永不砍 1–4 全部在场
    assert "【人设】念念" in system
    assert "硬规则（必须遵守）" in system and "不医疗诊断" in system
    assert "【钉选记忆】" in system and "住在杭州" in system
    assert "【设备时间·实时】" in system
    assert "【关系】" in system

    # 顺序：policy < persona < 钉选 < 时间
    idx = [
        system.index("你是念匣"),
        system.index("【人设】"),
        system.index("【钉选记忆】"),
        system.index("【设备时间·实时】"),
    ]
    assert idx == sorted(idx), f"装配顺序错误: {idx}"

    # 日志同源快照
    assert "iso" in result["device_time"]


def test_loose_facts_limited_by_tier(tmp_path):
    store = make_store(tmp_path)
    for i in range(10):
        store.add_fact(f"普通记忆{i}", pinned=False)
    l0 = assemble(store, tier="L0")
    assert l0["memory_usage"]["loose_used"] == 4  # L0 预算紧


def test_recall_on_query(tmp_path):
    """聊到记过的内容时，唤起相关记忆块。"""
    store = make_store(tmp_path)
    store.add_fact("用户对花粉过敏", pinned=False)
    hit = assemble(store, tier="L0", query="晚上吃花粉相关的东西怎么样")
    assert "【唤起的相关记忆】" in hit["system"]
    assert "花粉过敏" in hit["system"]
    assert hit["memory_usage"]["recalled"]

    miss = assemble(store, tier="L0", query="今天天气怎么样")
    assert "【唤起的相关记忆】" not in miss["system"]
