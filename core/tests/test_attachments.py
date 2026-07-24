"""对话附件：上传端点 + _build_user_content 多模态组装。"""

import pytest
from fastapi.testclient import TestClient

from nianxia_core.api.app import app
from nianxia_core.models import Attachment, ChatRequest
from nianxia_core.runtime.companion import _build_user_content


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """把 app 的 data_root 指到临时目录。"""
    from nianxia_core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "data_root", tmp_path)
    return TestClient(app), tmp_path


def test_upload_text_file_inline(client):
    c, _ = client
    r = c.post("/v1/media/upload", files={"file": ("笔记.md", "# 标题\n用户喜欢猫" * 10, "text/markdown")})
    assert r.status_code == 200
    d = r.json()
    assert d["kind"] == "file" and d["name"] == "笔记.md"
    assert "用户喜欢猫" in d["text"]
    rel = d["url"].split("rel=", 1)[-1]
    r2 = c.get(f"/v1/media/file?rel={rel}")
    assert r2.status_code == 200


def test_upload_image_and_traversal_blocked(client):
    c, _ = client
    png = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 32
    r = c.post("/v1/media/upload", files={"file": ("../../evil.png", png, "image/png")})
    assert r.status_code == 200
    d = r.json()
    assert d["kind"] == "image"
    assert ".." not in d["url"] and "evil.png" in d["url"]


def test_upload_unsupported_type_honest(client):
    c, _ = client
    r = c.post("/v1/media/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400
    assert "暂不支持" in r.json()["detail"]


class _FakeStore:
    def __init__(self, root):
        self.data_root = root


def test_build_content_text_attachment(tmp_path):
    req = ChatRequest(
        message="看看这个",
        attachments=[Attachment(kind="file", name="a.txt", url="/v1/media/file?rel=media/uploads/x", text="文件内容123")],
    )
    stored, content = _build_user_content(_FakeStore(tmp_path), req, "l0")
    assert "文件内容123" in content
    assert "[文件] a.txt" in stored


def test_build_content_image_blind_honest(tmp_path, monkeypatch):
    """L0 无 mmproj：不假装看见，如实声明。"""
    from nianxia_core.inference.l0 import L0Sidecar

    monkeypatch.setattr(L0Sidecar, "find_mmproj", lambda self: None)
    req = ChatRequest(
        message="看图",
        attachments=[Attachment(kind="image", name="p.png", url="/v1/media/file?rel=media/uploads/p.png")],
    )
    stored, content = _build_user_content(_FakeStore(tmp_path), req, "l0")
    assert isinstance(content, str)
    assert "看不到图" in content
    assert "[图片] p.png" in stored


def test_build_content_image_multimodal(tmp_path):
    """L1 云（有视觉）：产出 OpenAI 多模态 content 数组 + base64。"""
    up = tmp_path / "media" / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    (up / "p.png").write_bytes(b"\x89PNG-fake")
    req = ChatRequest(
        message="这图里是啥",
        attachments=[Attachment(kind="image", name="p.png", url="/v1/media/file?rel=media/uploads/p.png")],
    )
    _, content = _build_user_content(_FakeStore(tmp_path), req, "l1")
    assert isinstance(content, list)
    assert content[0]["type"] == "text" and "这图里是啥" in content[0]["text"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
