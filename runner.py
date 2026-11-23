#!/usr/bin/env python3
"""Paper-trading runner — Fase 1. Uang NYATA tidak disentuh sama sekali.

Pakai data publik Binance (tanpa API key). Simulasi fill di open bar berikutnya
setelah sinyal close, fee+slippage sama dengan bot.py (satu sumber konstanta).

Tiap buku (symbol x strategi) jalan paralel supaya keputusan strategi diuji
out-of-sample sungguhan, bukan dipilih dari yang terbaik di backtest.

Jalankan:
  python3 runner.py --selftest            # cek idempotensi + logika fill
  python3 runner.py --tick                # satu kali proses bar terakhir
  python3 runner.py --backfill 500        # isi riwayat 500 bar terakhir
  python3 runner.py --loop                # daemon: tunggu tiap bar baru (4h)
  python3 runner.py --status              # ringkasan state
"""
import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request

import bot  # konstanta fee/slippage + fetch klines (stdlib)

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "paper_state.json")
TRADES = os.path.join(HERE, "paper_trades.csv")
LOG = os.path.join(HERE, "paper_log.txt")
INTERVAL = "4h"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
CONFIGS = ((20, 100), (50, 100))   # (fast, slow) SMA
NOTIONAL = 1000.0                  # modal kertas per buku (unit bebas)
LOOKBACK = 400                     # bar yang diambil tiap tick


def books():
    return [f"{s}_{f}/{sl}" for s in SYMBOLS for f, sl in CONFIGS]


def load():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    st = {}
    for b in books():
        st[b] = {"pos": 0, "qty": 0.0, "cash": NOTIONAL, "entry": None,
                 "last_bar": 0, "trades": 0, "equity": NOTIONAL}
    return st


def save(st):
    json.dump(st, open(STATE, "w"), indent=2)


def logline(msg):
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    line = f"[{stamp}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def sma_last(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def signal(sym, closes, fast, slow):
    f, s = sma_last(closes, fast), sma_last(closes, slow)
    if f is None or s is None:
        return 0
    return 1 if f > s else 0


def fill(st, book, target, open_px, close_px, bar_ts, bar_time):
    """Eksekusi target posisi. Kembalikan event string atau None."""
    b = st[book]
    if target == b["pos"]:
        return None
    if target == 1 and b["cash"] > 0:
        px = open_px * (1 + bot.SLIP)
        b["qty"] = b["cash"] / (px * (1 + bot.FEE))
        b["cash"] = 0.0
        b["entry"] = {"ts": bar_ts, "time": bar_time, "px": round(px, 4)}
        b["pos"] = 1
    elif target == 0 and b["qty"] > 0:
        px = open_px * (1 - bot.SLIP)
        proceeds = b["qty"] * px * (1 - bot.FEE)
        pnl = round((proceeds / NOTIONAL - 1) * 100, 2)
        b["cash"] = proceeds
        b["qty"] = 0.0
        b["pos"] = 0
        b["entry"] = None
        b["trades"] += 1
        with open(TRADES, "a", newline="") as f:
            csv.writer(f).writerow([book, bar_time, "EXIT", round(px, 4), f"{pnl}%"])
        logline(f"EXIT  {book:<16} @ {px:,.2f}  pnl {pnl}%")
        return f"exit {pnl}%"
    b["pos"] = target
    if target == 1:
        b["trades"] += 1
        with open(TRADES, "a", newline="") as f:
            csv.writer(f).writerow([book, bar_time, "ENTRY", round(open_px * (1 + bot.SLIP), 4), ""])
        logline(f"ENTRY {book:<16} @ {open_px * (1 + bot.SLIP):,.2f}")
        return "entry"
    return None


def tick(st, klines):
    """Proses semua buku dari data klines (list bar Binance). Terbar Idempoten
    pada bar yang sama: kalau last_bar sudah >= bar close terakhir, tidak ada aksi."""
    events = []
    for sym in SYMBOLS:
        rows = klines[sym]
        closed = rows[:-1]          # bar terakhir masih berjalan
        cur = rows[-1]              # bar berjalan -> open-nya titik eksekusi
        close_ts = int(closed[-1][0])
        closes = [float(r[4]) for r in closed]
        open_px, mark = float(cur[1]), float(cur[4])
        bar_time = time.strftime("%Y-%m-%d %H:%M", time.gmtime(close_ts / 1000))
        for fast, slow in CONFIGS:
            book = f"{sym}_{fast}/{slow}"
            b = st[book]
            if close_ts <= b["last_bar"]:
                events.append(f"SKIP  {book:<16} bar {bar_time} sudah diproses")
                continue
            tgt = signal(sym, closes, fast, slow)
            ev = fill(st, book, tgt, open_px, mark, close_ts, bar_time)
            b["last_bar"] = close_ts
            b["equity"] = b["cash"] + b["qty"] * mark
            with open(LOG, "a") as f:
                f.write(f"[{bar_time}] sinyal {book} bar_closed={bar_time} tgt={tgt} "
                        f"equity={b['equity']:.2f}\n")
            events.append(f"{book:<16} tgt={tgt} equity={b['equity']:.2f}"
                          + (f" -> {ev}" if ev else ""))
    return events


