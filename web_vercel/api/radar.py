"""Vercel serverless: scan funding APR carry dari data publik Binance.

CATATAN: aturan gate & ambang di file ini SALINAN dari ../radar.py (versi lokal).
Kalau mengubah aturan di radar.py, ubah juga di sini. Sengaja tidak diimpor supaya
fungsi Vercel tetap satu file tanpa dependensi lintas folder.

Tidak butuh API key, tidak menyentuh saldo.
"""
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler

FAPI = "https://fapi.binance.com"
SPOT = "https://api.binance.com"
ROUND_TRIP = 0.003
TOPN = int(os.environ.get("RADAR_TOP", "60"))
THRESHOLD = float(os.environ.get("RADAR_THRESHOLD", "8"))
CACHE_TTL = 300
_cache = {"t": 0.0, "payload": None}


def _get(url, timeout=20):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def gate(r, threshold=THRESHOLD, min_bond=30, max_spread=15.0, min_vol=50.0):
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


def book_map():
    out = {}
    for url, is_fut in ((f"{FAPI}/fapi/v1/ticker/bookTicker", True),
                        (f"{SPOT}/api/v3/ticker/bookTicker", False)):
        try:
            for b in _get(url):
                bid, ask = float(b["bidPrice"]), float(b["askPrice"])
                if bid <= 0 or ask <= 0:
                    continue
                out[(b["symbol"], is_fut)] = (
                    (ask - bid) / ((ask + bid) / 2) * 10000,
                    bid * float(b["bidQty"]) + ask * float(b["askQty"]))
        except Exception:
            continue
    return out


def one(row_in, books):
    ticker, onboard, depth_limit = row_in
    sym = ticker["symbol"]
    try:
        hist = _get(f"{FAPI}/fapi/v1/fundingRate?symbol={sym}&limit=90")
    except Exception:
        return None
    rates = [float(h["fundingRate"]) for h in hist]
    if len(rates) < 21:
        return None
    a7 = sum(rates[-21:]) * 365 / 7 * 100
    a30 = sum(rates[-90:]) * 365 / 30 * 100
    pos = sum(1 for r in rates[-90:] if r > 0) / len(rates[-90:]) * 100
    perp_sp, perp_top = books.get((sym, True), (None, 0.0))
    spot_sp, _ = books.get((sym, False), (None, None))
    has_spot = (sym, False) in books
    bond_days = max(0, int((time.time() * 1000 - onboard) / 86_400_000)) if onboard else 0
    cost = ROUND_TRIP * 100
    if perp_sp is not None and spot_sp is not None:
        cost += (perp_sp + spot_sp) / 100
    be = (cost / 100 / (a7 / 100 / 365)) if a7 > 0 else None
    row = {"symbol": sym, "volume_musd": round(float(ticker["quoteVolume"]) / 1e6, 1),
           "apr_7d": round(a7, 2), "apr_30d": round(a30, 2),
           "last_bps": round(rates[-1] * 10000, 3), "pos_pct": round(pos, 1),
           "bond_days": bond_days, "has_spot": has_spot,
           "spread_bps": round(perp_sp, 2) if perp_sp is not None else None,
           "spot_spread_bps": round(spot_sp, 2) if spot_sp is not None else None,
           "book_top_usd": round(perp_top), "carry_cost_pct": round(cost, 3),
           "breakeven_days": round(be, 1) if be else None}
    row["flags"] = gate(row)
    row["alert"] = not row["flags"]
    row["depth_usd"] = None
    if row["alert"] and depth_limit:
        try:
            d = _get(f"{FAPI}/fapi/v1/depth?symbol={sym}&limit=20")
            row["depth_usd"] = round(sum(float(p) * float(q) for p, q in d["bids"])
                                     + sum(float(p) * float(q) for p, q in d["asks"]))
        except Exception:
            pass
    return row


def scan(force=False):
    if not force and _cache["payload"] and time.time() - _cache["t"] < CACHE_TTL:
        return _cache["payload"]
    info = _get(f"{FAPI}/fapi/v1/exchangeInfo")
    perps = {s["symbol"]: int(s.get("onboardDate") or 0) for s in info["symbols"]
             if s.get("contractType") == "PERPETUAL" and s.get("underlyingType") == "COIN"
             and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"}
    tickers = _get(f"{FAPI}/fapi/v1/ticker/24hr")
    books = book_map()
    ranked = sorted((t for t in tickers if t["symbol"] in perps),
                    key=lambda t: float(t["quoteVolume"]), reverse=True)[:TOPN]
    jobs = [(t, perps[t["symbol"]], True) for t in ranked]
    with ThreadPoolExecutor(max_workers=16) as ex:
        rows = [r for r in ex.map(lambda j: one(j, books), jobs) if r]
    rows.sort(key=lambda r: -r["apr_7d"])
    ok = [r for r in rows if r["alert"]]
    payload = {"generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
               "universe": len(rows), "scanned_rank": TOPN, "threshold": THRESHOLD,
               "round_trip_cost_pct": ROUND_TRIP * 100,
               "gate": {"min_bond_days": 30, "max_spread_bps": 15.0, "min_volume_musd": 50.0},
               "alerts": [r["symbol"] for r in ok], "passed": ok,
               "rejected": [{"symbol": r["symbol"], "apr_7d": r["apr_7d"], "flags": r["flags"]}
                            for r in rows if not r["alert"] and r["apr_7d"] >= THRESHOLD],
               "rows": rows}
    _cache.update(t=time.time(), payload=payload)
    return payload


class handler(BaseHTTPRequestHandler):
    def _send(self, body, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "public, s-maxage=300, stale-while-revalidate=600")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/radar"):
            try:
                self._send(json.dumps(scan()).encode())
            except Exception as e:
                self._send(json.dumps({"error": str(e), "rows": []}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        """Paksa scan ulang. Dibatasi 30 detik sekali supaya tidak bisa dispam."""
        if not self.path.startswith("/api/scan"):
            self.send_response(404)
            self.end_headers()
            return
        if time.time() - _cache["t"] < 30:
            self._send(json.dumps({"ok": True, "note": "baru saja dipindai"}).encode())
            return
        try:
            scan(force=True)
            self._send(json.dumps({"ok": True}).encode())
        except Exception as e:
            self._send(json.dumps({"ok": False, "error": str(e)}).encode())
