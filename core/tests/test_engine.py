"""引擎选择：L0 发现 / 兜底顺序 / 状态接口。"""

from nianxia_core.inference.l0 import L0Sidecar
from nianxia_core.runtime.engine import pick_engine


def test_l0_status_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(L0Sidecar, "is_running", lambda self: False)  # 真 sidecar 在跑时不受污染
    sc = L0Sidecar(tmp_path)
    st = sc.status()
    assert st["installed"] is False
    assert st["model_path"] is None
    assert st["running"] is False


def test_l0_discovers_model_and_mmproj(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    (models / "qwen3.5-2b-q4_k_m.gguf").write_bytes(b"fake-weights")
    (models / "mmproj-qwen3.5-2b.gguf").write_bytes(b"fake-mmproj")
    fake_bin = tmp_path / "llama-server.exe"
    fake_bin.write_bytes(b"MZ")
    monkeypatch.setenv("NIANXIA_LLAMA_SERVER", str(fake_bin))

    sc = L0Sidecar(tmp_path)
    st = sc.status()
    assert st["model_path"].endswith("qwen3.5-2b-q4_k_m.gguf")
    assert st["mmproj_path"].endswith("mmproj-qwen3.5-2b.gguf")
    assert st["binary"] == str(fake_bin)
    assert st["installed"] is True


def test_pick_engine_none_without_anything(tmp_path):
    name, client = pick_engine("L0", tmp_path, {"llm": {}}, None)
    assert name is None and client is None


def test_pick_engine_prefers_l1_when_configured(tmp_path):
    media = {"llm": {"base_url": "https://api.example.com/v1", "model": "m"}}
    name, client = pick_engine("L0", tmp_path, media, "sk-test")
    assert name == "l1"  # L0 未安装时 L1 兜底
    assert client is not None


def test_pick_engine_tier_l1_skips_l0_first(tmp_path):
    media = {"llm": {"base_url": "https://api.example.com/v1", "model": "m"}}
    name, _ = pick_engine("L1", tmp_path, media, "sk-test")
    assert name == "l1"
