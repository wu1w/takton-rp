"""角色卡：CRUD / 导入（PNG tEXt + JSON v1v2）/ 启用注入装配 / 开场白。"""

import struct
import zlib

import pytest
from fastapi.testclient import TestClient

from nianxia_core.api.app import app
from nianxia_core.models import CharacterCard
from nianxia_core.runtime.cards import BUILTIN_CARD, CardStore, build_card_png
from nianxia_core.runtime.companion import _parse_mes_example


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from nianxia_core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "data_root", tmp_path)
    return TestClient(app), tmp_path


def _chunk(ctype: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + ctype + payload + struct.pack(
        ">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF
    )


def _minimal_png() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + _chunk(b"IEND", b"")


def test_builtin_card_and_crud(env):
    c, _ = env
    r = c.get("/v1/cards")
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["id"] == BUILTIN_CARD.id and i["name"] == "念念" for i in items)

    r = c.post("/v1/cards", json={"name": "狐仙阿九", "description": "千年狐仙，爱打趣",
                                  "scenario": "山间茶馆", "first_mes=": ""} | {"first_mes": "（摇扇）客官里面请～"})
    assert r.status_code == 200
    cid = r.json()["id"]

    r = c.put(f"/v1/cards/{cid}", json={"name": "狐仙阿九", "personality": "狡黠温柔"})
    assert r.json()["personality"] == "狡黠温柔"

    r = c.delete(f"/v1/cards/{cid}")
    assert r.json()["ok"] is True
    assert c.get(f"/v1/cards/{cid}").status_code == 404


def test_import_json_v2_and_v1(env):
    c, _ = env
    v2 = {"spec": "chara_card_v2", "data": {"name": " imported姬 ", "description": "d", "first_mes": "hi {{user}}"}}
    r = c.post("/v1/cards/import", files={"file": ("a.json", __import__("json").dumps(v2), "application/json")})
    assert r.status_code == 200 and r.json()["source"] == "imported"

    v1 = {"name": "旧版卡", "personality": "冷"}
    r = c.post("/v1/cards/import", files={"file": ("b.json", __import__("json").dumps(v1), "application/json")})
    assert r.status_code == 200 and r.json()["name"] == "旧版卡"


def test_import_png_card_roundtrip(env):
    c, tmp = env
    card = CharacterCard(name="PNG卡娘", description="从 PNG 来", first_mes="（探头）")
    png = build_card_png(card, _minimal_png())
    r = c.post("/v1/cards/import", files={"file": ("card.png", png, "image/png")})
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "PNG卡娘" and d["avatar_url"].startswith("/v1/media/file?rel=media/cards/")
    # 头像真落盘可取
    rel = d["avatar_url"].split("rel=", 1)[-1]
    assert c.get(f"/v1/media/file?rel={rel}").status_code == 200


def test_import_garbage_honest(env):
    c, _ = env
    r = c.post("/v1/cards/import", files={"file": ("x.png", b"not-a-png", "image/png")})
    assert r.status_code == 400


def test_active_card_injects_into_assembly(env):
    c, tmp = env
    c.post("/v1/cards", json={
        "name": "剑客无名", "description": "沉默的浪人", "personality": "寡言",
        "scenario": "雪夜破庙", "system_prompt": "永远以剑喻人",
    })
    cid = [i for i in c.get("/v1/cards").json()["items"] if i["name"] == "剑客无名"][0]["id"]
    r = c.post("/v1/profiles/default/active-card", json={"card_id": cid})
    assert r.json()["active_card_id"] == cid

    from nianxia_core.memory.assemble import assemble
    from nianxia_core.memory.store import ProfileStore

    out = assemble(ProfileStore(tmp, "default"))
    assert "【角色】剑客无名" in out["system"]
    assert "雪夜破庙" in out["system"]
    assert "永远以剑喻人" in out["system"]
    assert out["card"]["name"] == "剑客无名"

    # 删除卡 → 自动解除启用，回到默认 persona
    c.delete(f"/v1/cards/{cid}")
    out = assemble(ProfileStore(tmp, "default"))
    assert out["card"] is None
    assert "【人设】" in out["system"]


def test_session_greeting(env):
    c, _ = env
    r = c.post("/v1/profiles/default/active-card", json={"card_id": BUILTIN_CARD.id})
    assert r.status_code == 200
    r = c.post("/v1/profiles/default/sessions")
    d = r.json()
    assert "你来啦" in d["greeting"]
    hist = c.get(f"/v1/profiles/default/sessions/{d['session_id']}").json()
    msgs = hist["items"]
    assert msgs[0]["role"] == "assistant" and msgs[0]["content"] == d["greeting"]


def test_parse_mes_example():
    text = "<START>\n{{user}}: 你好\n{{char}}: （笑）你好呀\n{{user}}: 在干嘛\n{{char}}: 在想你\n"
    pairs = _parse_mes_example(text)
    assert pairs == [("你好", "（笑）你好呀"), ("在干嘛", "在想你")]
    assert _parse_mes_example("") == []


def test_render_vars():
    card = CharacterCard(name="阿茶", first_mes="你好 {{user}}，我是 {{char}}")
    out = card.render_vars(user_name="你")
    assert out.first_mes == "你好 你，我是 阿茶"
