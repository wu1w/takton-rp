"""L0 下载器：真实本地 HTTP 服务 + Range 断点续传集成测试。"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from nianxia_core.inference import downloader

PAYLOAD = b"GGUF" + b"x" * 60000  # ~60KB 假模型


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        rng = self.headers.get("Range")
        if rng:
            start = int(rng.replace("bytes=", "").split("-")[0])
            body = PAYLOAD[start:]
            self.send_response(206)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)

    def log_message(self, *a):
        pass


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def wait_done(timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if downloader.status()["status"] in ("done", "error", "cancelled"):
            return downloader.status()
        time.sleep(0.1)
    return downloader.status()


def test_download_and_resume(tmp_path):
    srv = serve()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/qwen-test-q4_k_m.gguf"

        # 预埋半截 .part → 应走 Range 续传
        models = tmp_path / "models"
        models.mkdir()
        half = len(PAYLOAD) // 2
        (models / "qwen-test-q4_k_m.gguf.part").write_bytes(PAYLOAD[:half])

        r = downloader.start(tmp_path, url)
        assert r["ok"] is True
        st = wait_done()
        assert st["status"] == "done", st
        assert st["done_bytes"] == len(PAYLOAD)  # 半截 + 续传 = 全量

        final = models / "qwen-test-q4_k_m.gguf"
        assert final.exists()
        assert final.read_bytes() == PAYLOAD  # 字节级一致
        assert not (models / "qwen-test-q4_k_m.gguf.part").exists()  # .part 已改名
    finally:
        srv.shutdown()


def test_download_error_honest(tmp_path):
    r = downloader.start(tmp_path, "http://127.0.0.1:1/none.gguf")  # 端口 1 必失败
    assert r["ok"] is True
    st = wait_done()
    assert st["status"] == "error"
    assert st["error"]  # 如实报错，不假装完成
    assert not list((tmp_path / "models").glob("*.gguf"))
