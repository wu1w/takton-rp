"""上下文守卫：token 估算 / 溢出识别 / 装配收缩。"""

import pytest

from nianxia_core.inference.router import ContextOverflowError, _is_overflow
from nianxia_core.memory.tokenmeter import (
    estimate_messages,
    estimate_tokens,
    token_budget,
)


# ---------- tokenmeter ----------

def test_estimate_cjk_vs_latin():
    # CJK 约 1.5 字符/token，密度高于拉丁（约 4 字符/token）
    cjk = estimate_tokens("你好世界你好世界")
    latin = estimate_tokens("abcdefghijklmnop")  # 同长 16 字符
    assert cjk > latin
    assert estimate_tokens("你好世界你好世界") == pytest.approx(8, abs=1)


def test_estimate_messages_overhead():
    msgs = [
        {"role": "system", "content": "你是角色"},
        {"role": "user", "content": "你好"},
    ]
    est = estimate_messages(msgs)
    assert est > estimate_tokens("你是角色") + estimate_tokens("你好")  # 含结构开销


def test_estimate_multimodal():
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "看图"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}]
    assert estimate_messages(msgs) >= 1024  # 图片按 1024 估


def test_token_budget_engines():
    assert token_budget("l0") == int(4096 * 0.85) - 800
    assert token_budget("l1") > token_budget("l0") * 10
    assert token_budget(None) == token_budget("l0")  # 兜底按 L0


# ---------- 溢出识别 ----------

@pytest.mark.parametrize("status,body,expect", [
    (400, '{"error":{"code":"context_length_exceeded"}}', True),
    (413, "request too large", True),
    (500, "llama: prompt exceeds the context size (n_ctx=4096)", True),
    (400, '{"error":"invalid api key"}', False),
    (401, "unauthorized", False),
    (500, "internal error", False),
])
def test_is_overflow(status, body, expect):
    assert _is_overflow(status, body) is expect


# ---------- L1 客户端溢出抛 ContextOverflowError ----------

@pytest.mark.anyio
async def test_l1_stream_raises_overflow():
    import httpx

    from nianxia_core.inference.router import L1CloudClient

    def handler(request):
        return httpx.Response(400, json={"error": {"code": "context_length_exceeded", "message": "too long"}})

    transport = httpx.MockTransport(handler)
    client = L1CloudClient("http://x/v1", "k", "m")
    orig = httpx.AsyncClient
    httpx.AsyncClient = lambda **kw: orig(transport=transport, **kw)  # noqa
    try:
        with pytest.raises(ContextOverflowError):
            async for _ in client.stream_events([{"role": "user", "content": "hi"}]):
                pass
    finally:
        httpx.AsyncClient = orig


# ---------- assemble scale 收缩 ----------

def test_assemble_scale_shrinks(tmp_path):
    from nianxia_core.memory.store import ProfileStore
    from nianxia_core.memory.assemble import assemble
    from nianxia_core.models import SessionSummary

    store = ProfileStore(tmp_path, "default")
    for i in range(10):
        store.add_fact(f"用户喜欢第{i}号东西" * 5, pinned=False)
    store.add_fact("用户对花粉过敏", pinned=True)
    sid = store.new_session_id()
    for i in range(3):
        store.add_summary(SessionSummary(
            session_id=sid, covers_upto=float(i + 1), text="之前聊过的话题" * 40,
        ))

    full = assemble(store, tier="L1", query="第3号")
    shrunk = assemble(store, tier="L1", query="第3号", scale=0.25)
    # 硬块不砍：policy/persona/pinned 必须在
    for needle in ("钉选记忆", "花粉过敏", "【人设】"):
        assert needle in shrunk["system"]
    # 软块收缩：整体明显变短
    assert len(shrunk["system"]) < len(full["system"]) * 0.7
