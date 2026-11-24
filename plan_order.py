#!/usr/bin/env python3
"""Tahap 1 — rencana order carry. TIDAK mengirim order, TIDAK butuh API key.

Bot memilih koin yang lolos gate, menghitung ukuran posisi dari kedalaman orderbook
nyata, lalu menyusun rencana: harga entry dua kaki, biaya, hari balik modal, margin,
aturan keluar. Bro eksekusi manual.

Pakai:
  python3 plan_order.py --selftest
  python3 plan_order.py --run --capital 1000        # cetak ke layar
  python3 plan_order.py --run --capital 1000 --send # kirim ke bot alert (Telegram)
"""
import subprocess
import argparse
import json
import os
import time

import radar
import risk

CAPITAL = 1000.0      # nominal per posisi (USD)
BOOK_USE = 0.10       # maksimal 10% kedalaman orderbook dalam pita 0,1%
BAND = 0.001          # pita harga 0,1% dari mid
MIN_NOTIONAL = 20.0   # minimum order supaya tidak ditolak exchange
MAX_POS = 3
HERE = os.path.dirname(os.path.abspath(__file__))


def depth(sym, spot=False, limit=100):
    base = radar.SPOT if spot else radar.FAPI
    path = "/api/v3/depth" if spot else "/fapi/v1/depth"
    url = f"{base}{path}?symbol={sym}&limit={limit}"
    return radar.get(url, f"d100_{'s' if spot else 'f'}_{sym}_{int(time.time()) // 300}.json",
                     ttl=300)


def band_capacity(book):
    """Notional yang bisa dieksekusi tanpa keluar pita 0,1% dari mid. (bid, ask, mid)."""
    bids = [(float(p), float(q)) for p, q in book["bids"]]
    asks = [(float(p), float(q)) for p, q in book["asks"]]
    if not bids or not asks:
        return 0.0, 0.0, 0.0
    mid = (bids[0][0] + asks[0][0]) / 2
    lo, hi = mid * (1 - BAND), mid * (1 + BAND)
    return (sum(p * q for p, q in bids if p >= lo),
            sum(p * q for p, q in asks if p <= hi), mid)


def capacity(sym):
    """Kapasitas dua kaki. Kedua kaki harus muat, jadi ukuran = yang terkecil."""
    kb = depth(sym, spot=False)
    sb = depth(sym, spot=True)
    pbid, pask, pmid = band_capacity(kb)
    sbid, sask, smid = band_capacity(sb)
    masuk = min(sask, pbid)          # kita BELI di spot (pakai ask), SHORT di perp (pakai bid)
    return {"spot_mid": smid, "perp_mid": pmid,
            "spot_ask": float(sb["asks"][0][0]), "perp_bid": float(kb["bids"][0][0]),
            "kapasitas": masuk, "perp_ask": float(kb["asks"][0][0]),
            "spot_bid": float(sb["bids"][0][0])}


def ukuran(sym, modal, cap):
    """Ukuran posisi = modal, tapi tidak lebih dari BOOK_USE x kapasitas,
    dan tidak lebih dari plafon risiko per posisi (risk.batas_notional)."""
    plafon = risk.batas_notional(modal)
    batas_buku = cap["kapasitas"] * BOOK_USE
    n = min(modal, batas_buku, plafon)
    ikat = ("kedalaman orderbook" if batas_buku == n and n < modal else
            "plafon risiko" if plafon == n and n < modal else "modal")
    return n, ikat, batas_buku


