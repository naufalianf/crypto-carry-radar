#!/usr/bin/env python3
"""Time-series momentum multi-aset (TSMOM) — hipotesis B.

Aturan (dipilih sebelum lihat hasil, bukan hasil tuning):
- Universe: 10 coin besar USDT, data 1d dari Binance publik.
- Sinyal: momentum lookback L hari. Aset dipegang kalau return L hari > 0.
- Bobot sama rata untuk aset yang lolos, sisanya cash (tidak short).
- Rebalance tiap R hari. Turnover rendah supaya fee tidak memakan hasil.
- Fee + slippage sama dengan bot.py.

Perbandingan: BTC buy&hold, dan keranjang equal-weight buy&hold.
Cek konsistensi: pecah jadi potongan OOS 180 hari non-overlap.

  python3 portfolio.py --selftest
  python3 portfolio.py --run
"""
import argparse
import json
import math
import os
import statistics as st
import time

import bot

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "hasil")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
           "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT")
INTERVAL = "1d"
LOOKBACKS = (30, 60, 90, 180)
REBALS = (7, 30)
CHUNK = 180


def load(years=4):
    end = int(time.time() * 1000)
    start = end - years * 365 * 86_400_000
    raw = {s: bot.fetch(s, INTERVAL, start, end) for s in SYMBOLS}
    common = None
    for s in SYMBOLS:
        keys = {int(r[0]) for r in raw[s]}
        common = keys if common is None else (common & keys)
    common = sorted(common)
    ts = common
    opens, closes = {}, {}
    for s in SYMBOLS:
        m = {int(r[0]): r for r in raw[s]}
        opens[s] = [float(m[t][1]) for t in ts]
        closes[s] = [float(m[t][4]) for t in ts]
    return ts, opens, closes


def tsmom_weights(closes, L, R):
    """Bobot target per bar (None = tidak rebalance di bar itu).
    Sinyal memakai close bar i-1 dan dieksekusi di open bar i (anti look-ahead)."""
    n = len(next(iter(closes.values())))
    out = []
    for i in range(n):
        if i % R != 0 or i < L + 1:
            out.append(None)
            continue
        j = i - 1                                    # close yang sudah tutup sebelum open hari i
        picked = [s for s in SYMBOLS
                  if closes[s][j - L] > 0 and closes[s][j] / closes[s][j - L] - 1 > 0]
        w = {s: 1.0 / len(picked) for s in picked} if picked else {}
        out.append(w)
    return out


def sim(opens, closes, weights):
    """Simulasi portofolio long-only, rebalance diskrit, cash tidak boleh negatif.
    Jual dulu, baru beli, dan belanja diskalakan supaya biaya transaksi terbayar."""
    n = len(next(iter(closes.values())))
    rate = bot.FEE + bot.SLIP
    units = {s: 0.0 for s in SYMBOLS}
    cash, equity, turnover = 1.0, [], 0.0
    for i in range(n):
        w = weights[i]
        if w is not None:
            px = {s: opens[s][i] for s in SYMBOLS}
            vals = {s: units[s] * px[s] for s in SYMBOLS}
            total = cash + sum(vals.values())
            target = {s: total * w.get(s, 0.0) for s in SYMBOLS}
            for s in SYMBOLS:                       # jual dulu -> tambah cash
                if target[s] < vals[s] - 1e-12:
                    amt = vals[s] - target[s]
                    cash += amt * (1 - rate)
                    units[s] -= amt / px[s]
                    turnover += amt
            need = sum(max(0.0, target[s] - vals[s]) for s in SYMBOLS)
            scale = min(1.0, cash / (need * (1 + rate))) if need > 0 else 1.0
            for s in SYMBOLS:                       # beli dengan sisa cash
                want = (target[s] - vals[s]) * scale
                if want > 1e-12:
                    cash -= want * (1 + rate)
                    units[s] += want / px[s]
                    turnover += want
        equity.append(cash + sum(units[s] * closes[s][i] for s in SYMBOLS))
    return equity, turnover


def stats(eq, days_per_year=365):
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]
    sd = st.pstdev(rets) if rets else 0.0
    sharpe = (st.mean(rets) / sd * math.sqrt(days_per_year)) if sd > 0 else 0.0
    peak, mdd = eq[0], 0.0
    for e in eq:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    return {"ret_pct": round((eq[-1] / eq[0] - 1) * 100, 2),
            "sharpe": round(sharpe, 2), "mdd_pct": round(mdd * 100, 2)}


def chunks(eq, size=CHUNK, min_tail=30):
    """Potongan non-overlap berbagi batas. Ekor >= min_tail ikut dihitung,
    supaya 'chained' menutup seluruh periode (tidak membuang data terakhir)."""
    out = [eq[i:i + size + 1] for i in range(0, len(eq) - size, size)]
    tail = len(eq) - 1 - len(out) * size
    if tail >= min_tail:
        out.append(eq[len(out) * size:])
    return out


