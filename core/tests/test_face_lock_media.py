"""生图锁脸 + media_io 媒体抽出（不连真 Comfy）。"""

import base64

import httpx

from nianxia_core.inference.image import (
    assemble_locked_prompt,
    face_lock_text,
    generate_image,
    resolve_backend,
)
from nianxia_core.models import CharacterCard
from nianxia_core.channels.media_io import (
    extract_outbound_media,
    save_inbound_bytes,
)
from nianxia_core.runtime.cards import CardStore


def test_resolve_backend_comfy():
    assert resolve_backend({"backend": "comfy"}) == "comfy"
    assert resolve_backend({"base_url": "http://192.168.1.10:8188"}) == "comfy"
    assert resolve_backend({"base_url": "https://api.openai.com/v1", "model": "x"}) == "openai"


def test_face_lock_switches_with_card():
    a = CharacterCard(name="阿九", face_prompt="银发狐耳少女，桃花眼")
    b = CharacterCard(name="念念", description="黑发短发程序员御姐")
    assert "银发" in face_lock_text(a)
    assert "阿九" in face_lock_text(a)
    assert "念念" in face_lock_text(b)
    pa, _, ra = assemble_locked_prompt("海边散步", a)
    pb, _, _ = assemble_locked_prompt("海边散步", b)
    assert "银发" in pa and "阿九" in pa
    assert "念念" in pb
    assert pa != pb
    assert ra == ""


def test_generate_openai_still_works(tmp_path):
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nfakepng").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"b64_json": png}]})

    c = httpx.Client(transport=httpx.MockTransport(handler))
    card = CharacterCard(id="card_t1", name="测试", face_prompt="红发双马尾")
    CardStore(tmp_path).save(card)
    r = generate_image(
        tmp_path,
        {"base_url": "https://x.test/v1", "model": "m", "backend": "openai"},
        "教室窗边",
        client=c,
        card=card,
        face_lock=True,
    )
    assert r["ok"] and r.get("face_lock") is True
    assert (tmp_path / r["path"]).exists()
    # last_portrait 回写
    live = CardStore(tmp_path).get("card_t1")
    assert live and live.last_portrait.startswith("media/portraits/")


def test_media_io_inbound_outbound(tmp_path):
    att = save_inbound_bytes(tmp_path, b"\x89PNG\r\n\x1a\nxx", filename="a.png", kind_hint="image")
    assert att and att.kind == "image"
    # 写入假成图
    (tmp_path / "media").mkdir(exist_ok=True)
    p = tmp_path / "media" / "out.png"
    p.write_bytes(b"\x89PNG")
    text, files = extract_outbound_media(f"画好了\nMEDIA:media/out.png", tmp_path)
    assert "画好了" in text
    assert files and files[0].name == "out.png"
