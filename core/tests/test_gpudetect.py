"""gpudetect 候选链排序 + sidecar vendor 多后端发现。"""

from nianxia_core.inference.gpudetect import backend_candidates
from nianxia_core.inference.l0 import L0Sidecar


def test_candidates_windows_nvidia():
    c = backend_candidates(["NVIDIA GeForce RTX 3060"], system="Windows")
    assert c[0] == "cuda" and c[-1] == "cpu" and "vulkan" in c


def test_candidates_windows_amd_supported():
    c = backend_candidates(["AMD Radeon RX 6800 XT"], system="Windows")
    assert c[0] == "hip" and c.index("hip") < c.index("vulkan")


def test_candidates_windows_intel_arc():
    c = backend_candidates(["Intel(R) Arc(TM) A770 Graphics"], system="Windows")
    assert c[0] == "sycl"


def test_candidates_windows_unknown():
    c = backend_candidates(["Microsoft Basic Display Adapter"], system="Windows")
    assert c == ["vulkan", "cpu"]


def test_candidates_non_client_platform():
    """非客户端平台（如开发用 Linux）：保守兜底 vulkan→cpu。"""
    assert backend_candidates(["MI210"], system="Linux") == ["vulkan", "cpu"]


def test_candidates_macos():
    assert backend_candidates([], system="Darwin") == ["metal", "cpu"]


def test_sidecar_vendor_scan_order(tmp_path, monkeypatch):
    """vendor/llama/<backend>/ 按候选链顺序命中（vendor_root 指向临时目录，防真实包污染）。"""
    import nianxia_core.inference.l0 as l0mod

    # 伪造候选链 sycl→vulkan→cpu；只放 vulkan 的二进制 → 应命中 vulkan
    monkeypatch.setattr(L0Sidecar, "candidates", lambda self: ["sycl", "vulkan", "cpu"])
    fake_vendor = tmp_path / "vendor"
    vdir = fake_vendor / "llama" / "vulkan"
    vdir.mkdir(parents=True)
    fake = vdir / "llama-server"
    fake.write_bytes(b"#!/bin/sh\n")
    monkeypatch.setattr(l0mod, "vendor_root", lambda: fake_vendor)
    sc = L0Sidecar(tmp_path)
    binary, backend = sc.find_binary()
    assert backend == "vulkan"
    assert binary == str(fake)
    st = sc.status()
    assert st["candidates"] == ["sycl", "vulkan", "cpu"]
