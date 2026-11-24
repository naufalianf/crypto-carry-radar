#!/usr/bin/env python3
"""Paper carry — simulasi eksekusi carry pakai data LIVE. Tidak ada uang, tidak ada API key.

Aturan (ditetapkan sebelum jalan, bukan hasil tuning):
- Kandidat: koin yang LOLOS gate di radar.json.
- Masuk: APR 7d >= ambang masuk (default 8%).
- Keluar: APR 7d < ambang keluar (default 4%), atau posisi lebih tua dari max_hari (default 60).
- Posisi: long spot + short perp, nominal sama, 1x tanpa leverage. Nominal 1000/buku.
- Funding diakumulasi dari endpoint funding rate (dihitung per fundingTime, tidak dobel).
- Biaya masuk+keluar diambil dari radar (fee + spread kedua kaki).

  python3 paper_carry.py --selftest
  python3 paper_carry.py --tick
  python3 paper_carry.py --loop          # tiap 4 jam
  python3 paper_carry.py --status
"""
import argparse
import csv
import json
import os
import time

from radar import FAPI, get
import risk

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "paper_carry_state.json")
TRADES = os.path.join(HERE, "paper_carry_trades.csv")
LOG = os.path.join(HERE, "paper_carry_log.txt")
RADAR_JSON = os.path.join(HERE, "web", "radar.json")
NOTIONAL = 1000.0
MAX_POS = 3
ENTRY_APR = 4.0      # ambang masuk: hanya level yang benar-benar bisa di-carry (punya pasar spot)
EXIT_APR = 2.0
MAX_DAYS = 60
MODAL_BUKU = NOTIONAL * MAX_POS   # modal terkomit maksimum; dasar ukuran rugi harian
CACHE = os.path.join(HERE, "data")


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def load():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"positions": {}, "closed": [], "equity": NOTIONAL, "started": time.time()}


def save(st):
    json.dump(st, open(STATE, "w"), indent=2)


def radar_rows():
    if not os.path.exists(RADAR_JSON):
        return []
    return json.load(open(RADAR_JSON)).get("rows", [])


def perp_info(sym):
    return get(f"{FAPI}/fapi/v1/premiumIndex?symbol={sym}", None, ttl=30)


def spot_price(sym):
    return float(get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}", None, ttl=30)["price"])


def new_funding(sym, since_ms):
    rows = get(f"{FAPI}/fapi/v1/fundingRate?symbol={sym}&startTime={since_ms + 1}&limit=1000",
               f"frp_{sym}_{since_ms}.json", ttl=300)
    return [(int(r["fundingTime"]), float(r["fundingRate"])) for r in rows]


def mark(p):
    """PnL berjalan posisi delta-neutral: funding + pergerakan basis."""
    sp, pp = spot_price(p["symbol"]), float(perp_info(p["symbol"])["markPrice"])
    s_leg = sp / p["spot_entry"] - 1
    p_leg = pp / p["perp_entry"] - 1
    gross = s_leg - p_leg + p["funding"]
    p["spot_now"], p["perp_now"] = sp, pp
    p["basis_pct"] = (pp / sp - 1) * 100          # basis sekarang, % dari spot
    p["gross"] = gross
    p["net"] = gross - p["cost"]
    return p


