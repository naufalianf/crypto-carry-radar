#!/usr/bin/env python3
"""Uji apakah strategi gaya Pine di bar 5 menit bisa hidup setelah fee.

Pertanyaan yang dijawab: bot bridge TradingView->Binance yang membuat 45 trade/hari
(134 trade dalam 3 hari) — apakah profitnya bertahan setelah fee 0,1%/sisi?

Aturan main sama dengan bot.py: sinyal diputuskan di close bar i, eksekusi di open
bar i+1 (anti look-ahead), long-only spot, modal 100%, fee + slippage di tiap sisi.

  python3 uji_churn.py --fetch --hari 180    # unduh 5m BTCUSDT
  python3 uji_churn.py --run                 # jalankan semua aturan, tulis hasil/churn.json
  python3 uji_churn.py --selftest            # cek harness: aturan "tiap bar" harus rugi = 2x biaya
"""
import argparse
import json
import os

import bot

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "hasil")
BIAYA = bot.FEE + bot.SLIP          # per sisi; satu putaran = 2x
BAR_MS = 300_000
bot.BAR_MS.update({"5m": 300_000, "15m": 900_000})   # bot.py baru kenal 1h/4h/1d


# ---------------------------------------------------------------- aturan sinyal
# Semua mengembalikan list 0/1 per bar: 1 = ingin pegang posisi saat itu.
# Dibaca HANYA dari data sampai bar i (tidak ada look-ahead).

def aturan_sma(closes, cepat=12, lambat=48):
    out, n = [0] * len(closes), len(closes)
    for i in range(lambat, n):
        a = sum(closes[i - cepat + 1:i + 1]) / cepat
        b = sum(closes[i - lambat + 1:i + 1]) / lambat
        out[i] = 1 if a > b else 0
    return out


def aturan_breakout(highs, lows, closes, n=48):
    out = [0] * len(closes)
    for i in range(n, len(closes)):
        if closes[i] > max(highs[i - n:i]):
            out[i] = 1
        elif closes[i] < min(lows[i - n:i]):
            out[i] = 0
        else:
            out[i] = out[i - 1]
    return out


def aturan_rsi(closes, n=14, bawah=30, atas=70):
    out = [0] * len(closes)
    for i in range(n, len(closes)):
        naik = turun = 0.0
        for j in range(i - n + 1, i + 1):
            d = closes[j] - closes[j - 1]
            if d > 0:
                naik += d
            else:
                turun -= d
        rsi = 100.0 if turun == 0 else 100 - 100 / (1 + naik / turun)
        if rsi < bawah:
            out[i] = 1
        elif rsi > atas:
            out[i] = 0
        else:
            out[i] = out[i - 1]
    return out


def aturan_tiap_bar(closes):
    """Pembanding: beli-jual tiap bar. Dipakai selftest untuk memastikan biaya dihitung benar."""
    out = [0] * len(closes)
    for i in range(1, len(closes)):
        out[i] = i % 2
    return out


# ---------------------------------------------------------------- mesin
def hitung(opens, highs, lows, closes, sinyal, modal=1000.0, fee=None, slip=None):
    """Backtest sama dengan bot.py, tapi biaya dipisah dari gerak harga.
    Sinyal di close bar i -> order di open bar i+1."""
    fee = bot.FEE if fee is None else fee
    slip = bot.SLIP if slip is None else slip
    cash, koin, masuk, tahan = modal, 0.0, 0.0, 0
    tutup, bruto_list, tahan_list = [], [], []
    nilai_masuk = modal

    for i in range(len(closes) - 1):
        nxt = opens[i + 1]
        if sinyal[i] == 1 and koin == 0.0:
            koin = cash / (nxt * (1 + slip) * (1 + fee))
            cash, masuk, tahan = 0.0, nxt, 0
            nilai_masuk = koin * nxt
        elif sinyal[i] == 0 and koin > 0.0:
            cash = koin * nxt * (1 - slip) * (1 - fee)
            koin = 0.0
            tutup.append(cash / nilai_masuk - 1.0 if nilai_masuk else 0.0)
            bruto_list.append(nxt / masuk - 1.0 if masuk else 0.0)
            tahan_list.append(tahan)
            tahan = 0
        elif koin > 0.0:
            tahan += 1

    akhir = cash or koin * closes[-1] * (1 - slip) * (1 - fee)
    return {
        "trade": len(tutup),
        "menang_pct": 100.0 * sum(1 for x in tutup if x > 0) / len(tutup) if tutup else 0.0,
        "net_pct": 100.0 * (akhir / modal - 1.0),
        "bruto_pct": 100.0 * sum(bruto_list),
        "biaya_pct": 100.0 * (sum(bruto_list) - sum(tutup)),
        "rata_tahan_bar": round(sum(tahan_list) / len(tahan_list), 1) if tahan_list else 0.0,
        "rata_net_trade_pct": 100.0 * sum(tutup) / len(tutup) if tutup else 0.0,
    }


