#!/usr/bin/env python3
"""Adapter Binance TESTNET untuk execution.Exchange. Hanya stdlib.

PENGAMAN:
  - URL testnet ditulis mati di sini. Tidak ada mode live; untuk live harus menulis berkas
    baru dengan sadar, bukan mengubah satu flag.
  - Kunci dibaca dari env BINANCE_TESTNET_KEY / BINANCE_TESTNET_SECRET (nama sengaja beda
    dari kunci live, jadi kunci live yang kebetulan ada di env tidak ikut terpakai).
    Kunci tidak pernah ditulis ke log. Kunci testnet dibuat di testnet.binance.vision
    (spot) dan testnet.binancefuture.com (futures); keduanya terpisah.
  - Semua order LIMIT IOC yang menyilang buku (bukan MARKET), toleransi TOL_BPS.
  - Order hanya dipakai lewat execution.buka_carry / tutup_carry (kaki yatim, halt).

Klasifikasi galat (penting untuk keselamatan):
  - HTTP 4xx dengan kode Binance selain yang tak pasti/duplikat -> Rejected (pasti tak terisi)
  - timeout, koneksi putus, 5xx, -1006/-1007, cid duplikat      -> Unknown (execution bertanya
    status dengan cid yang sama, lalu HALT bila tetap tak jelas)

Pakai:  python3 binance_testnet.py --selftest        (tanpa jaringan)
        python3 binance_testnet.py --smoke BTCUSDT   (butuh kunci testnet; buka+tutup ~120 USDT)
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_DOWN

import execution as ex

SPOT = "https://testnet.binance.vision"
# Binance punya DUA testnet futures: yang lama (testnet.binancefuture.com) dan
# "Demo Trading API" di akun (demo-fapi.binance.com). Kunci demo hanya berlaku di
# host demo — diuji, kunci demo ditolak -2015 oleh host lama dan sebaliknya.
# Bisa ditimpa lewat env BINANCE_TESTNET_FUT_HOST untuk berpindah tanpa ubah kode.
FUT = os.environ.get("BINANCE_TESTNET_FUT_HOST", "https://demo-fapi.binance.com")
TOL_BPS = 10.0
RECV_WINDOW = 5000
UNKNOWN_CODES = {-1006, -1007, -1008, -1021}     # status tak pasti / waktu / beban
DUPLIKAT_CODES = {-2010, -4015}                  # cid sudah dipakai (spot / futures)
TIDAK_PERLU = -4046                              # margin type sudah isolated
ORDER_TIDAK_ADA = -2013


class GalatBinance(ex.Rejected):
    def __init__(self, kode, msg):
        super().__init__(f"kode {kode}: {msg}")
        self.kode = kode
        self.msg = msg


def _http(method, url, params, headers, timeout=10):
    """Transport nyata -> (status, json|None). Galat jaringan dilempar sebagai OSError."""
    data = urllib.parse.urlencode(params).encode() if method == "POST" else None
    if method != "POST" and params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None


def _floor(x, step):
    x, step = Decimal(str(x)), Decimal(str(step))
    return (x / step).to_integral_value(rounding=ROUND_DOWN) * step


class BinanceTestnet(ex.Exchange):
    def __init__(self, key=None, secret=None, http=None, now=time.time,
                 fut_key=None, fut_secret=None):
        """Kunci spot dan futures TERPISAH: Binance memisah dua testnet itu,
        kunci spot tidak berlaku di host futures (401 -2014).

        Urutan pencarian: argumen -> BINANCE_TESTNET_SPOT_KEY/SECRET ->
        BINANCE_TESTNET_KEY/SECRET (nama lama). Futures: argumen ->
        BINANCE_TESTNET_FUT_KEY/SECRET -> jatuh ke kunci spot (supaya akun yang
        kebetulan berbagi kunci tetap jalan).
        """
        e = os.environ
        self.key = key or e.get("BINANCE_TESTNET_SPOT_KEY") or e.get("BINANCE_TESTNET_KEY", "")
        self.secret = secret or e.get("BINANCE_TESTNET_SPOT_SECRET") or e.get("BINANCE_TESTNET_SECRET", "")
        self.fut_key = fut_key or e.get("BINANCE_TESTNET_FUT_KEY") or self.key
        self.fut_secret = fut_secret or e.get("BINANCE_TESTNET_FUT_SECRET") or self.secret
        if not self.key or not self.secret:
            raise RuntimeError(
                "kunci testnet belum diisi. Taruh BINANCE_TESTNET_KEY dan "
                "BINANCE_TESTNET_SECRET (spot) di ~/.testnet.env — lihat "
                "HANDOFF-HERMES.md langkah 5")
        self.http, self.now = http or _http, now
        self._cid = {}          # cid -> (pasar, simbol); order_status butuh simbol
        self._filter = {}
        self._simbol = None     # cache simbol perp (simbol_perp())

    def _kred(self, base):
        """(key, secret) untuk host tujuan. Kaki futures punya kunci sendiri."""
        return (self.fut_key, self.fut_secret) if base == FUT else (self.key, self.secret)

    # ---- transport ----
    def _req(self, base, path, params, method="GET", signed=True):
        p = dict(params)
        k, s = self._kred(base)
        if signed:
            p["timestamp"] = int(self.now() * 1000)
            p["recvWindow"] = RECV_WINDOW
            q = urllib.parse.urlencode(p)
            p["signature"] = hmac.new(s.encode(), q.encode(), hashlib.sha256).hexdigest()
        try:
            st, js = self.http(method, base + path, p, {"X-MBX-APIKEY": k})
        except OSError as e:                      # timeout / koneksi putus
            raise ex.Unknown(type(e).__name__) from None
        if st == 200:
            return js
        d = js if isinstance(js, dict) else {}
        kode = d.get("code")
        if st >= 500 or kode in UNKNOWN_CODES or kode in DUPLIKAT_CODES:
            raise ex.Unknown(f"HTTP {st} kode {kode}")
        raise GalatBinance(kode, d.get("msg", ""))

    def perp_short_qty(self):
        """{simbol: qty short} dari positionRisk. Hanya baca. Sumber kebenaran posisi, bukan respons order."""
        js = self._req(FUT, "/fapi/v2/positionRisk", {})
        return {d["symbol"]: -float(d["positionAmt"]) for d in js if float(d["positionAmt"]) != 0}

    def spot_qty(self):
        """{aset: free+locked} dari akun spot. Hanya baca. Akun testnet berisi saldo bawaan,
        jadi pemakai hanya boleh memeriksa batas bawah (kaki spot ada), bukan kesamaan."""
        js = self._req(SPOT, "/api/v3/account", {})
        return {b["asset"]: float(b["free"]) + float(b["locked"]) for b in js.get("balances", [])
                if float(b["free"]) + float(b["locked"]) > 0}

    # ---- aturan simbol & harga ----
    def simbol_perp(self):
        """Himpunan simbol yang ada di bursa perp tujuan. Di-cache: satu request per proses.
        Perlu karena testnet spot dan futures TIDAK punya daftar simbol yang sama
        (mis. OPGUSDT ada di spot, tidak ada di futures demo)."""
        if self._simbol is None:
            js = self._req(FUT, "/fapi/v1/exchangeInfo", {}, signed=False)
            self._simbol = {x["symbol"] for x in js["symbols"]}
        return self._simbol

    def _aturan(self, sym):
        if sym in self._filter:
            return self._filter[sym]
        hasil = {}
        for nama, base, path in (("spot", SPOT, "/api/v3/exchangeInfo"), ("perp", FUT, "/fapi/v1/exchangeInfo")):
            js = self._req(base, path, {"symbol": sym} if nama == "spot" else {}, signed=False)
            s = next((x for x in js["symbols"] if x["symbol"] == sym), None)
            if s is None:
                raise ex.Rejected(f"{sym} tidak ada di {nama}")
            f = {x["filterType"]: x for x in s["filters"]}
            hasil[nama] = {"step": f["LOT_SIZE"]["stepSize"], "min_qty": f["LOT_SIZE"]["minQty"],
                           "tick": f["PRICE_FILTER"]["tickSize"]}
        self._filter[sym] = hasil
        return hasil

    def qty_valid(self, sym, qty):
        """Qty yang sah di KEDUA pasar (kelipatan langkah terbesar, dibulatkan ke bawah)."""
        a = self._aturan(sym)
        step = max(Decimal(a["spot"]["step"]), Decimal(a["perp"]["step"]))
        q = _floor(qty, step)
        if q < max(Decimal(a["spot"]["min_qty"]), Decimal(a["perp"]["min_qty"])):
            raise ex.Rejected(f"qty {qty} di bawah minimum {sym}")
        return float(q)

    def setup(self, sym):
        """Perp: isolated + leverage 1x. 'sudah isolated' bukan galat; galat lain naik."""
        try:
            self._req(FUT, "/fapi/v1/marginType", {"symbol": sym, "marginType": "ISOLATED"}, "POST")
        except GalatBinance as e:
            if e.kode != TIDAK_PERLU:
                raise
        self._req(FUT, "/fapi/v1/leverage", {"symbol": sym, "leverage": 1}, "POST")

    def _harga_batas(self, pasar, sym, sisi):
        base, path = (SPOT, "/api/v3/ticker/bookTicker") if pasar == "spot" else (FUT, "/fapi/v1/ticker/bookTicker")
        js = self._req(base, path, {"symbol": sym}, signed=False)
        beli = sisi == "BUY"
        ref = Decimal(js["askPrice" if beli else "bidPrice"])
        if ref <= 0:
            raise ex.Rejected("buku kosong")
        tol = Decimal(str(TOL_BPS)) / Decimal(10000)
        tick = Decimal(self._aturan(sym)[pasar]["tick"])
        if beli:
            return str(_floor(ref * (1 + tol), tick) + tick)    # beli: pembulatan ke atas, pasti menyilang
        return str(_floor(ref * (1 - tol), tick))

    # ---- order ----
    def _order(self, pasar, sym, sisi, qty, cid, reduce=False):
        self._cid[cid] = (pasar, sym)
        p = {"symbol": sym, "side": sisi, "type": "LIMIT", "timeInForce": "IOC",
             "quantity": format(Decimal(str(self.qty_valid(sym, qty))), "f"),
             "price": self._harga_batas(pasar, sym, sisi), "newClientOrderId": cid,
             "newOrderRespType": "RESULT"}
        if reduce:
            p["reduceOnly"] = "true"
        base, path = (SPOT, "/api/v3/order") if pasar == "spot" else (FUT, "/fapi/v1/order")
        return self._hasil(pasar, self._req(base, path, p, "POST"))

    @staticmethod
    def _hasil(pasar, js):
        q = float(js.get("executedQty") or 0)
        if q <= 0:
            return 0.0, 0.0
        return q, _avg_harga(pasar, js)

    def spot_buy(self, sym, qty, cid): return self._order("spot", sym, "BUY", qty, cid)
    def spot_sell(self, sym, qty, cid): return self._order("spot", sym, "SELL", qty, cid)
    def perp_short(self, sym, qty, cid): return self._order("perp", sym, "SELL", qty, cid)
    def perp_buy(self, sym, qty, cid): return self._order("perp", sym, "BUY", qty, cid, reduce=True)

    def order_status(self, cid):
        if cid not in self._cid:
            raise ex.Unknown("cid tidak dikenal (proses restart?); periksa manual")
        pasar, sym = self._cid[cid]
        base, path = (SPOT, "/api/v3/order") if pasar == "spot" else (FUT, "/fapi/v1/order")
        try:
            js = self._req(base, path, {"symbol": sym, "origClientOrderId": cid})
        except GalatBinance as e:
            if e.kode == ORDER_TIDAK_ADA:             # order tidak ada = pasti tidak masuk
                return 0.0, 0.0
            raise ex.Unknown(str(e)) from None
        if js.get("status") in ("NEW", "PARTIALLY_FILLED") and float(js.get("executedQty") or 0) == 0:
            raise ex.Unknown("order masih terbuka")    # IOC seharusnya tidak begini; jangan menebak
        return self._hasil(pasar, js)


def _avg_harga(pasar, js):
    """Harga isi rata-rata, tahan dua bentuk respons.

    Spot (RESULT) memberi `cummulativeQuoteQty`. Futures DIDOKUMENTASIKAN memberi
    `avgPrice` untuk newOrderRespType=RESULT, tapi host demo/testnet yang diuji
    tidak mengirimnya sama sekali — hanya `price` LIMIT. Jatuh ke `cumQuote/executedQty`
    kalau ada, lalu ke `price`.
    """
    q = float(js.get("executedQty") or 0)
    if q <= 0:
        return 0.0
    cq = js.get("cummulativeQuoteQty") or js.get("cumQuote")
    if cq:
        return float(cq) / q
    if js.get("avgPrice"):
        return float(js["avgPrice"])
    # IOC limit yang FILLED terisi tepat di harga limitnya; tidak ada sumber lain.
    return float(js.get("price") or 0.0)


def _fake_http(skrip):
    """Transport tiruan: skrip = list balasan (status, json) atau Exception; mencatat panggilan."""
    log = []

    def f(method, url, params, headers):
        log.append((method, url, dict(params), dict(headers)))
        r = skrip.pop(0) if skrip else (200, {})
        if isinstance(r, Exception):
            raise r
        return r
    f.log = log
    return f


def selftest():
    import tempfile
    A = {"symbols": [{"symbol": "ABC", "filters": [
        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
        {"filterType": "PRICE_FILTER", "tickSize": "0.01"}]}]}
    F = {"symbols": [{"symbol": "ABC", "filters": [
        {"filterType": "LOT_SIZE", "stepSize": "0.01", "minQty": "0.01"},
        {"filterType": "PRICE_FILTER", "tickSize": "0.1"}]}]}
    BOOK = (200, {"askPrice": "100.00", "bidPrice": "99.90"})

    def mk(skrip):
        h = _fake_http(skrip)
        return BinanceTestnet("K", "RAHASIA123", http=h, now=lambda: 1000.0), h

    def harus(jenis, fn):
        try:
            fn()
        except jenis:
            return
        raise AssertionError(f"harus melempar {jenis.__name__}")

    harus(RuntimeError, lambda: BinanceTestnet("", ""))

    # beli spot: qty dibulatkan ke langkah terbesar (0.01), LIMIT IOC menyilang, tanda tangan benar
    b, h = mk([(200, A), (200, F), BOOK, (200, {"executedQty": "1.23", "cummulativeQuoteQty": "123.5"})])
    q, px = b.spot_buy("ABC", 1.2399, "cid1")
    assert (q, round(px, 3)) == (1.23, round(123.5 / 1.23, 3))
    m, url, p, hd = h.log[-1]
    assert url.startswith(SPOT) and m == "POST" and p["type"] == "LIMIT" and p["timeInForce"] == "IOC"
    assert p["quantity"] == "1.23" and p["newClientOrderId"] == "cid1"
    assert float(p["price"]) > 100.0, "beli harus menyilang di atas ask"
    assert hd["X-MBX-APIKEY"] == "K" and "RAHASIA123" not in json.dumps(p) and len(p["signature"]) == 64
    isi = urllib.parse.urlencode({k: v for k, v in p.items() if k != "signature"})
    assert p["signature"] == hmac.new(b"RAHASIA123", isi.encode(), hashlib.sha256).hexdigest(), "tanda tangan salah"

    # short perp di futures, harga jual di bawah bid
    b2, h2 = mk([(200, A), (200, F), BOOK, (200, {"executedQty": "1.23", "avgPrice": "99.95"})])
    assert b2.perp_short("ABC", 1.23, "c2") == (1.23, 99.95)
    assert h2.log[-1][1].startswith(FUT) and float(h2.log[-1][2]["price"]) < 99.9

    # tutup perp = reduceOnly
    b3, h3 = mk([(200, A), (200, F), BOOK, (200, {"executedQty": "1", "avgPrice": "100"})])
    b3.perp_buy("ABC", 1, "c3")
    assert h3.log[-1][2]["reduceOnly"] == "true"

    # IOC tak terisi -> (0,0), bukan galat
    b4, _ = mk([(200, A), (200, F), BOOK, (200, {"executedQty": "0", "cummulativeQuoteQty": "0"})])
    assert b4.spot_buy("ABC", 1, "c4") == (0.0, 0.0)

    # klasifikasi galat
    for balas, jenis in [((400, {"code": -1013, "msg": "x"}), ex.Rejected),
                         ((400, {"code": -2010, "msg": "dup"}), ex.Unknown),
                         ((400, {"code": -1007, "msg": "tak pasti"}), ex.Unknown),
                         ((503, None), ex.Unknown),
                         (TimeoutError("t"), ex.Unknown)]:
        bx, _ = mk([(200, A), (200, F), BOOK, balas])
        harus(jenis, lambda: bx.spot_buy("ABC", 1, "cx"))
    bx, _ = mk([(200, A), (200, F), BOOK, (400, {"code": -1013, "msg": "x"})])
    try:
        bx.spot_buy("ABC", 1, "cy")
    except ex.Unknown:
        raise AssertionError("galat 400 biasa bukan Unknown")
    except ex.Rejected:
        pass

    # qty di bawah minimum ditolak sebelum ada POST
    bm, hm = mk([(200, A), (200, F)])
    harus(ex.Rejected, lambda: bm.spot_buy("ABC", 0.001, "cm"))
    assert not [x for x in hm.log if x[0] == "POST"]

    # order_status: terisi setelah duplikat / tidak ada / cid tak dikenal / masih terbuka
    b5, _ = mk([(200, A), (200, F), BOOK, (400, {"code": -2010, "msg": "dup"}),
                (200, {"status": "FILLED", "executedQty": "1", "cummulativeQuoteQty": "100"})])
    harus(ex.Unknown, lambda: b5.spot_buy("ABC", 1, "c5"))
    assert b5.order_status("c5") == (1.0, 100.0)
    b6, _ = mk([(400, {"code": -2013, "msg": "no"})])
    b6._cid["c6"] = ("spot", "ABC")
    assert b6.order_status("c6") == (0.0, 0.0)
    harus(ex.Unknown, lambda: mk([])[0].order_status("zzz"))
    b7, _ = mk([(200, {"status": "NEW", "executedQty": "0"})])
    b7._cid["c7"] = ("perp", "ABC")
    harus(ex.Unknown, lambda: b7.order_status("c7"))
    b7b, _ = mk([(400, {"code": -1121, "msg": "simbol salah"})])
    b7b._cid["c8"] = ("perp", "ABC")
    harus(ex.Unknown, lambda: b7b.order_status("c8"))     # galat lain saat cek status = tak jelas, bukan "tidak masuk"

    # setup: 'sudah isolated' diabaikan; galat lain naik; leverage 1x
    b8, h8 = mk([(400, {"code": -4046, "msg": "No need"}), (200, {})])
    b8.setup("ABC")
    assert h8.log[-1][1].endswith("/leverage") and h8.log[-1][2]["leverage"] == 1
    b8b, _ = mk([(400, {"code": -4047, "msg": "ada posisi terbuka"})])
    harus(ex.Rejected, lambda: b8b.setup("ABC"))

    # alur penuh lewat execution.buka_carry memakai adapter + transport tiruan
    d = tempfile.mkdtemp()
    b9, _ = mk([(200, A), (200, F), BOOK, (200, {"executedQty": "1.00", "cummulativeQuoteQty": "100"}),
                BOOK, (200, {"executedQty": "1.00", "avgPrice": "99.95"})])
    r = ex.buka_carry(b9, "ABC", 100.0, 100.0, 100.0, "T9", os.path.join(d, "h"), os.path.join(d, "f.csv"))
    assert r["status"] == "ok", r
    # kunci spot vs futures dipisah: header tiap host harus memakai kuncinya sendiri
    bk, hk = mk([(200, A), (200, F)])
    bk.key, bk.secret = "KSPOT", "SSPOT"
    bk.fut_key, bk.fut_secret = "KFUT", "SFUT"
    bk._aturan("ABC")
    assert hk.log[0][3]["X-MBX-APIKEY"] == "KSPOT", "exchangeInfo spot pakai kunci spot"
    assert hk.log[1][3]["X-MBX-APIKEY"] == "KFUT", "exchangeInfo futures pakai kunci futures"
    # futures tidak mengirim avgPrice (host demo/testnet): harus jatuh ke price LIMIT
    assert _avg_harga("perp", {"executedQty": "2", "price": "99.9", "status": "FILLED"}) == 99.9
    assert _avg_harga("perp", {"executedQty": "2", "avgPrice": "100.0"}) == 100.0
    assert _avg_harga("perp", {"executedQty": "2", "cumQuote": "200"}) == 100.0
    assert _avg_harga("spot", {"executedQty": "2", "cummulativeQuoteQty": "202"}) == 101.0
    assert _avg_harga("perp", {"executedQty": "0", "price": "99.9"}) == 0.0
    hs = lambda m, u, p, hd: (200, {"balances": [{"asset": "AAA", "free": "1.5", "locked": "0.5"},
                                                {"asset": "ZZZ", "free": "0", "locked": "0"}]})
    assert BinanceTestnet("k", "s", http=hs).spot_qty() == {"AAA": 2.0}, "saldo spot: free+locked, nol dibuang"
    hp = lambda m, u, p, hd: (200, [{"symbol": "AAAUSDT", "positionAmt": "-2.5"},
                                    {"symbol": "BBBUSDT", "positionAmt": "0.000"}])
    assert BinanceTestnet("k", "s", http=hp).perp_short_qty() == {"AAAUSDT": 2.5}, "positionRisk: hanya short berisi"
    bf = BinanceTestnet("k", "s", http=lambda m, u, p, hd: (
        200, {"symbols": [{"symbol": "AAAUSDT"}, {"symbol": "BBBUSDT"}]}))
    assert bf.simbol_perp() == {"AAAUSDT", "BBBUSDT"}, "simbol_perp: daftar dari exchangeInfo"
    assert bf.simbol_perp() == {"AAAUSDT", "BBBUSDT"}, "simbol_perp: cache"
    print("binance_testnet selftest: OK")


def _muat_env(path=None):
    """Baca .testnet.env tanpa menimpa env yang sudah di-set shell.

    Kunci tidak pernah dicetak. File dicari di lokasi bawaan profil, bukan di repo,
    supaya tidak ikut ter-commit.
    """
    p = path or os.path.expanduser("~/.testnet.env")
    if not os.path.exists(p):
        p = "/opt/data/profiles/techbro-bot/home/.testnet.env"
    if not os.path.exists(p):
        return False
    with open(p) as f:
        for baris in f:
            baris = baris.strip()
            if not baris or baris.startswith("#") or "=" not in baris:
                continue
            k, v = baris.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    return True


def smoke(sym, kaki="dua"):
    """Buka lalu tutup posisi uji di testnet.

    kaki="dua"   : spot beli + perp short (butuh kunci spot DAN futures)
    kaki="spot"  : beli lalu jual di spot saja. Membuktikan tanda tangan HMAC,
                   format order, dan pembacaan respons — tanpa perlu akun Binance.
    """
    b = BinanceTestnet()
    if kaki == "spot":
        return _smoke_spot(b, sym)
    try:
        b.setup(sym)
    except GalatBinance as e:
        if e.kode in (-2015, -2014):
            print(f"KAKI FUTURES DITOLAK (kode {e.kode}): {e.msg}")
            print("Kunci spot tidak berlaku di testnet futures — Binance memisah dua akun itu.")
            print("Buat kunci di testnet.binancefuture.com lalu isi:")
            print("  BINANCE_TESTNET_FUT_KEY=...")
            print("  BINANCE_TESTNET_FUT_SECRET=...")
            print("Uji kaki spot saja dulu: --smoke SYMBOL --spot")
            return 2
        raise
    book = b._req(SPOT, "/api/v3/ticker/bookTicker", {"symbol": sym}, signed=False)
    ref = float(book["askPrice"])
    # Referensi kaki perp HARUS dari buku perp, bukan dari harga spot. Memakai harga
    # spot membuat "slip_bps" mencampur basis spot-perp dengan slippage sungguhan.
    pb = b._req(FUT, "/fapi/v1/ticker/bookTicker", {"symbol": sym}, signed=False)
    ref_perp = float(pb["bidPrice"])
    tid = f"SMOKE{int(time.time())}"
    qty = b.qty_valid(sym, 120.0 / ref)
    r = ex.buka_carry(b, sym, qty * ref, ref, ref_perp, tid)
    print("buka:", r)
    if r["status"] == "ok":
        pb2 = b._req(FUT, "/fapi/v1/ticker/bookTicker", {"symbol": sym}, signed=False)
        print("tutup:", ex.tutup_carry(b, sym, r["qty"], ref, float(pb2["askPrice"]), tid))
    print("slippage tercatat di", ex.FILLS_CSV)


def _smoke_spot(b, sym, usdt=120.0):
    """Uji kaki spot saja: beli lalu jual kembali, laporkan slippage tiap kaki."""
    js = b._req(SPOT, "/api/v3/ticker/bookTicker", {"symbol": sym}, signed=False)
    ask, bid = float(js["askPrice"]), float(js["bidPrice"])
    if ask <= 0 or bid <= 0:
        print(f"BUKU KOSONG {sym}: ask {ask} bid {bid} — testnet tidak punya likuiditas")
        return 1
    print(f"{sym}: ask {ask} bid {bid} spread {(ask/bid-1)*10000:.1f} bps | target {usdt:.0f} USDT")
    qty = b.qty_valid(sym, usdt / ask)
    if qty <= 0:
        print(f"QTY NOL: {usdt:.0f} USDT / {ask} dibulatkan ke 0 oleh step size")
        return 1
    print(f"qty: {qty} (nilai ~{qty*ask:.2f} USDT)")

    tid = f"SMOKE{int(time.time())}"
    hasil = {}
    for nama, fn, ref, sisi in (("beli", b.spot_buy, ask, "buy"), ("jual", b.spot_sell, bid, "sell")):
        cid = f"{tid}{nama[0].upper()}"
        try:
            q, h = fn(sym, qty, cid)
        except (ex.Rejected, ex.Unknown) as e:
            print(f"{nama}: GAGAL {type(e).__name__}: {e}")
            ex._catat(tid, "spot", sisi, qty, ref, 0.0, f"gagal {type(e).__name__}")
            return 1
        slip = (h / ref - 1) * 10000 if h else 0.0
        hasil[nama] = (q, h, slip)
        ex._catat(tid, "spot", sisi, q, ref, h, "ok" if q > 0 else "terisi nol")
        print(f"{nama}: qty {q} harga {h} ref {ref} slip {slip:+.2f} bps")
        if q <= 0:
            print(f"{nama}: TERISI NOL (IOC tidak dapat lawan di {ref}) — bukan galat kode")
            return 1
        time.sleep(1)

    # pastikan tidak ada sisa
    try:
        akun = b._req(SPOT, "/api/v3/account", {})
        sisa = {x["asset"]: float(x["free"]) + float(x["locked"]) for x in akun["balances"]
                if x["asset"] == sym.replace("USDT", "") and float(x["free"]) + float(x["locked"]) > 0}
    except (ex.Rejected, ex.Unknown) as e:
        sisa = f"(tidak bisa cek saldo: {e})"
    print("sisa aset:", sisa or "0 (bersih)")
    print(f"SPOT SMOKE SELESAI — slippage tercatat di {ex.FILLS_CSV}")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--smoke" in sys.argv:
        _muat_env()
        kak = "spot" if "--spot" in sys.argv else "dua"
        sys.exit(smoke(sys.argv[sys.argv.index("--smoke") + 1], kak))
    else:
        print(__doc__)