def run(years=4):
    os.makedirs(OUT, exist_ok=True)
    ts, opens, closes = load(years)
    n = len(ts)
    d0 = time.strftime("%Y-%m-%d", time.gmtime(ts[0] / 1000))
    d1 = time.strftime("%Y-%m-%d", time.gmtime(ts[-1] / 1000))
    print(f"data {n} bar 1d | {d0} → {d1} | {len(SYMBOLS)} aset")

    btc = "{:<22}{:>9}{:>8}{:>9}{:>10}{:>10}".format("", "ret", "sharpe", "MDD", "chunk+", "chained")
    print("\n" + btc)
    bh_eq = [c / closes["BTCUSDT"][0] for c in closes["BTCUSDT"]]
    print("{:<22}{:>8.2f}%{:>8.2f}{:>8.2f}%".format("BTC buy&hold", *[stats(bh_eq)["ret_pct"],
                                                     stats(bh_eq)["sharpe"], stats(bh_eq)["mdd_pct"]]))
    eqw = [sum(closes[s][i] / closes[s][0] for s in SYMBOLS) / len(SYMBOLS) for i in range(n)]
    m = stats(eqw)
    print("{:<22}{:>8.2f}%{:>8.2f}{:>8.2f}%".format("keranjang B&H (EW)", m["ret_pct"], m["sharpe"], m["mdd_pct"]))

    report = {"bench": {"btc": stats(bh_eq), "ew": stats(eqw)}, "combos": {}}
    for L in LOOKBACKS:
        for R in REBALS:
            eq, to = sim(opens, closes, tsmom_weights(closes, L, R))
            s = stats(eq)
            ch = chunks(eq)
            pos = sum(1 for c in ch if c[-1] > c[0])
            chained = 1.0
            for c in ch:
                chained *= c[-1] / c[0]
            line = "{:<22}{:>8.2f}%{:>8.2f}{:>8.2f}%{:>7}/{:<3}{:>9.2f}%".format(
                f"TSMOM L{L} R{R}", s["ret_pct"], s["sharpe"], s["mdd_pct"],
                pos, len(ch), (chained - 1) * 100)
            print(line)
            report["combos"][f"L{L}_R{R}"] = {**s, "chunk_pos": f"{pos}/{len(ch)}",
                                              "chained_pct": round((chained - 1) * 100, 2),
                                              "turnover": round(to, 2),
                                              "chunks": [round((c[-1] / c[0] - 1) * 100, 2) for c in ch]}
    eh = chunks(bh_eq)
    print(f"\nB&H BTC potongan 180d: {sum(1 for c in eh if c[-1] > c[0])}/{len(eh)} positif "
          f"| list {[round((c[-1]/c[0]-1)*100,1) for c in eh]}")
    json.dump(report, open(os.path.join(OUT, "tsmom_daily.json"), "w"), indent=2)
    print(f"\nReport: {OUT}/tsmom_daily.json")
    return report


def selfcheck():
    # 1 aset, beli sekali, tanpa rebalance -> wajib == buy&hold (beda hanya fee awal)
    ts, opens, closes = load(1)
    n = len(ts)
    o2 = {s: (opens["BTCUSDT"] if s == "BTCUSDT" else [1.0] * n) for s in SYMBOLS}
    c2 = {s: (closes["BTCUSDT"] if s == "BTCUSDT" else [1.0] * n) for s in SYMBOLS}
    weights = [{"BTCUSDT": 1.0}] + [None] * (n - 1)
    eq, _ = sim(o2, c2, weights)
    bh = [x / closes["BTCUSDT"][0] for x in closes["BTCUSDT"]]
    # bandingkan PERTUMBUHAN, bukan level: eq[0] sudah di-mark di close bar 0
    diff = abs((eq[-1] / eq[0]) / (bh[-1] / bh[0]) - 1)
    assert diff < 1e-9, f"pertumbuhan portofolio 1 aset != buy&hold (beda {diff:.6%})"
    # biaya wajib terbayar: harga konstan 100, beli 100% -> equity awal = modal/(1+rate)
    rate = bot.FEE + bot.SLIP
    flat_o = {s: [100.0] * n for s in SYMBOLS}
    flat_c = {s: [100.0] * n for s in SYMBOLS}
    eq3, _ = sim(flat_o, flat_c, [{"BTCUSDT": 1.0}] + [None] * (n - 1))
    assert abs(eq3[0] - 1.0 / (1 + rate)) < 1e-12, "biaya transaksi awal tidak terhitung"
    eq2, _ = sim(o2, c2, [{}] * n)          # semua cash
    assert abs(eq2[-1] - 1.0) < 1e-9, "cash-only harus datar"
    print(f"selfcheck OK (1 aset == buy&hold beda {diff:.2e}; biaya awal {rate:.4%}; cash-only datar)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--years", type=int, default=4)
    a = ap.parse_args()
    if a.selftest:
        selfcheck()
    elif a.run:
        run(years=a.years)
    else:
        ap.print_help()