def selftest():
    # harga datar: beli-jual tiap bar -> rugi persis sebesar biaya per putaran
    n = 40
    flat = [100.0] * n
    r = hitung(flat, flat, flat, flat, aturan_tiap_bar(flat))
    biaya_per_putaran = 2 * (bot.FEE + bot.SLIP) * 100.0
    harus = -biaya_per_putaran * r["trade"]
    assert abs(r["net_pct"] - harus) < 0.5, f"net {r['net_pct']:.2f} != {harus:.2f}"
    assert r["trade"] > 15, r["trade"]
    assert r["menang_pct"] < 1.0, "harga datar tidak boleh ada trade menang"

    # harga naik terus: satu trade beli di awal harus untung (biaya sekali masuk)
    naik = [100.0 * (1.01 ** i) for i in range(n)]
    sinyal = [1] * (n - 1) + [0]
    r2 = hitung(naik, naik, naik, naik, sinyal)
    assert r2["trade"] == 0, "belum ditutup di dalam loop -> 0 trade tertutup"
    assert r2["net_pct"] > 0, r2
    print("uji_churn selftest: OK")


def muat(hari, symbol="BTCUSDT", interval="5m", offset=0):
    akhir = int(__import__("time").time() * 1000) - offset * 86_400_000
    mulai = akhir - hari * 86_400_000
    rows = bot.fetch(symbol, interval, mulai, akhir)
    rows = [r for r in rows if int(r[0]) >= mulai]
    return rows


def run(hari=180, interval="5m", symbol="BTCUSDT", fee=None, slip=None, offset=0):
    rows = muat(hari, symbol=symbol, interval=interval, offset=offset)
    if len(rows) < 500:
        raise SystemExit(f"data terlalu sedikit: {len(rows)} bar")
    o = [float(r[1]) for r in rows]
    h = [float(r[2]) for r in rows]
    l = [float(r[3]) for r in rows]
    c = [float(r[4]) for r in rows]
    bar = len(c)
    step = bot.BAR_MS[interval]
    hari_nyata = bar * step / 86_400_000

    gerak = [abs(c[i] / c[i - 1] - 1) for i in range(1, bar)]
    gerak.sort()
    amb = gerak[len(gerak) // 2]
    _fee = bot.FEE if fee is None else fee
    _slip = bot.SLIP if slip is None else slip
    biaya_putaran = 2 * (_fee + _slip) * 100

    aturan = {
        "sma_12_48": aturan_sma(c),
        "breakout_48": aturan_breakout(h, l, c),
        "rsi_14": aturan_rsi(c),
    }
    hasil = {"symbol": symbol, "interval": interval, "bar": bar,
             "hari": round(hari_nyata, 1), "biaya_putaran_pct": round(biaya_putaran, 3),
             "gerak_median_bar_pct": round(amb * 100, 4),
             "aturan": {}}
    for nama, sig in aturan.items():
        hasil["aturan"][nama] = hitung(o, h, l, c, sig, fee=fee, slip=slip)

    # berapa bar yang geraknya melebihi biaya satu putaran -> peluang realistis
    lolos = sum(1 for g in gerak if g > 2 * BIAYA)
    hasil["bar_lolos_biaya_pct"] = round(100.0 * lolos / len(gerak), 2)
    hasil["beli_tahan_pct"] = round(100.0 * (c[-1] / c[0] - 1.0), 2)

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"churn_{symbol}_{interval}_off{offset}.json"), "w") as f:
        json.dump(hasil, f, indent=2)
    return hasil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--hari", type=int, default=180)
    ap.add_argument("--interval", default="5m", choices=["5m", "15m", "1h", "4h"])
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--offset-hari", type=int, default=0)
    ap.add_argument("--fee", type=float, default=None)
    ap.add_argument("--slip", type=float, default=None)
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    if a.run:
        h = run(a.hari, a.interval, a.symbol, a.fee, a.slip, a.offset_hari)
        print(f"{h['symbol']} {h['interval']} — {h['hari']} hari, {h['bar']} bar")
        print(f"biaya 1 putaran      : {h['biaya_putaran_pct']}%")
        print(f"gerak median per bar : {h['gerak_median_bar_pct']}%")
        print(f"bar lolos biaya      : {h['bar_lolos_biaya_pct']}%")
        print()
        for nama, r in h["aturan"].items():
            print(f"{nama:14s} trade {r['trade']:4d} | menang {r['menang_pct']:5.1f}% | "
                  f"bruto {r['bruto_pct']:7.1f}% | biaya {r['biaya_pct']:7.1f}% | "
                  f"NET {r['net_pct']:7.1f}% | tahan {r['rata_tahan_bar']:5.1f} bar")
        return
    ap.print_help()


if __name__ == "__main__":
    main()