"""AI 代笔：一句话 → L0 扩写完整角色卡草稿。

- 冷路径 LLM（用户点按钮才跑），不碰聊天热路径
- L0 不可用/没装模型 → 如实报错，不编造草稿
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_DRAFT_KEYS = ("name", "description", "personality", "scenario", "first_mes", "mes_example")


def build_prompt(hint: str, name: str = "") -> str:
    name_line = f"角色名字已定：「{name}」。" if name.strip() else "顺便给她起个好听的两三字中文名。"
    return (
        "你是角色卡撰写助手。根据用户的一句话设定，写一张角色扮演卡。"
        f"{name_line}\n"
        "严格输出一个 JSON 对象（不要 markdown 代码块、不要任何其他文字），字段：\n"
        '{\n  "name": "角色名",\n  "description": "人设描述：外貌/身份/背景，150字内",\n'
        '  "personality": "性格：3-5个关键词+一句话说明",\n  "scenario": "场景：故事发生的地点和当下处境，80字内",\n'
        '  "first_mes": "开场白：她对用户说的第一句话，带一个括号动作描写，60字内",\n'
        '  "mes_example": "一段示例对话，{{user}}: 和 {{char}}: 两行"\n}\n'
        f"用户的一句话设定：{hint.strip()}"
    )


def parse_draft(text: str) -> dict[str, str]:
    """从模型输出提取卡草稿。三级容错：严格 JSON → 逐键正则 → 整段当人设。"""
    text = text.strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        raw = m.group(0)
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                out = {k: str(obj.get(k, "")).strip() for k in _DRAFT_KEYS}
                if any(out.values()):
                    return out
        except (json.JSONDecodeError, ValueError):
            pass
        # 小模型常把换行直接写进字符串 → 严格解析挂掉，逐键正则捞
        out: dict[str, str] = {}
        for k in _DRAFT_KEYS:
            km = re.search(rf'"{k}"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
            if km:
                out[k] = km.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
        if any(out.values()):
            return {k: out.get(k, "") for k in _DRAFT_KEYS}
    # 退化：全文进人设描述，别的字段留空
    return {k: "" for k in _DRAFT_KEYS} | {"description": text[:500]}


async def run_draft(data_root: Path, hint: str, name: str = "") -> dict[str, Any]:
    """调 L0 写草稿。返回 {ok, draft} 或 {ok: False, error}。"""
    from ..inference.l0 import L0Sidecar

    hint = hint.strip()
    if not hint:
        return {"ok": False, "error": "先写一句她的设定，哪怕几个字"}

    sidecar = L0Sidecar(data_root)
    if sidecar.find_model() is None:
        return {"ok": False, "error": "本地小模型还没安装（设置 · 怎么聊）"}
    if not sidecar.is_running() and not sidecar.start():
        return {"ok": False, "error": "本地小模型没跑起来，稍后再试"}

    import httpx

    try:
        async with httpx.AsyncClient(timeout=180.0) as c:
            r = await c.post(
                "http://127.0.0.1:7421/v1/chat/completions",
                json={
                    "model": "l0",
                    "messages": [{"role": "user", "content": build_prompt(hint, name)}],
                    "max_tokens": 1200,
                    "temperature": 0.8,
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            r.raise_for_status()
            msg = (r.json().get("choices") or [{}])[0].get("message", {})
            text = msg.get("content") or msg.get("reasoning_content") or ""
    except Exception as e:
        return {"ok": False, "error": f"代笔失败：{e}"}

    if not text.strip():
        return {"ok": False, "error": "小模型没写出东西，换个说法再试"}
    draft = parse_draft(text)
    if name.strip():  # 名字以用户填的为准
        draft["name"] = name.strip()
    return {"ok": True, "draft": draft}