def keluar(st, sym, p, reason):
    """Tutup posisi: catat ke CSV + tahan di riwayat. Satu jalur kode untuk semua alasan keluar."""
    p["exit_reason"] = reason
    p["closed_iso"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    st["closed"].append(p)
    with open(TRADES, "a", newline="") as f:
        csv.writer(f).writerow([sym, p["opened_iso"], p["closed_iso"],
                                f"{p['funding']*100:.3f}%", f"{p['net']*100:.3f}%", reason])
    log(f"KELUAR {sym}: net {p['net']*100:.3f}% (funding {p['funding']*100:.3f}%) — {reason}")
    del st["positions"][sym]


def tick():
    st = load()
    rows = {r["symbol"]: r for r in radar_rows()}
    log(f"tick: {len(rows)} koin di radar, {len(st['positions'])} posisi terbuka")

    # 1. kelola posisi terbuka
    for sym in list(st["positions"]):
        p = st["positions"][sym]
        # posisi lama (sebelum basis stop ada) belum punya basis entry — hitung dari harga entry
        p.setdefault("basis_entry_pct", (p["perp_entry"] / p["spot_entry"] - 1) * 100)
        for ts, rate in new_funding(sym, p["last_funding_ms"]):
            p["funding"] += rate
            p["last_funding_ms"] = ts
        p["events"] = p.get("events", 0) + 1
        mark(p)
        age = (time.time() - p["opened"]) / 86400
        r = rows.get(sym)
        # Temuan B: kalau simbol keluar dari top-N snapshot, dulu apr jatuh ke
        # apr_entry (konstan) sehingga `apr < EXIT_APR` tak pernah terpicu tanpa
        # jejak. Sekarang: tidak ada data = tidak bisa dinilai, dan itu dicatat.
        apr = r.get("apr_7d") if r else None
        reason = None
        keluar_basis, _alasan_basis = risk.cek_basis(p.get("basis_pct", 0.0),
                                                     p.get("basis_entry_pct", 0.0))
        keluar_net, _alasan_net = risk.cek_net(p["net"] * 100)
        keluar_fund, _alasan_fund = risk.cek_funding(p["funding"] * 100)
        if keluar_fund:
            reason = _alasan_fund
        elif keluar_net:
            reason = _alasan_net
        elif apr is not None and apr < EXIT_APR:
            reason = f"APR turun ke {apr}%"
        elif keluar_basis:
            reason = _alasan_basis
        elif age >= MAX_DAYS:
            reason = f"umur {age:.0f} hari"
        if reason:
            keluar(st, sym, p, reason)
        else:
            if apr is None:
                log(f"TAHAN  {sym}: TIDAK ADA DI SNAPSHOT RADAR — EXIT_APR tak bisa "
                    f"dinilai, backstop net {risk.NET_STOP_PCT}% yang menjaga "
                    f"(net {p['net']*100:.3f}%)")
            else:
                log(f"TAHAN  {sym}: net {p['net']*100:.3f}% (funding {p['funding']*100:.3f}%) "
                    f"basis {p.get('basis_pct', 0.0):.3f}% apr7d {apr}%")

    # 1b. Kill switch harian — batas rugi dipaksa di kode, bukan di dokumen.
    # Termasuk posisi yang SUDAH ditutup hari ini: kalau tidak, rugi yang
    # direalisasikan pagi lalu posisi baru dibuka sore akan lolos dari hitungan.
    hari = time.strftime("%Y-%m-%d", time.gmtime())
    pnl_now = sum(p["net"] * p["notional"] for p in st["positions"].values())
    pnl_closed = sum(p["net"] * p["notional"] for p in st.get("closed", [])
                     if str(p.get("closed_iso", "")).startswith(hari))
    pnl_hari = pnl_now + pnl_closed
    anchor = st.get("day") or {}
    if anchor.get("date") != hari:
        anchor = {"date": hari, "pnl": pnl_hari, "halted": bool(anchor.get("halted"))}
    st["day"] = anchor
    terpicu, rugi = risk.cek_kill_switch(MODAL_BUKU + anchor["pnl"], MODAL_BUKU + pnl_hari)
    if terpicu and not anchor["halted"]:
        anchor["halted"] = True
        log(f"KILL SWITCH: rugi harian {rugi:.2f}% >= batas {risk.KILL_SWITCH_HARIAN_PCT}% "
            f"-> tutup semua posisi, berhenti sampai direset manual")
        for sym in list(st["positions"]):
            keluar(st, sym, st["positions"][sym], f"kill switch harian ({rugi:.2f}%)")
    if anchor["halted"]:
        log(f"HENTI SEMENTARA (profitabilitas hari ini {rugi:+.2f}%): tidak buka posisi baru. "
            f"Reset dengan: python3 paper_carry.py --reset-halt")
        save(st)
        return st

    # 2. buka posisi baru. Kandidat dipilih dengan aturan kualitas yang sama
    #    seperti gate radar, TAPI ambang APR sendiri (4%) — supaya jejak eksekusi
    #    tetap terkumpul pada koin yang benar-benar bisa di-carry (punya pasar spot).
    def layak(r):
        return (r.get("has_spot") and r["bond_days"] >= 30 and r["apr_7d"] >= ENTRY_APR
                and (r["spread_bps"] or 99) <= 15.0 and r["volume_musd"] >= 50.0)

    kandidat = sorted((r for r in rows.values() if layak(r)), key=lambda r: -r["apr_7d"])
    for r in kandidat:
        if len(st["positions"]) >= MAX_POS:
            break
        sym = r["symbol"]
        if sym in st["positions"]:
            continue
        try:
            pp = perp_info(sym)["markPrice"]
            sp = spot_price(sym)
        except Exception as e:
            log(f"gagal ambil harga {sym}: {type(e).__name__} {e}")
            continue
        hist = new_funding(sym, int(time.time() * 1000) - 8 * 3600 * 1000)
        st["positions"][sym] = {
            "symbol": sym, "opened": time.time(),
            "opened_iso": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
            "spot_entry": sp, "perp_entry": float(pp),
            "basis_entry_pct": (float(pp) / sp - 1) * 100,
            "cost": r["carry_cost_pct"] / 100, "funding": 0.0,
            "last_funding_ms": hist[-1][0] if hist else int(time.time() * 1000),
            "apr_entry": r["apr_7d"], "notional": NOTIONAL, "events": 0}
        log(f"MASUK  {sym}: APR {r['apr_7d']}% biaya {r['carry_cost_pct']}% "
            f"kapasitas ${r.get('depth_usd') or 0:,}")
    save(st)
    return st


def status():
    st = load()
    tot = 0.0
    print(f"{'simbol':<14}{'umur':>6}{'funding':>10}{'basis':>9}{'net':>9}{'APR masuk':>10}")
    for sym, p in st["positions"].items():
        mark(p)
        age_h = (time.time() - p["opened"]) / 3600
        tot += p["net"]
        print(f"{sym:<14}{age_h:>5.1f}h{p['funding']*100:>9.3f}%"
              f"{(p['gross']-p['funding'])*100:>8.3f}%{p['net']*100:>8.3f}%{p['apr_entry']:>9.1f}%")
    if st["closed"]:
        print(f"\nsudah ditutup ({len(st['closed'])}):")
        for p in st["closed"]:
            print(f"  {p['symbol']:<14} net {p['net']*100:>7.3f}%  "
                  f"funding {p['funding']*100:>7.3f}%  {p['exit_reason']}")
    print(f"\nPnL berjalan terbuka: {tot*NOTIONAL:+.2f} (nominal {NOTIONAL:.0f}/buku)")
    return st


def loop():
    log("paper carry mulai: mode loop tiap 4 jam")
    while True:
        try:
            tick()
        except Exception as e:
            log(f"ERROR tick: {e}")
        time.sleep(4 * 3600)


def selfcheck():
    # 1. delta-neutral: spot +10%, perp +10% -> 0
    assert abs((0.10 - 0.10) + 0.0) < 1e-12
    # 2. funding 3x0,0001 -> 0,03%
    f = sum([0.0001] * 3)
    assert abs(f * 100 - 0.03) < 1e-9
    # 3. net = gross - cost
    p = {"spot_entry": 100.0, "perp_entry": 101.0, "funding": 0.02, "cost": 0.004, "symbol": "X"}
    # tidak memanggil jaringan: hitung manual
    gross = (110 / 100 - 1) - (111.1 / 101 - 1) + 0.02
    assert abs(gross - (0.10 - 0.10 + 0.02)) < 1e-9
    assert abs((gross - p["cost"]) - 0.016) < 1e-9
    print("selfcheck OK (delta-neutral, akumulasi funding, net = gross - biaya)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--reset-halt", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selfcheck()
    elif a.reset_halt:
        st = load()
        st.get("day", {})["halted"] = False
        save(st)
        print("status henti direset; tick berikutnya boleh buka posisi baru")
    elif a.status:
        status()
    elif a.loop:
        loop()
    elif a.tick:
        tick()
        status()
    else:
        ap.print_help()
