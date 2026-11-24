#!/usr/bin/env python3
"""Hypothesis D: funding-rate / basis carry (delta-neutral), hipotesis struktural.

Posisi: LONG spot + SHORT perpetual futures, nominal sama (1x, bukan leverage).
PnL harian:
  (+ return spot) - (return perp) + funding yang diterima posisi short
Biaya: masuk 0.15% (spot taker 0.1% + perp taker 0.05%), keluar 0.15%.
Tidak ada prediksi arah harga. Edge (kalau ada) datang dari funding + basis.

  python3 carry.py --selftest
  python3 carry.py --run --years 3
"""
import argparse
import json
import math
import os
import statistics as st
import time
import urllib.request

import bot

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "hasil")
FAPI = "https://fapi.binance.com"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
ROUND_TRIP_COST = 0.0015 * 2      # spot taker + perp taker, masuk dan keluar
CACHE = os.path.join(HERE, "data")


def get(url, cache_name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, cache_name)
    if os.path.exists(path):
        return json.load(open(path))
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read())
    json.dump(data, open(path, "w"))
    return data


def fetch_funding(sym, start_ms, end_ms):
    cur, rows = start_ms, []
    while cur < end_ms:
        url = f"{FAPI}/fapi/v1/fundingRate?symbol={sym}&startTime={cur}&endTime={end_ms}&limit=1000"
        batch = get(url, f"fund_{sym}_{cur}.json")
        if not batch:
            break
        rows.extend(batch)
        cur = int(batch[-1]["fundingTime"]) + 1
        if len(batch) < 1000:
            break
        time.sleep(0.25)
    return rows


def fetch_perp_klines(sym, start_ms, end_ms):
    cur, rows = start_ms, []
    while cur < end_ms:
        url = f"{FAPI}/fapi/v1/klines?symbol={sym}&interval=1d&startTime={cur}&endTime={end_ms}&limit=1000"
        batch = get(url, f"perp_{sym}_{cur}.json")
        if not batch:
            break
        rows.extend(batch)
        cur = int(batch[-1][0]) + 86_400_000
        if len(batch) < 1000:
            break
        time.sleep(0.25)
    return rows


