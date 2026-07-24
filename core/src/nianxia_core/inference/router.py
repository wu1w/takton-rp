"""InferenceRouter — L0/L1/L2 骨架。

- L1：OpenAI-compatible 云（httpx，媒体设置 media.llm 配好后生效），支持 tools
- L0：Qwen3.5-2B llama-server sidecar（骨架期：未启动则走占位回复）
- L2：Ollama 探测（骨架期仅接口预留）
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import httpx


class ChatEvent(dict):
    """{type: delta|tool_calls|finish|error, ...}"""


class ContextOverflowError(Exception):
    """prompt 超过引擎上下文窗口（HTTP 400/413/500 且报文命中溢出特征）。"""


_OVERFLOW_HINTS = (
    "context_length", "prompt_too_long", "maximum context", "context size",
    "n_ctx", "too many tokens", "exceed", "context window", "request too large",
)


def _is_overflow(status: int, body: str) -> bool:
    if status not in (400, 413, 422, 500):
        return False
    low = body.lower()
    return any(h in low for h in _OVERFLOW_HINTS)


class L1CloudClient:
    """OpenAI-compatible 流式客户端（Takton 血缘的薄重写，支持 tools）。"""

    engine_name = "l1"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def complete(
        self, messages: list[dict[str, Any]], max_tokens: int = 400
    ) -> str:
        """非流式一次性补全（冷路径摘要/Growth 用，不进热路径）。"""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": 0.3,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            if resp.status_code >= 400:
                body = resp.text[:500]
                if _is_overflow(resp.status_code, body):
                    raise ContextOverflowError(body)
            resp.raise_for_status()
            data = resp.json()
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    async def stream_events(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        # tool_calls 累加器：index → {id, name, arguments}
        tc_acc: dict[int, dict[str, Any]] = {}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "ignore")[:500]
                    if _is_overflow(resp.status_code, body):
                        raise ContextOverflowError(body)
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}: {body[:200]}",
                        request=resp.request, response=resp,
                    )
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield {"type": "delta", "text": content}
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = tc_acc.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                    finish = choices[0].get("finish_reason")
                    if finish == "tool_calls":
                        break

        if tc_acc:
            calls = []
            for idx in sorted(tc_acc):
                slot = tc_acc[idx]
                try:
                    args = json.loads(slot["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                calls.append(
                    {"id": slot["id"], "name": slot["name"], "args": args,
                     "raw_arguments": slot["arguments"]}
                )
            yield {"type": "tool_calls", "calls": calls}
        else:
            yield {"type": "finish"}


def l1_from_media_settings(media: dict[str, Any], api_key: str | None) -> L1CloudClient | None:
    llm = media.get("llm") or {}
    base = llm.get("base_url") or ""
    model = llm.get("model") or ""
    if base and model and api_key:
        return L1CloudClient(base, api_key, model)
    return None
