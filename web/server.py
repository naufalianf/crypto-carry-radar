#!/usr/bin/env python3
"""Server dashboard radar funding. Stdlib saja (http.server), tanpa Flask.

  python3 web/server.py            # http://127.0.0.1:8787
  python3 web/server.py --port 9000

Endpoint:  GET /  (dashboard)   GET /api/radar (data)   POST /api/scan (scan ulang)
"""
import argparse
import http.server
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RADAR = os.path.join(ROOT, "radar.py")
DATA = os.path.join(HERE, "radar.json")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def do_GET(self):
        if self.path.startswith("/api/radar"):
            if not os.path.exists(DATA):
                return self._send(200, b'{"rows":[],"note":"belum ada data"}', "application/json")
            return self._send(200, open(DATA, "rb").read(), "application/json")
        if self.path in ("/", "/index.html"):
            return self._send(200, open(os.path.join(HERE, "index.html"), "rb").read(),
                              "text/html; charset=utf-8")
        self.send_error(404)

    def do_POST(self):
        if self.path.startswith("/api/scan"):
            try:
                p = subprocess.run([sys.executable, RADAR, "--run"], cwd=ROOT,
                                   capture_output=True, timeout=300)
                ok = p.returncode == 0
                tail = p.stdout.decode()[-400:] if ok else p.stderr.decode()[-400:]
            except Exception as e:
                ok, tail = False, str(e)
            return self._send(200 if ok else 500,
                              json.dumps({"ok": ok, "output": tail}).encode(),
                              "application/json")
        self.send_error(404)

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    a = ap.parse_args()
    with http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler) as srv:
        print(f"Dashboard: http://127.0.0.1:{a.port}")
        srv.serve_forever()
