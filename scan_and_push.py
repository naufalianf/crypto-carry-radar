#!/usr/bin/env python3
"""Pindai radar lalu commit+push web/radar.json supaya dashboard Vercel dapat data baru.

Vercel tidak bisa memanggil Binance Futures (fapi.binance.com membalas HTTP 451
dari IP cloud). Jadi mesin ini yang memindai, Vercel cuma menyajikan snapshot
statis dari raw.githubusercontent.com.

  python3 scan_and_push.py --run      # sekali
  python3 scan_and_push.py --loop     # tiap JAM jam

Prasyarat: SSH key push GitHub tersedia di GIT_SSH_KEY (default: key nerd-bot).
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import radar  # noqa: E402

GIT_SSH_KEY = os.environ.get(
    "GIT_SSH_KEY", "/opt/data/profiles/nerd-bot/home/.ssh/id_ed25519")
DATA_FILES = ["web/radar.json", "web/paper.json"]   # paper.json ditulis paper_carry.py tiap tick
JAM = 4


def _git(*args, check=True):
    env = dict(os.environ)
    env["GIT_SSH_COMMAND"] = (
        f"ssh -i {GIT_SSH_KEY} -o IdentitiesOnly=yes "
        "-o StrictHostKeyChecking=accept-new")
    return subprocess.run(["git", *args], cwd=HERE, env=env, check=check,
                          capture_output=True, text=True)


def scan_once(topn, threshold):
    payload = radar.scan(topn, threshold)
    print(f"{payload['generated_at']} | {len(payload['rows'])} koin | "
          f"lolos gate {len(payload['alerts'])}: {', '.join(payload['alerts']) or '-'}")
    return payload


def push_if_changed(payload):
    """Commit + push hanya kalau radar.json / paper.json berubah. Tahan konflik sekali."""
    ada = [f for f in DATA_FILES if os.path.exists(os.path.join(HERE, f))]
    status = _git("status", "--porcelain", "--", *ada).stdout.strip()
    if not status:
        print("tidak ada perubahan, push dilewati")
        return False
    _git("add", "--", *ada)
    _git("commit", "-q", "-m",
         f"radar: snapshot {payload['generated_at']}")
    for attempt in (1, 2):
        try:
            _git("push", "-q", "origin", "HEAD:main")
            print("ter-push ke origin/main")
            return True
        except subprocess.CalledProcessError as e:
            # remote bergerak duluan: rebase lalu coba sekali lagi
            print(f"push gagal ({attempt}): {(e.stderr or '').strip()[:200]}")
            if attempt == 2:
                return False
            _git("pull", "-q", "--rebase", "origin", "main", check=False)
    return False


def run(topn, threshold):
    push_if_changed(scan_once(topn, threshold))


def loop(topn, threshold):
    while True:
        try:
            run(topn, threshold)
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")
        time.sleep(JAM * 3600)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--top", type=int, default=60)
    ap.add_argument("--threshold", type=float, default=8.0)
    a = ap.parse_args()
    if a.loop:
        loop(a.top, a.threshold)
    elif a.run:
        run(a.top, a.threshold)
    else:
        ap.print_help()