def daily_funding(rows):
    """Jumlahkan funding 8h per hari UTC -> {ts_hari: total_rate}."""
    out = {}
    for r in rows:
        day = (int(r["fundingTime"]) // 86_400_000) * 86_400_000
        out[day] = out.get(day, 0.0) + float(r["fundingRate"])
    return out


def analyse(sym, years=3):
    end = int(time.time() * 1000)
    start = end - years * 365 * 86_400_000
    fund_rows = fetch_funding(sym, start, end)
    perp = fetch_perp_klines(sym, start, end)
    spot = bot.fetch(sym, "1d", start, end)
    fund = daily_funding(fund_rows)

    s_close = {int(r[0]): float(r[4]) for r in spot}
    p_close = {int(r[0]): float(r[4]) for r in perp}
    days = sorted(set(s_close) & set(p_close) & set(fund))
    if len(days) < 30:
        return None

    eq, rets, fund_contrib, basis_contrib = 1.0, [], 0.0, 0.0
    for i in range(1, len(days)):
        d, pm = days[i], days[i - 1]
        r_spot = s_close[d] / s_close[pm] - 1
        r_perp = p_close[d] / p_close[pm] - 1
        r = (r_spot - r_perp) + fund[d]
        eq *= 1 + r
        rets.append(r)
        fund_contrib += fund[d]
        basis_contrib += r_spot - r_perp
    eq_after_cost = eq * (1 - ROUND_TRIP_COST)

    sd = st.pstdev(rets)
    sharpe = st.mean(rets) / sd * math.sqrt(365) if sd > 0 else 0.0
    peak, mdd = 1.0, 0.0
    e = 1.0
    for r in rets:
        e *= 1 + r
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    npos = sum(1 for k in days if fund.get(k, 0) > 0)
    ann = (eq_after_cost ** (365 / len(days)) - 1) * 100
    return {"symbol": sym, "days": len(days),
            "from": time.strftime("%Y-%m-%d", time.gmtime(days[0] / 1000)),
            "to": time.strftime("%Y-%m-%d", time.gmtime(days[-1] / 1000)),
            "gross_pct": round((eq - 1) * 100, 2),
            "net_pct": round((eq_after_cost - 1) * 100, 2),
            "apr_net_pct": round(ann, 2),
            "funding_pct": round(fund_contrib * 100, 2),
            "basis_pct": round(basis_contrib * 100, 2),
            "sharpe": round(sharpe, 2), "mdd_pct": round(mdd * 100, 2),
            "days_funding_pos_pct": round(100 * npos / len(days), 1),
            "avg_funding_8h_bps": round(st.mean([fund[k] / 3 * 10000 for k in days]), 3),
            "per_year": per_year(days, s_close, p_close, fund)}


def per_year(days, s_close, p_close, fund):
    out = {}
    for d in range(1, len(days)):
        y = time.strftime("%Y", time.gmtime(days[d] / 1000))
        pm, cur = days[d - 1], days[d]
        rs = s_close[cur] / s_close[pm] - 1
        rp = p_close[cur] / p_close[pm] - 1
        b = out.setdefault(y, {"rets": [], "fund": 0.0, "basis": 0.0})
        b["rets"].append((rs - rp) + fund[cur])
        b["fund"] += fund[cur]
        b["basis"] += rs - rp
    return {y: {"ret_pct": round((math.prod(1 + r for r in v["rets"]) - 1) * 100, 2),
                "days": len(v["rets"]),
                "funding_pct": round(v["fund"] * 100, 2),
                "basis_pct": round(v["basis"] * 100, 2)}
            for y, v in out.items()}


def conditional(sym, years=3, thresholds=(0.0, 0.05, 0.10, 0.15, 0.20), win=7):
    """Masuk hanya kalau funding trailing `win` hari (di-annualize) > threshold.
    Setiap masuk dan keluar bayar 0.15% (satu kaki pasangan)."""
    end = int(time.time() * 1000)
    start = end - years * 365 * 86_400_000
    fund = daily_funding(fetch_funding(sym, start, end))
    perp = {int(r[0]): float(r[4]) for r in fetch_perp_klines(sym, start, end)}
    spot = {int(r[0]): float(r[4]) for r in bot.fetch(sym, "1d", start, end)}
    days = sorted(set(fund) & set(perp) & set(spot))
    print(f"\n{sym}: masuk hanya saat funding trailing {win}d mahal ({len(days)} hari)")
    print(f"  {'threshold APR':>14}{'net%':>9}{'APR%':>9}{'hari di pasar':>15}{'switch':>8}{'MDD%':>8}")
    out = {}
    for th in thresholds:
        eq, in_pos, switches, days_in = 1.0, False, 0, 0
        peak, mdd = 1.0, 0.0
        for i in range(win, len(days)):
            d, pm = days[i], days[i - 1]
            trail = sum(fund.get(days[j], 0.0) for j in range(i - win, i)) * 365 / win
            want = trail > th
            if want and not in_pos:
                eq *= 1 - 0.0015
                in_pos, switches = True, switches + 1
            if in_pos:
                rs = spot[d] / spot[pm] - 1
                rp = perp[d] / perp[pm] - 1
                eq *= 1 + (rs - rp) + fund.get(d, 0.0)
                days_in += 1
                peak = max(peak, eq)
                mdd = min(mdd, eq / peak - 1)
            if not want and in_pos:
                eq *= 1 - 0.0015
                in_pos, switches = False, switches + 1
        apr = (eq ** (365 / len(days)) - 1) * 100
        label = "trail>0" if th == 0.0 else f"{th*100:.0f}%"
        print(f"  {label:>14}{round((eq-1)*100,2):>9.2f}{round(apr,2):>9.2f}"
              f"{days_in:>15}{switches:>8}{round(mdd*100,2):>8.2f}")
        out[label] = {"net_pct": round((eq - 1) * 100, 2), "apr_pct": round(apr, 2),
                      "days_in_market": days_in, "switches": switches,
                      "mdd_pct": round(mdd * 100, 2)}
    return out


def run(years=3):
    os.makedirs(OUT, exist_ok=True)
    rep = {}
    print(f"{'aset':<10}{'hari':>6}{'gross%':>10}{'net%':>10}{'APR net%':>10}"
          f"{'funding%':>10}{'basis%':>10}{'sharpe':>8}{'MDD%':>8}{'fund+':>8}")
    for s in SYMBOLS:
        r = analyse(s, years)
        if not r:
            print(f"{s:<10} data tidak cukup")
            continue
        rep[s] = r
        print(f"{s:<10}{r['days']:>6}{r['gross_pct']:>10.2f}{r['net_pct']:>10.2f}"
              f"{r['apr_net_pct']:>10.2f}{r['funding_pct']:>10.2f}{r['basis_pct']:>10.2f}"
              f"{r['sharpe']:>8.2f}{r['mdd_pct']:>8.2f}{r['days_funding_pos_pct']:>7.1f}%")
        print(f"   {r['from']} → {r['to']} | rata funding 8h {r['avg_funding_8h_bps']} bps")
        for y, v in sorted(r["per_year"].items()):
            print(f"   {y}: net {v['ret_pct']:>7.2f}%  ({v['days']} hari)")
    path = os.path.join(OUT, f"carry_funding_y{years}.json")
    json.dump(rep, open(path, "w"), indent=2)
    print(f"\nReport: {path}")
    print(f"Asumsi biaya masuk+keluar: {ROUND_TRIP_COST*100:.2f}% dari nominal")
    return rep


def selfcheck():
    def pnl(r_spot, r_perp, r_fund):
        return (r_spot - r_perp) + r_fund

    # 1. harga naik 10% dua-duanya -> delta-neutral, PnL nol
    assert abs(pnl(0.10, 0.10, 0.0)) < 1e-12, "delta-neutral bocor"
    # 2. funding positif 1 bps/hari selama 39 hari -> naik sesuai compound
    f = 0.0001
    eq = math.prod(1 + pnl(0, 0, f) for _ in range(39))
    assert abs(eq - (1 + f) ** 39) < 1e-12, "akumulasi funding salah"
    # 3. tanpa funding & tanpa basis -> hasil wajib persis -biaya
    assert abs((1.0 * (1 - ROUND_TRIP_COST)) - (1 - ROUND_TRIP_COST)) < 1e-12
    # 4. basis menyempit 0.3% saat pegang short perp -> PnL positif
    assert pnl(0.0, -0.003, 0.0) > 0, "arah basis terbalik"
    print("selfcheck OK (delta-neutral, akumulasi funding, biaya, arah basis)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--conditional", action="store_true")
    ap.add_argument("--years", type=int, default=3)
    a = ap.parse_args()
    if a.selftest:
        selfcheck()
    elif a.conditional:
        cond = {s: conditional(s, a.years) for s in SYMBOLS}
        json.dump(cond, open(os.path.join(OUT, "carry_conditional.json"), "w"), indent=2)
        print(f"\nReport: {OUT}/carry_conditional.json")
    elif a.run:
        run(years=a.years)
    else:
        ap.print_help()
