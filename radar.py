#!/usr/bin/env python3
"""Radar funding rate — pemantau peluang carry (delta-neutral), BUKAN eksekutor.

Yang dilakukan: scan perp kripto USDT terbesar, hitung APR funding trailing 7/30 hari,
ranking, tulis radar.json, dan kirim alert kalau ada yang tembus ambang.

Yang TIDAK dilakukan: tidak menyentuh saldo, tidak pasang order, tidak butuh API key.

  python3 radar.py --selftest
  python3 radar.py --run                 # sekali scan
  python3 radar.py --loop                # scan tiap 4 jam
  python3 radar.py --top 15 --threshold 10
"""
import argparse
import json
import math
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data")
OUT_JSON = os.path.join(HERE, "web", "radar.json")
FAPI = "https://fapi.binance.com"
SPOT = "https://api.binance.com"
TOPN = 60            # ambil dari perp kripto paling likuid
ENTRY_APR = 4.0      # ambang APR untuk rencana order / paper carry
ROUND_TRIP = 0.003   # biaya masuk+keluar carry (spot taker 0.1% + perp taker 0.05%, dua kali)


def get(url, cache_name=None, ttl=900):
    if cache_name:
        os.makedirs(CACHE, exist_ok=True)
        path = os.path.join(CACHE, cache_name)
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
            return json.load(open(path))
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read())
    if cache_name:
        json.dump(data, open(path, "w"))
    return data


