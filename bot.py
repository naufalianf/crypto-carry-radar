#!/usr/bin/env python3
"""Backtest spot crypto — Fase 0. Stdlib only (no pandas/numpy).

Aturan main:
- Sinyal diputuskan di close bar i, EKSEKUSI di open bar i+1 (anti look-ahead).
- Long-only spot (tanpa leverage), posisi 0 atau 100% modal.
- Fee + slippage dimasukkan ke setiap transaksi.
- Walk-forward: param dioptimasi di data in-sample (70%), diuji out-of-sample (30%).

Jalankan:
  python3 bot.py --selftest          # cek rumus metrik
  python3 bot.py --fetch             # unduh + cache data
  python3 bot.py --run               # backtest penuh
"""
import argparse
import json
import math
import os
import statistics as st
import time
import urllib.request

BASE = "https://data-api.binance.vision/api/v3/klines"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "hasil")
FEE = 0.001        # 0.1% taker spot Binance per sisi
SLIP = 0.0005      # 0.05% slippage asumsi order kecil
BAR_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
BARS_PER_YEAR = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365}


# ---------- data ----------
def fetch(symbol, interval, start_ms, end_ms, cache=CACHE):
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, f"{symbol}_{interval}_{start_ms}.json")
    if os.path.exists(path):
        return json.load(open(path))
    step = BAR_MS[interval]
    rows, cur = [], start_ms
    while cur < end_ms:
        url = (f"{BASE}?symbol={symbol}&interval={interval}"
               f"&startTime={cur}&endTime={end_ms}&limit=1000")
        with urllib.request.urlopen(url, timeout=30) as r:
            batch = json.loads(r.read())
        if not batch:
            break
        rows.extend(batch)
        cur = batch[-1][0] + step
        if len(batch) < 1000:
            break
        time.sleep(0.25)
    json.dump(rows, open(path, "w"))
    return rows


def to_series(rows):
    open_t = [float(r[1]) for r in rows]
    close_t = [float(r[4]) for r in rows]
    ts = [int(r[0]) for r in rows]
    return ts, open_t, close_t


# ---------- strategi (return: list target posisi, diputuskan di close i) ----------
def sma(vals, n, i):
    if i + 1 < n:
        return None
    return sum(vals[i + 1 - n:i + 1]) / n


def sig_sma_cross(closes, fast, slow):
    out = [0] * len(closes)
    state = 0
    for i in range(len(closes)):
        f, s = sma(closes, fast, i), sma(closes, slow, i)
        if f is None or s is None:
            out[i] = 0
            continue
        state = 1 if f > s else 0
        out[i] = state
    return out


def sig_meanrev(closes, lookback, entry_z, exit_z, max_hold):
    out = [0] * len(closes)
    state, held = 0, 0
    for i in range(len(closes)):
        w = closes[i + 1 - lookback:i + 1]
        if len(w) < lookback:
            out[i] = 0
            continue
        m = sum(w) / lookback
        sd = st.pstdev(w) or 1e-9
        z = (closes[i] - m) / sd
        if state == 0:
            if z <= -entry_z:
                state, held = 1, 0
        else:
            held += 1
            if z >= exit_z or held >= max_hold:
                state = 0
        out[i] = state
    return out


# ---------- eksekusi ----------
def simulate(opens, closes, target):
    """target[i] diputuskan di close i, dieksekusi di open i+1."""
    cash, coin = 1.0, 0.0
    equity = [1.0]
    trades, entry_eq, hold = [], None, 0
    for i in range(1, len(closes)):
        tgt = target[i - 1]
        px = opens[i]
        if tgt == 1 and coin == 0.0 and px > 0:
            qty = cash / (px * (1 + SLIP) * (1 + FEE))
            coin, cash = qty, 0.0
            entry_eq = coin * closes[i]
        elif tgt == 0 and coin > 0.0:
            cash = coin * px * (1 - SLIP) * (1 - FEE)
            coin = 0.0
            trades.append((entry_eq, cash))
            entry_eq = None
        eq = cash + coin * closes[i]
        equity.append(eq)
        hold += 1
    if coin > 0.0:
        cash = coin * closes[-1] * (1 - SLIP) * (1 - FEE)
        trades.append((entry_eq, cash))
    return equity, trades