def rencana(rows, modal=CAPITAL, max_pos=MAX_POS):
    """rows: daftar baris radar yang sudah lolos gate, terurut APR menurun."""
    keluar, plans = [], []
    for r in rows:
        if len(plans) >= max_pos:
            break
        sym = r["symbol"]
        try:
            cap = capacity(sym)
            n, ikat, batas_buku = ukuran(sym, modal, cap)
        except Exception as e:
            keluar.append(f"{sym}: gagal ambil orderbook ({e})")
            continue
        if n < MIN_NOTIONAL:
            keluar.append(f"{sym}: kapasitas {cap['kapasitas']:.0f} USD terlalu tipis "
                          f"(batas buku {batas_buku:.0f} USD < minimum order {MIN_NOTIONAL:.0f})")
            continue
        biaya_pct = r["carry_cost_pct"]
        biaya_usd = n * biaya_pct / 100
        apr = r["apr_7d"]
        hari = biaya_pct / (apr / 365) if apr > 0 else None
        plans.append({
            "symbol": sym, "apr_7d": apr, "apr_30d": r["apr_30d"],
            "pos_pct": r["pos_pct"], "ukuran_usd": round(n, 2), "ikat": ikat,
            "kapasitas_usd": round(cap["kapasitas"], 2),
            "batas_buku_usd": round(batas_buku, 2),
            "spot_ask": cap["spot_ask"], "perp_bid": cap["perp_bid"],
            "basis_pct": round((cap["perp_bid"] / cap["spot_ask"] - 1) * 100, 3),
            "biaya_pct": biaya_pct, "biaya_usd": round(biaya_usd, 2),
            "balik_modal_hari": round(hari, 1) if hari else None,
            "hasil_bulan": round(n * apr / 100 / 12, 2),
            "margin_perp_usd": round(n * 1.2, 2),   # 1x + buffer 20%
            "flags": r.get("flags", []),
        })
    return plans, keluar


def _commit():
    """Hash commit kode saat arsip dibuat — supaya arsip basi langsung kelihatan."""
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE,
                              capture_output=True, text=True, timeout=10).stdout.strip() or "?"
    except Exception:
        return "?"


def teks(plans, keluar, modal=CAPITAL, stamp=None):
    stamp = stamp or time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    versi = f"kode {_commit()}"
    if not plans:
        out = [f"RENCANA CARRY {stamp} ({versi})", f"Modal total: ${modal:,.0f}",
               "", "Tidak ada yang layak dieksekusi sekarang."]
        if keluar:
            out += ["", "Gugur di pemeriksaan orderbook:"] + [f"  - {k}" for k in keluar]
        out += ["", "Bertahan. Syarat: punya pasar spot, kapasitas >= $20, APR 7d >= 4%."]
        return "\n".join(out)
    out = [f"RENCANA CARRY {stamp} ({versi})", f"Modal total: ${modal:,.0f} | plafon per posisi: "
           f"${risk.batas_notional(modal):,.0f} ({risk.MAX_NOTIONAL_PCT:.0f}% modal) | "
           f"maks {risk.MAX_POSISI} posisi", ""]
    for i, p in enumerate(plans, 1):
        out += [
            f"{i}) {p['symbol']} — APR 7d {p['apr_7d']:.2f}% (30d {p['apr_30d']:.2f}%), "
            f"funding positif {p['pos_pct']:.0f}% hari",
            f"   BELI spot  : ~{p['spot_ask']:.8g} (ask)",
            f"   SHORT perp : ~{p['perp_bid']:.8g} (bid, 1x)",
            f"   Ukuran     : ${p['ukuran_usd']:,.0f} (dibatasi: {p['ikat']}; "
            f"kapasitas ${p['kapasitas_usd']:,.0f}, pakai {BOOK_USE:.0%})",
            f"   Basis saat ini: {p['basis_pct']:+.3f}% (perp vs spot)",
            f"   Biaya masuk+keluar: {p['biaya_pct']:.2f}% = ${p['biaya_usd']:,.2f}",
            f"   Balik modal: ~{p['balik_modal_hari']:.0f} hari funding "
            f"(APR {p['apr_7d']:.2f}% -> ~${p['hasil_bulan']:,.2f}/bulan)",
            f"   Siapkan margin di futures: ~${p['margin_perp_usd']:,.0f} (1x + buffer 20%)",
            "   Keluar kalau: APR 7d < 2%, basis melebar 0,5% melawan, funding 3 hari negatif, "
            "atau lewat 60 hari",
        ]
        if p["flags"]:
            out.append(f"   Catatan: {'; '.join(p['flags'])}")
        out.append("")
    if keluar:
        out += ["Gugur di pemeriksaan orderbook:"] + [f"  - {k}" for k in keluar] + [""]
    out += [
        "Cara eksekusi: beli spot lebih dulu, baru short perp dengan nominal yang sama.",
        "Batal kalau harga sudah bergeser > 0,3% dari angka di atas.",
        "Dua kaki sama besar. Kalau salah satu gagal, tutup yang sudah jalan.",
        f"Nominal ini dihitung dari kedalaman orderbook nyata, bukan dari modal. "
        f"Feenya {radar.ROUND_TRIP * 100:.1f}% sekali jalan.",
        "",
        f"Batas risiko (dipaksa di kode, lihat risk.py): leverage maks {risk.MAX_LEVERAGE:.0f}x | "
        f"plafon {risk.MAX_NOTIONAL_PCT:.0f}% modal per posisi | maks {risk.MAX_POSISI} posisi terbuka.",
        f"Kill switch harian: rugi >= {risk.KILL_SWITCH_HARIAN_PCT:.0f}% modal buku -> tutup semua. "
        f"Basis stop {risk.BASIS_STOP_PCT}% | toleransi delta dua kaki {risk.DELTA_TOLERANSI_PCT:.0f}%.",
    ]
    return "\n".join(out)


