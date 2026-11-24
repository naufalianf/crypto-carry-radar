#!/usr/bin/env python3
"""Pratinjau lokal paket Vercel: index.html statis + /api/radar dari handler yang sama.

Tujuan: lihat tampilan persis seperti di Vercel sebelum deploy.
  python3 preview_vercel.py --port 8901
"""
import argparse
import os
import sys
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web_vercel")
sys.path.insert(0, os.path.join(WEB, "api"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8901)
    a = ap.parse_args()

    import radar  # handler Vercel, modul yang sama yang dipakai di api/radar.py

    api = HTTPServer(("127.0.0.1", a.port + 1), radar.handler)
    threading.Thread(target=api.serve_forever, daemon=True).start()

    class Static(SimpleHTTPRequestHandler):
        def __init__(self, *x, **kw):
            super().__init__(*x, directory=WEB, **kw)

        def do_GET(self):
            if self.path.startswith("/api/"):
                # teruskan ke handler Vercel supaya perilakunya identik
                from urllib.request import urlopen
                try:
                    r = urlopen(f"http://127.0.0.1:{a.port + 1}{self.path}", timeout=90)
                    body, code = r.read(), r.status
                except Exception as e:
                    body, code = str(e).encode(), 502
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def log_message(self, *x):
            pass

    print(f"pratinjau: http://127.0.0.1:{a.port}")
    HTTPServer(("127.0.0.1", a.port), Static).serve_forever()


if __name__ == "__main__":
    main()
