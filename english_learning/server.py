#!/usr/bin/env python3
"""極小訪客計數服務（Python 標準函式庫，無需 Flask）。
   GET  /api/count  -> {"count": N}
   POST /api/visit  -> 累加並回傳 {"count": N}
   計數存於 /data/visits.json（用 docker volume 保存，重啟不歸零）。
"""
import json, os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA = "/data/visits.json"
lock = threading.Lock()


def read_count():
    try:
        with open(DATA) as f:
            return int(json.load(f).get("count", 0))
    except Exception:
        return 0


def write_count(n):
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    tmp = DATA + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"count": n}, f)
    os.replace(tmp, DATA)


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/count":
            self._send({"count": read_count()})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/visit":
            with lock:
                n = read_count() + 1
                write_count(n)
            self._send({"count": n})
        else:
            self._send({"error": "not found"}, 404)

    def log_message(self, *args):
        pass  # 安靜


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 5000), Handler).serve_forever()
