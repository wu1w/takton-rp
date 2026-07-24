"""AI 代笔：草稿解析 + 端点错误路径（无 L0 时如实报错）。"""

import pytest
from fastapi.testclient import TestClient

from nianxia_core.api.app import app
from nianxia_core.runtime.draft import parse_draft


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from nianxia_core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "data_root", tmp_path)
    return TestClient(app), tmp_path


def test_parse_clean_json():
    text = '{"name": "阿茶", "description": "猫耳店长", "personality": "外冷内热", "scenario": "咖啡店", "first_mes": "欢迎", "mes_example": "{{user}}: 累\\n{{char}}: 坐"}'
    d = parse_draft(text)
    assert d["name"] == "阿茶"
    assert d["first_mes"] == "欢迎"
    assert d["mes_example"].startswith("{{user}}")


def test_parse_wrapped_in_prose():
    text = '好的，这是你要的卡：\n```json\n{"name": "阿茶", "description": "猫耳店长"}\n```\n希望你喜欢'
    d = parse_draft(text)
    assert d["name"] == "阿茶"
    assert d["description"] == "猫耳店长"


def test_parse_fallback_to_description():
    d = parse_draft("一个温柔的古风狐仙，喜欢下雨天。")
    assert d["description"] == "一个温柔的古风狐仙，喜欢下雨天。"
    assert d["name"] == ""


def test_parse_lenient_multiline_strings():
    """小模型把真实换行写进 JSON 字符串 → 严格解析失败 → 逐键正则兜底。"""
    text = '{\n  "name": "林栖",\n  "description": "19岁的咖啡店店长，\n拥有猫耳和尾巴。",\n  "personality": "外冷内热",\n  "scenario": "咖啡店",\n  "first_mes": "（抬头）欢迎。",\n  "mes_example": "{{user}}: 累\n{{char}}: 坐"\n}'
    d = parse_draft(text)
    assert d["name"] == "林栖"
    assert "猫耳" in d["description"]
    assert d["first_mes"] == "（抬头）欢迎。"


def test_draft_endpoint_honest_without_l0(env):
    c, _ = env
    # 空 hint
    r = c.post("/v1/cards/draft", json={"hint": "  "})
    assert r.json()["ok"] is False
    # tmp 环境没装模型 → 如实报没装
    r2 = c.post("/v1/cards/draft", json={"hint": "猫耳店长"})
    d = r2.json()
    assert d["ok"] is False
    assert "模型" in d["error"]
