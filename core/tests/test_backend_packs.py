"""后端包：sha256 校验失败必删 / 解压防 zip-slip / backend.json 落盘。"""

import io
import json
import time
import zipfile

from nianxia_core.inference import backend_packs


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_extract_zip_slip_blocked(tmp_path):
    evil = tmp_path / "evil.zip"
    evil.write_bytes(_make_zip({"../../escape.txt": b"x"}))
    dest = tmp_path / "dest"
    try:
        backend_packs._extract(evil, dest)
        assert False, "应当拒绝 zip-slip"
    except ValueError:
        pass
    assert not (tmp_path / "escape.txt").exists()


def test_install_pack_end_to_end(tmp_path, monkeypatch):
    """本地假 zip + 真 sha256：完整走 下载→校验→解压→backend.json。"""
    payload = _make_zip({"llama-server.exe": b"MZ-fake", "ggml.dll": b"dll"})
    import hashlib

    sha = hashlib.sha256(payload).hexdigest()
    manifest = {
        "llama_tag": "bTEST",
        "backends": {"cpu": {"windows": [{"name": "cpu.zip", "url": "http://x/cpu.zip", "sha256": sha}]}},
    }
    monkeypatch.setattr(backend_packs, "load_manifest", lambda: manifest)
    monkeypatch.setattr(backend_packs, "_sys_key", lambda: "windows")

    class FakeResp:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self, n):
            yield payload

    monkeypatch.setattr(backend_packs.httpx, "stream", lambda *a, **k: FakeResp())

    r = backend_packs.start_pack_download(tmp_path, "cpu")
    assert r["ok"]
    for _ in range(50):
        if backend_packs.pack_status("cpu").get("state") in ("done", "error"):
            break
        time.sleep(0.05)
    st = backend_packs.pack_status("cpu")
    assert st["state"] == "done", st
    dest = tmp_path / "llama" / "cpu"
    assert (dest / "llama-server.exe").read_bytes() == b"MZ-fake"
    meta = json.loads((dest / "backend.json").read_text(encoding="utf-8"))
    assert meta["backend"] == "cpu" and meta["assets"][0]["sha256"] == sha


def test_install_pack_sha_mismatch_honest(tmp_path, monkeypatch):
    """sha 不符：报错且不产物。"""
    manifest = {
        "llama_tag": "bTEST",
        "backends": {"hip": {"windows": [{"name": "hip.zip", "url": "http://x/hip.zip", "sha256": "0" * 64}]}},
    }
    monkeypatch.setattr(backend_packs, "load_manifest", lambda: manifest)
    monkeypatch.setattr(backend_packs, "_sys_key", lambda: "windows")

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self, n):
            yield b"tampered"

    monkeypatch.setattr(backend_packs.httpx, "stream", lambda *a, **k: FakeResp())

    backend_packs.start_pack_download(tmp_path, "hip")
    for _ in range(50):
        if backend_packs.pack_status("hip").get("state") in ("done", "error"):
            break
        time.sleep(0.05)
    st = backend_packs.pack_status("hip")
    assert st["state"] == "error" and "sha256" in st["error"]
    assert not (tmp_path / "llama" / "hip").exists()
