"""画图/TTS 实际调用（MockTransport 注入，不发真网）。"""

import base64

import httpx

from nianxia_core.inference.image import generate_image
from nianxia_core.inference.tts import synthesize

PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfakepng").decode()


def mock_client(payload, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_image_b64_saved(tmp_path):
    c = mock_client({"data": [{"b64_json": PNG_B64}]})
    r = generate_image(tmp_path, {"base_url": "https://x.test/v1", "model": "m"}, "a cat", client=c)
    assert r["ok"] is True
    saved = tmp_path / r["path"]
    assert saved.exists() and saved.read_bytes().startswith(b"\x89PNG")


def test_image_url_downloaded(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "images/generations" in str(request.url):
            return httpx.Response(200, json={"data": [{"url": "https://cdn.test/x.png"}]})
        return httpx.Response(200, content=b"\x89PNG-url-img")

    c = httpx.Client(transport=httpx.MockTransport(handler))
    r = generate_image(tmp_path, {"base_url": "https://x.test/v1", "model": "m"}, "a dog", client=c)
    assert r["ok"] and (tmp_path / r["path"]).read_bytes() == b"\x89PNG-url-img"
    assert any("cdn.test" in u for u in calls)


def test_image_unconfigured_and_error(tmp_path):
    r = generate_image(tmp_path, {}, "a cat")
    assert r["ok"] is False and "未配置" in r["error"]

    c = mock_client({"error": "bad key"}, status=401)
    r2 = generate_image(tmp_path, {"base_url": "https://x.test/v1", "model": "m"}, "x", client=c)
    assert r2["ok"] is False and "画图失败" in r2["error"]
    assert not list((tmp_path / "media").glob("*")) if (tmp_path / "media").exists() else True


def test_tts_empty_text(tmp_path):
    import asyncio

    r = asyncio.run(synthesize(tmp_path, "   "))
    assert r["ok"] is False and "为空" in r["error"]