def selfcheck():
    book = {"bids": [["100.0", "10"], ["99.9", "10"]], "asks": [["100.1", "5"], ["100.2", "5"]]}
    b, a, mid = band_capacity(book)
    assert abs(mid - 100.05) < 1e-9, f"mid salah: {mid}"
    assert abs(b - 1000.0) < 1e-6, f"notional bid salah: {b}"
    # 100.1 -> 500.5 masuk; 100.2 di luar pita (batas atas 100.15005) jadi dibuang
    assert abs(a - 500.5) < 1e-6, f"notional ask salah: {a}"
    # harga di luar pita harus dibuang
    jauh = {"bids": [["100.0", "1"], ["90.0", "1000"]], "asks": [["100.0", "1"], ["110.0", "1000"]]}
    b2, a2, _ = band_capacity(jauh)
    assert b2 == 100.0 and a2 == 100.0, f"pita tidak menyaring: {b2}, {a2}"
    n, ikat, batas = ukuran("X", 1000.0, {"kapasitas": 1000.0})
    assert (n, ikat) == (100.0, "kedalaman orderbook"), f"ukuran salah: {n}, {ikat}"
    # plafon risiko 20% modal -> 200, lebih kecil dari batas buku 1000
    n2, ikat2, _ = ukuran("X", 1000.0, {"kapasitas": 10000.0})
    assert (n2, ikat2) == (200.0, "plafon risiko"), f"plafon salah: {n2}, {ikat2}"
    # modal kecil: plafon 20% dari 50 = 10
    n3, ikat3, _ = ukuran("X", 50.0, {"kapasitas": 10000.0})
    assert (n3, ikat3) == (10.0, "plafon risiko"), f"ukuran salah: {n3}, {ikat3}"
    assert abs(0.3 / (20.0 / 365) - 5.475) < 0.01, "hari balik modal salah"
    print("selfcheck OK (pita 0,1%, ukuran posisi, hari balik modal)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--capital", type=float, default=CAPITAL)
    ap.add_argument("--threshold", type=float, default=radar.ENTRY_APR)
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selfcheck()
    elif a.run:
        rows = [r for r in radar.rows_layak(a.threshold)]
        plans, keluar = rencana(rows, modal=a.capital)
        t = teks(plans, keluar, modal=a.capital)
        print(t)
        if a.send:
            print("\n-> kirim:", radar.send(t))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