def crypto_perps():
    """{simbol: onboardDate_ms} untuk perp kripto USDT aktif."""
    info = get(f"{FAPI}/fapi/v1/exchangeInfo", "fapi_info.json", ttl=86400)
    return {s["symbol"]: int(s.get("onboardDate") or 0) for s in info["symbols"]
            if s.get("contractType") == "PERPETUAL" and s.get("underlyingType") == "COIN"
            and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"}


def book_map():
    """{simbol: (spread_bps, notional_top_usd)} dari bookTicker (1 request per pasar)."""
    out = {}
    for url in (f"{FAPI}/fapi/v1/ticker/bookTicker",
                "https://api.binance.com/api/v3/ticker/bookTicker"):
        is_fut = "fapi" in url
        for b in get(url, None, ttl=60):
            try:
                bid, ask = float(b["bidPrice"]), float(b["askPrice"])
                if bid <= 0 or ask <= 0:
                    continue
                out[(b["symbol"], is_fut)] = (
                    (ask - bid) / ((ask + bid) / 2) * 10000,
                    bid * float(b["bidQty"]) + ask * float(b["askQty"]))
            except Exception:
                continue
    return out


def depth_usd(sym, limit=20):
    """Kedalaman orderbook 20 level teratas (perp), USD."""
    d = get(f"{FAPI}/fapi/v1/depth?symbol={sym}&limit={limit}",
            f"depth_{sym}_{int(time.time())//600}.json", ttl=600)
    return round(sum(float(p) * float(q) for p, q in d["bids"])
                 + sum(float(p) * float(q) for p, q in d["asks"]))


def gate(r, threshold, min_bond=30, max_spread=15.0, min_vol=50.0):
    """Saring koin yang APR-nya kelihatan besar tapi tidak layak dieksekusi.
    Kembalikan daftar alasan gagal; kosong = lolos."""
    bad = []
    if not r.get("has_spot"):
        bad.append("tidak ada pasar spot: carry mustahil")
    if r["apr_7d"] < threshold:
        bad.append("APR di bawah ambang")
    if r["bond_days"] < min_bond:
        bad.append(f"listing baru {r['bond_days']} hari")
    if r["spread_bps"] is None:
        bad.append("spread tidak terbaca")
    elif r["spread_bps"] > max_spread:
        bad.append(f"spread {r['spread_bps']:.1f} bps")
    if r["volume_musd"] < min_vol:
        bad.append(f"volume {r['volume_musd']:.0f} jt")
    if r["breakeven_days"] and r["breakeven_days"] <= 3:
        bad.append("balik modal <3 hari: APR tidak stabil")
    return bad


def scan(topn=TOPN, threshold=10.0):
    perps = crypto_perps()
    tickers = get(f"{FAPI}/fapi/v1/ticker/24hr", None)
    books = book_map()
    now_ms = time.time() * 1000
    ranked = sorted((t for t in tickers if t["symbol"] in perps),
                    key=lambda t: float(t["quoteVolume"]), reverse=True)[:topn]
    rows = []
    for t in ranked:
        sym = t["symbol"]
        try:
            hist = get(f"{FAPI}/fapi/v1/fundingRate?symbol={sym}&limit=90",
                       f"fr_{sym}_{int(time.time())//86400}.json", ttl=3600)
        except Exception as e:
            print(f"  lewat {sym}: {e}")
            continue
        rates = [float(h["fundingRate"]) for h in hist]
        if len(rates) < 21:
            continue
        a7 = sum(rates[-21:]) * 365 / 7 * 100
        a30 = sum(rates[-90:]) * 365 / 30 * 100
        pos = sum(1 for r in rates[-90:] if r > 0) / len(rates[-90:]) * 100
        perp_sp_read, perp_top = books.get((sym, True), (None, 0.0))
        spot_sp_read, _ = books.get((sym, False), (None, None))
        has_spot = (sym, False) in books
        bond_days = max(0, int((now_ms - perps[sym]) / 86_400_000)) if perps[sym] else 0
        # biaya carry: fee masuk+keluar + menyeberang spread di kedua kaki
        cost = ROUND_TRIP * 100
        if perp_sp_read is not None and spot_sp_read is not None:
            cost += (perp_sp_read + spot_sp_read) / 100
        be = (cost / 100 / (a7 / 100 / 365)) if a7 > 0 else None
        row = {"symbol": sym,
               "volume_musd": round(float(t["quoteVolume"]) / 1e6, 1),
               "apr_7d": round(a7, 2), "apr_30d": round(a30, 2),
               "last_bps": round(rates[-1] * 10000, 3),
               "pos_pct": round(pos, 1),
               "bond_days": bond_days,
               "has_spot": has_spot,
               "spread_bps": round(perp_sp_read, 2) if perp_sp_read is not None else None,
               "spot_spread_bps": round(spot_sp_read, 2) if spot_sp_read is not None else None,
               "book_top_usd": round(perp_top),
               "carry_cost_pct": round(cost, 3),
               "breakeven_days": round(be, 1) if be else None}
        row["flags"] = gate(row, threshold)
        row["alert"] = not row["flags"]
        rows.append(row)
    rows.sort(key=lambda r: -r["apr_7d"])
    ok = [r for r in rows if r["alert"]]
    # Kedalaman orderbook dihitung untuk 20 koin teratas (yang tampil di dashboard)
    # + semua yang lolos gate. Kalau hanya untuk yang lolos, kolom kapasitas selalu
    # kosong saat gate tipis — padahal justru di situ orang ingin tahu "muat berapa?".
    perlu = {r["symbol"] for r in rows[:20]} | {r["symbol"] for r in ok}
    for r in rows:
        r["depth_usd"] = depth_usd(r["symbol"]) if r["symbol"] in perlu else None
    payload = {"generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
               "universe": len(rows), "scanned_rank": topn, "threshold": threshold,
               "round_trip_cost_pct": ROUND_TRIP * 100,
               "gate": {"min_bond_days": 30, "max_spread_bps": 15.0, "min_volume_musd": 50.0},
               "alerts": [r["symbol"] for r in ok],
               "passed": ok,
               "rejected": [{"symbol": r["symbol"], "apr_7d": r["apr_7d"],
                             "flags": r["flags"]}
                            for r in rows if not r["alert"] and r["apr_7d"] >= threshold],
               "rows": rows}
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(payload, open(OUT_JSON, "w"), indent=2)
    return payload


ENV_FILE = os.path.join(os.path.expanduser("~"), "..", "home", ".alertbot.env")
QUEUE = os.path.join(HERE, "alert_queue.jsonl")


def _cred(name):
    """Ambil kredensial dari env, atau dari file .alertbot.env (KEY=value)."""
    if os.environ.get(name):
        return os.environ[name]
    path = os.path.abspath(ENV_FILE)
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == name:
                    return v.strip()
    return None


def _flush(tok, chat):
    """Kirim ulang alert yang tadi gagal, lalu kosongkan antrian.

    Tanpa ini antrian cuma menumpuk: pesan yang gagal waktu Telegram down tidak
    akan pernah sampai walau koneksi sudah pulih.
    """
    if not os.path.exists(QUEUE):
        return 0
    baris = [l for l in open(QUEUE).read().splitlines() if l.strip()]
    if not baris:
        return 0
    sisa, terkirim = [], 0
    for l in baris:
        try:
            data = urllib.parse.urlencode({"chat_id": chat,
                                           "text": json.loads(l)["text"]}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage",
                                   data, timeout=20)
            terkirim += 1
        except Exception:
            sisa.append(l)
    with open(QUEUE, "w") as f:
        f.write("\n".join(sisa) + ("\n" if sisa else ""))
    return terkirim


def send(text):
    """Kirim pesan ke bot alert. Kredensial tidak pernah ditulis di kode/log."""
    tok = _cred("ALERT_BOT_TOKEN") or _cred("TELEGRAM_BOT_TOKEN")
    chat = _cred("ALERT_CHAT_ID") or _cred("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return "belum dikonfigurasi: isi ALERT_BOT_TOKEN dan ALERT_CHAT_ID di ~/home/.alertbot.env"
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=20)
    except Exception as e:
        # jangan buang alert: simpan ke antrian supaya bisa dikirim ulang
        with open(QUEUE, "a") as f:
            f.write(json.dumps({"ts": time.time(), "text": text}) + "\n")
        return f"gagal kirim ({e}); disimpan ke antrian"
    # pengiriman berhasil = kesempatan kirim ulang antrian lama
    n = _flush(tok, chat)
    return f"terkirim ({n} antrian tertunda ikut dikirim)" if n else "terkirim"


def notify(payload):
    if not payload["alerts"]:
        return "tidak ada yang lolos ambang; tidak ada alert dikirim"
    baris = "\n".join(
        f"{r['symbol']}: APR {r['apr_7d']}% | balik modal {r['breakeven_days']:.0f}h | "
        f"kapasitas ${r['depth_usd']:,}" if r["depth_usd"] else
        f"{r['symbol']}: APR {r['apr_7d']}% | balik modal {r['breakeven_days']:.0f}h"
        for r in payload["passed"])
    return send(f"RADAR FUNDING {payload['generated_at']}\n"
                f"Lolos gate (ambang {payload['threshold']}%): {', '.join(payload['alerts'])}\n"
                f"{baris}\n\nCek koin ini punya pasar spot + kapasitas cukup sebelum dianggap layak.")


def rows_layak(threshold=ENTRY_APR, max_age=1800):
    """Baris radar yang lolos gate. Pakai radar.json kalau masih segar (<30 menit),
    kalau tidak pindai ulang. Gate dievaluasi ulang, tidak bergantung ambang lama."""
    path = os.path.join(HERE, "web", "radar.json")
    segar = os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age
    try:
        payload = json.load(open(path)) if segar else scan(TOPN, threshold)
    except (OSError, ValueError, KeyError):
        payload = scan(TOPN, threshold)
    return [r for r in payload["rows"] if not gate(r, threshold)]


def show(payload, top=15):
    print(f"\nRADAR FUNDING {payload['generated_at']} | {payload['universe']} koin "
          f"(dari {payload['scanned_rank']} perp terlikuid) | ambang {payload['threshold']}%")
    print(f"{'#':>3} {'simbol':<12}{'vol(jt$)':>9}{'umur':>7}{'spread':>8}"
          f"{'APR 7d':>9}{'APR 30d':>9}{'fund+':>7}{'biaya':>7}{'balik':>8}")
    for i, r in enumerate(payload["rows"][:top], 1):
        be = f"{r['breakeven_days']:.0f}h" if r["breakeven_days"] else "-"
        sp = f"{r['spread_bps']:.1f}" if r["spread_bps"] is not None else "-"
        flag = " LULUS" if r["alert"] else ""
        print(f"{i:>3} {r['symbol']:<12}{r['volume_musd']:>9.1f}{r['bond_days']:>6}h{sp:>8}"
              f"{r['apr_7d']:>8.2f}%{r['apr_30d']:>8.2f}%{r['pos_pct']:>6.0f}%"
              f"{r['carry_cost_pct']:>6.2f}%{be:>8}{flag}")
    if payload["alerts"]:
        print(f"\nLULUS gate: {', '.join(payload['alerts'])}")
        for r in payload["passed"]:
            print(f"  {r['symbol']}: likuiditas top-book ${r['book_top_usd']:,}, "
                  f"kedalaman 20 level ${r['depth_usd']:,}")
    else:
        print("\nTidak ada yang lolos gate. Carry belum layak dibuka.")
    if payload["rejected"]:
        print("\nAPR tinggi tapi GAGAL gate:")
        for r in payload["rejected"][:8]:
            print(f"  {r['symbol']:<12} {r['apr_7d']:>7.2f}%  → {'; '.join(r['flags'])}")


def loop(topn, threshold):
    while True:
        try:
            p = scan(topn, threshold)
            show(p)
            log_hasil = notify(p)
            if p["alerts"]:
                print(f"alert: {log_hasil}")
        except Exception as e:
            print(f"ERROR scan: {e}")
        time.sleep(4 * 3600)


def selfcheck():
    rates = [0.0001] * 21                       # 1 bps tiap 8 jam = 3 bps/hari
    apr = sum(rates) * 365 / 7 * 100
    assert abs(apr - 10.95) < 0.01, f"APR salah: {apr}"
    be = ROUND_TRIP / (apr / 100 / 365)
    assert abs(be - 10.0) < 0.05, f"breakeven salah: {be}"
    assert abs(sum([0.0] * 21) * 365 / 7 * 100) < 1e-12
    # gate: koin APR tinggi tapi baru listing & spread lebar harus ditolak
    bagus = {"apr_7d": 20.0, "bond_days": 400, "spread_bps": 1.0, "has_spot": True,
             "volume_musd": 500.0, "breakeven_days": 5.0}
    assert gate(bagus, 10.0) == [], "koin layak malah ditolak"
    assert gate({**bagus, "has_spot": False}, 10.0), "tanpa pasar spot harus ditolak"
    assert gate({**bagus, "bond_days": 5}, 10.0), "listing 5 hari harus ditolak"
    assert gate({**bagus, "spread_bps": 40.0}, 10.0), "spread 40 bps harus ditolak"
    assert gate({**bagus, "apr_7d": 3.0}, 10.0), "APR di bawah ambang harus ditolak"
    print(f"selfcheck OK (APR {apr:.2f}%; balik modal {be:.0f} hari; gate 4 aturan)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--test-alert", action="store_true")
    ap.add_argument("--top", type=int, default=TOPN)
    ap.add_argument("--threshold", type=float, default=10.0)
    a = ap.parse_args()
    if a.selftest:
        selfcheck()
    elif a.test_alert:
        print("uji alert:", send("Uji alert dari radar funding. Kalau pesan ini masuk, "
                                 "bot alert sudah tersambung."))
    elif a.loop:
        loop(a.top, a.threshold)
    elif a.run:
        show(scan(a.top, a.threshold), top=a.top)
    else:
        ap.print_help()
