"""备份/恢复/回忆读本。"""

import json
import zipfile

from nianxia_core.backup import export_backup, import_backup, export_memoir
from nianxia_core.memory import ProfileStore
from nianxia_core.models import ChatMessage


def make_root(tmp_path):
    store = ProfileStore(tmp_path, "default")
    store.add_fact("用户住在杭州", pinned=True)
    store.append_message("ses_b", ChatMessage(role="user", content="在吗", ts=1.0))
    store.append_message("ses_b", ChatMessage(role="assistant", content="在的", ts=2.0))
    (tmp_path / "secrets").mkdir(exist_ok=True)
    (tmp_path / "secrets" / "llm.key").write_text("sk-secret", encoding="utf-8")
    return store


def test_export_excludes_secrets_and_has_manifest(tmp_path):
    make_root(tmp_path)
    out = export_backup(tmp_path)
    assert out.exists()
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        manifest = json.loads(z.read("manifest.json").decode())
    assert manifest["app"] == "nianxia"
    assert manifest["profiles"] == ["default"]
    assert any("facts.jsonl" in n for n in names)
    assert not any(n.startswith("secrets/") for n in names)  # 默认剥密钥


def test_export_include_secrets_opt_in(tmp_path):
    make_root(tmp_path)
    out = export_backup(tmp_path, include_secrets=True)
    with zipfile.ZipFile(out) as z:
        assert any(n.startswith("secrets/") for n in z.namelist())


def test_import_roundtrip_and_reject_garbage(tmp_path):
    make_root(tmp_path)
    out = export_backup(tmp_path)

    target = tmp_path.parent / "restore_root"
    r = import_backup(out, target)
    assert r["ok"] is True
    assert "default" in r["profiles"]
    restored = ProfileStore(target, "default")
    assert any(f.text == "用户住在杭州" for f in restored.list_facts())

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("random.txt", "hello")
    r2 = import_backup(bad, tmp_path.parent / "restore2")
    assert r2["ok"] is False


def test_memoir_markdown(tmp_path):
    store = make_root(tmp_path)
    out = export_memoir(store)
    text = out.read_text(encoding="utf-8")
    assert "与 念念 的回忆" in text
    assert "相识第 1 天" in text
    assert "用户住在杭州" in text
    assert "**我**：在吗" in text
    assert "**念念**：在的" in text