def fetch_all(end_ms=None):
    now = end_ms or int(time.time() * 1000)
    start = now - LOOKBACK * bot.BAR_MS[INTERVAL]
    return {s: bot.fetch(s, INTERVAL, start, now) for s in SYMBOLS}


def notify(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=20)
        return True
    except Exception as e:
        logline(f"telegram gagal: {e}")
        return False


def backfill(n):
    """Replay n bar terakhir lewat SATU jalur kode yang sama dengan tick live."""
    st = load()
    end = int(time.time() * 1000)
    need = n + LOOKBACK + 2
    bars = {s: bot.fetch(s, INTERVAL, end - need * bot.BAR_MS[INTERVAL], end) for s in SYMBOLS}
    m = min(len(v) for v in bars.values())
    for i in range(LOOKBACK, m - 1):
        tick(st, {s: bars[s][i - LOOKBACK + 1:i + 2] for s in SYMBOLS})
    save(st)
    logline(f"backfill selesai: {m - 1 - LOOKBACK} bar diproses, {m} bar tersedia")
    return st


def status():
    st = load()
    print(f"{'buku':<18}{'pos':>4}{'trade':>7}{'entry px':>12}{'equity':>10}")
    for b, v in st.items():
        ep = v["entry"]["px"] if v["entry"] else 0
        print(f"{b:<18}{v['pos']:>4}{v['trades']:>7}{ep:>12}{v['equity']:>10.2f}")
    return st


def selfcheck():
    # 1. idempotensi: dua kali tick pada data sama -> tidak ada trade dobel
    st = load()
    k = fetch_all()
    st2 = {b: dict(v, trades=0, equity=NOTIONAL, pos=0, qty=0.0, cash=NOTIONAL,
                   entry=None, last_bar=0) for b, v in st.items()}
    tick(st2, k)
    t1 = json.dumps(st2, sort_keys=True)
    tick(st2, k)
    t2 = json.dumps(st2, sort_keys=True)
    assert t1 == t2, "tick tidak idempoten"
    # 2. fill pakai fee: masuk lalu keluar di harga sama harus rugi
    stx = {"X": {"pos": 0, "qty": 0.0, "cash": 1000.0, "entry": None,
                 "last_bar": 0, "trades": 0, "equity": 1000.0}}
    global TRADES
    keep, TRADES = TRADES, os.path.join(HERE, "paper_trades_selftest.csv")
    fill(stx, "X", 1, 100.0, 100.0, 1, "t")
    fill(stx, "X", 0, 100.0, 100.0, 2, "t")
    TRADES = keep
    assert stx["X"]["cash"] < 1000.0, "fee/slippage tidak masuk"
    assert stx["X"]["pos"] == 0
    print("selfcheck OK (idempoten + biaya transaksi terhitung)")


def loop():
    logline("runner mulai: mode loop tiap bar 4h")
    while True:
        try:
            st = load()
            ev = tick(st, fetch_all())
            save(st)
            logline(" | ".join(ev))
            notify("PAPER 4h\n" + "\n".join(e for e in ev if "SKIP" not in e))
        except Exception as e:
            logline(f"ERROR tick: {e}")
        nxt = (int(time.time()) // (bot.BAR_MS[INTERVAL] // 1000) + 1) * (bot.BAR_MS[INTERVAL] // 1000)
        time.sleep(max(60, nxt - int(time.time()) + 30))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--backfill", type=int, default=0)
    a = ap.parse_args()
    if a.selftest:
        selfcheck()
    elif a.status:
        status()
    elif a.backfill:
        backfill(a.backfill)
        status()
    elif a.loop:
        loop()
    elif a.tick:
        st = load()
        ev = tick(st, fetch_all())
        save(st)
        print("\n".join(ev))
    else:
        ap.print_help()