# ---------- metrik ----------
def metrics(equity, trades=None, interval="4h"):
    n = len(equity)
    if n < 2:
        return {}
    rets = [equity[i] / equity[i - 1] - 1 for i in range(1, n) if equity[i - 1] > 0]
    mean, sd = (st.mean(rets), st.pstdev(rets)) if rets else (0.0, 0.0)
    sharpe = (mean / sd * math.sqrt(BARS_PER_YEAR[interval])) if sd > 0 else 0.0
    peak, mdd = equity[0], 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    wins = [1 for a, b in (trades or []) if b > a]
    gain = sum(b - a for a, b in (trades or []) if b > a)
    loss = -sum(b - a for a, b in (trades or []) if b <= a)
    return {
        "total_return_pct": round((equity[-1] - 1) * 100, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "sharpe": round(sharpe, 2),
        "trades": len(trades or []),
        "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
        "profit_factor": round(gain / loss, 2) if loss > 0 else None,
        "final_equity": round(equity[-1], 4),
    }


def selfcheck():
    e, _ = simulate([1.0, 2.0, 1.0], [1.0, 2.0, 1.0], [1, 0, 0])
    assert abs(metrics([1.0, 2.0, 1.0])["max_drawdown_pct"] + 50.0) < 1e-6, "MDD salah"
    assert abs(metrics([1.0, 2.0])["total_return_pct"] - 100.0) < 1e-6, "return salah"
    assert metrics([1.0, 1.0, 1.0], [(1.0, 1.1), (1.0, 0.9)])["win_rate_pct"] == 50.0
    # fee+slippage harus bikin rugi walau harga bolak-balik
    eq, tr = simulate([100, 100, 100], [100, 100, 100], [1, 0, 0])
    assert eq[-1] < 1.0 and tr, "biaya transaksi tidak terhitung"
    print("selfcheck OK")


def grid(interval):
    strat = []
    for fast in (10, 20, 50):
        for slow in (50, 100, 200):
            if fast < slow:
                strat.append((f"sma{fast}/{slow}", lambda c, f=fast, s=slow: sig_sma_cross(c, f, s)))
    for lb in (20, 50, 100):
        for ez in (0.5, 1.0, 1.5, 2.0):
            for xz in (0.0, 0.5):
                for mh in (12, 24, 48):
                    strat.append((f"mr{lb}_z{ez}_x{xz}_h{mh}",
                                  lambda c, a=lb, b=ez, d=xz, e=mh: sig_meanrev(c, a, b, d, e)))
    return strat


def run(interval="4h", years=3, symbols=("BTCUSDT", "ETHUSDT")):
    os.makedirs(OUT, exist_ok=True)
    end = int(time.time() * 1000)
    start = end - years * 365 * 86_400_000
    report = {}
    for sym in symbols:
        rows = fetch(sym, interval, start, end)
        ts, opens, closes = to_series(rows)
        cut = int(len(closes) * 0.7)
        print(f"\n=== {sym} {interval} | {len(closes)} bar | "
              f"{time.strftime('%Y-%m-%d', time.gmtime(ts[0]/1000))} → {time.strftime('%Y-%m-%d', time.gmtime(ts[-1]/1000))}")
        bh_is = metrics([c / closes[0] for c in closes[:cut]], [(closes[0], closes[cut - 1])], interval)
        bh_oos = metrics([c / closes[cut] for c in closes[cut:]], [(closes[cut], closes[-1])], interval)
        print(f"  BUY&HOLD         IS {bh_is['total_return_pct']:>8.2f}%  OOS {bh_oos['total_return_pct']:>8.2f}%  "
              f"MDD {bh_is['max_drawdown_pct']:.1f}/{bh_oos['max_drawdown_pct']:.1f}%")
        best = None
        for name, fn in grid(interval):
            tgt = fn(closes)
            eq, tr = simulate(opens, closes, tgt)
            m = metrics(eq[:cut], [t for t in tr], interval)
            if best is None or (m["sharpe"], m["total_return_pct"]) > (best[1]["sharpe"], best[1]["total_return_pct"]):
                best = (name, m, eq, tr)
        name, m_is, eq, tr = best
        # potong trade ke OOS: jalankan ulang hanya pada segmen OOS
        tgt = dict(grid(interval))[name](closes)
        eq_o, tr_o = simulate(opens[cut:], closes[cut:], tgt[cut:])
        m_oos = metrics(eq_o, tr_o, interval)
        m_is_full = metrics(eq, tr, interval)
        print(f"  TERBAIK-IS {name:<22} IS ret {m_is['total_return_pct']:>8.2f}%  sharpe {m_is['sharpe']:>5.2f}  "
              f"trade {m_is['trades']}")
        print(f"  → OOS            ret {m_oos['total_return_pct']:>8.2f}%  sharpe {m_oos['sharpe']:>5.2f}  "
              f"trade {m_oos['trades']}  WR {m_oos['win_rate_pct']}%  PF {m_oos['profit_factor']}  "
              f"MDD {m_oos['max_drawdown_pct']}%")
        report[sym] = {"bars": len(closes), "best_is": name, "is": m_is_full,
                       "oos": m_oos, "buyhold_is": bh_is, "buyhold_oos": bh_oos}
    json.dump(report, open(os.path.join(OUT, f"report_{interval}.json"), "w"), indent=2)
    print(f"\nReport disimpan: {OUT}/report_{interval}.json")
    return report


def sweep_oos(interval="4h", years=3, symbols=("BTCUSDT", "ETHUSDT")):
    """Uji semua strategi di grid pada segmen OOS. Cek: apa menang, atau kebetulan?"""
    end = int(time.time() * 1000)
    start = end - years * 365 * 86_400_000
    out = {}
    for sym in symbols:
        ts, opens, closes = to_series(fetch(sym, interval, start, end))
        cut = int(len(closes) * 0.7)
        bh = metrics([c / closes[cut] for c in closes[cut:]], interval=interval)["total_return_pct"]
        rows = []
        for name, fn in grid(interval):
            tgt = fn(closes)[cut:]
            eq, tr = simulate(opens[cut:], closes[cut:], tgt)
            m = metrics(eq, tr, interval)
            m["name"] = name
            rows.append(m)
        rets = sorted(r["total_return_pct"] for r in rows)
        sh = sorted(r["sharpe"] for r in rows)
        beat = sum(1 for r in rows if r["total_return_pct"] > bh)
        traded = [r for r in rows if r["trades"] > 0]
        print(f"\n=== {sym} {interval} OOS sweep | {len(rows)} strategi")
        print(f"  B&H OOS            : {bh:>8.2f}%")
        print(f"  median strategi    : {st.median(rets):>8.2f}%   (sharpe median {st.median(sh):.2f})")
        print(f"  mengalahkan B&H    : {beat}/{len(rows)} ({100*beat/len(rows):.0f}%)")
        print(f"  profit (ret > 0)   : {sum(1 for r in rows if r['total_return_pct']>0)}/{len(rows)}")
        top = sorted(rows, key=lambda r: -r["total_return_pct"])[:3]
        for r in top:
            print(f"  top: {r['name']:<22} ret {r['total_return_pct']:>7.2f}%  sharpe {r['sharpe']:>5.2f}  "
                  f"trade {r['trades']}  WR {r['win_rate_pct']}%  MDD {r['max_drawdown_pct']}%")
        print(f"  trade median: {st.median([r['trades'] for r in traded]) if traded else 0} "
              f"(min {min([r['trades'] for r in traded]) if traded else 0})")
        out[sym] = {"buyhold_oos": bh, "n": len(rows), "median_ret": st.median(rets),
                    "beat_bh": beat, "rows": top}
    return out


def walk_forward(interval="4h", years=3, is_bars=750, oos_bars=250,
                 symbols=("BTCUSDT", "ETHUSDT")):
    """Rolling walk-forward. Tiap window: pilih param terbaik di IS, uji di OOS
    berikutnya. Yang dirangkum adalah hasil OOS, bukan hasil IS."""
    end = int(time.time() * 1000)
    start = end - years * 365 * 86_400_000
    allrep = {}
    for sym in symbols:
        ts, opens, closes = to_series(fetch(sym, interval, start, end))
        n = len(closes)
        tactic = grid(interval)
        targets = {name: fn(closes) for name, fn in tactic}
        windows, chosen = [], {}
        i = 0
        while i + is_bars + oos_bars <= n:
            a, b, c = i, i + is_bars, i + is_bars + oos_bars
            best, best_key = None, None
            for name, _ in tactic:
                tgt = targets[name][a:b]
                eq, tr = simulate(opens[a:b], closes[a:b], tgt)
                m = metrics(eq, tr, interval)
                if m["trades"] < 3:
                    continue
                key = (m["sharpe"], m["total_return_pct"])
                if best_key is None or key > best_key:
                    best, best_key = name, key
            if best is None:
                i += oos_bars
                continue
            tgt = targets[best][b:c]
            eq, tr = simulate(opens[b:c], closes[b:c], tgt)
            m = metrics(eq, tr, interval)
            bh = (closes[c - 1] / closes[b] - 1) * 100
            windows.append({"i": i, "is": best, "oos_ret": m["total_return_pct"],
                            "oos_sharpe": m["sharpe"], "trades": m["trades"],
                            "mdd": m["max_drawdown_pct"], "bh": round(bh, 2),
                            "from": time.strftime("%Y-%m-%d", time.gmtime(ts[b] / 1000)),
                            "to": time.strftime("%Y-%m-%d", time.gmtime(ts[c - 1] / 1000))})
            chosen[best] = chosen.get(best, 0) + 1
            i += oos_bars
        rets = [w["oos_ret"] for w in windows]
        bhs = [w["bh"] for w in windows]
        curve = 1.0
        for r in rets:
            curve *= 1 + r / 100
        print(f"\n=== {sym} {interval} walk-forward | {len(windows)} window "
              f"(IS {is_bars} bar, OOS {oos_bars} bar)")
        for w in windows:
            print(f"  {w['from']}→{w['to']}  pilih {w['is']:<20} OOS {w['oos_ret']:>7.2f}%  "
                  f"B&H {w['bh']:>7.2f}%  sharpe {w['oos_sharpe']:>5.2f}  trade {w['trades']:>2}  "
                  f"MDD {w['mdd']:.1f}%")
        prof = sum(1 for r in rets if r > 0)
        print(f"  window profit     : {prof}/{len(rets)} ({100*prof/len(rets):.0f}%)")
        print(f"  median OOS        : {st.median(rets):.2f}%   (median B&H {st.median(bhs):.2f}%)")
        print(f"  rata-rata OOS     : {st.mean(rets):.2f}%   (rata B&H {st.mean(bhs):.2f}%)")
        print(f"  ngalahin B&H      : {sum(1 for r, x in zip(rets, bhs) if r > x)}/{len(rets)}")
        print(f"  kurva berantai    : {(curve-1)*100:.2f}%  (B&H {(math.prod(1+x/100 for x in bhs)-1)*100:.2f}%)")
        print(f"  stabilitas pilihan: {dict(sorted(chosen.items(), key=lambda kv: -kv[1]))}")
        allrep[sym] = {"windows": windows, "chosen": chosen, "prof": prof,
                       "median": st.median(rets), "chained": (curve - 1) * 100}
    json.dump(allrep, open(os.path.join(OUT, f"walkforward_{interval}.json"), "w"), indent=2)
    return allrep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--walkforward", action="store_true")
    ap.add_argument("--interval", default="4h")
    ap.add_argument("--years", type=int, default=3)
    a = ap.parse_args()
    if a.selftest:
        selfcheck()
    elif a.walkforward:
        walk_forward(interval=a.interval, years=a.years)
    elif a.sweep:
        sweep_oos(interval=a.interval, years=a.years)
    elif a.run:
        run(interval=a.interval, years=a.years)
    else:
        ap.print_help()
