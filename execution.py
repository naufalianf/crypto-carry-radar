#!/usr/bin/env python3
"""Eksekusi dua kaki carry (beli spot + short perp) dengan penanganan kegagalan satu kaki.

TIDAK ada kode yang bicara ke Binance di sini. Modul ini hanya logika + antarmuka `Exchange`.
Adapter sungguhan sengaja belum ditulis; yang ada `FakeExchange` untuk uji.

Aturan keselamatan (urutannya penting):
  1. Kaki spot dulu. Kalau gagal, belum ada eksposur, selesai.
  2. Lalu short perp dengan qty = yang benar-benar terisi di spot.
  3. Kalau perp gagal / terisi sebagian, kelebihan spot DIJUAL balik. Tidak boleh ada posisi searah.
  4. Status order tidak jelas (timeout) -> tanya status; masih tidak jelas -> HALT, butuh manusia.
  5. Unwind gagal setelah beberapa percobaan -> HALT. Setelah HALT tidak ada order baru.
  6. Tiap order punya client id deterministik, jadi retry tidak bisa menggandakan order.

Catatan untuk adapter nanti: harus limit order (syarat 9 ROADMAP), cid dikirim sebagai
newClientOrderId, dan order_status harus membaca order by cid. Uji dulu di testnet.

Pakai:  python3 execution.py --selftest
"""
import csv
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HALT_FILE = os.path.join(HERE, "execution_halt.json")
FILLS_CSV = os.path.join(HERE, "execution_fills.csv")
FILLS_HEADER = ["ts", "trade_id", "leg", "side", "qty", "ref_price", "fill_price", "slip_bps", "status"]

UNWIND_TRIES = 3
STATUS_TRIES = 3
SLIP_ALARM_BPS = 15.0      # slippage lebih dari ini = catat sebagai alarm
MIN_FILL_RATIO = 0.98      # kaki dianggap terisi penuh kalau >= 98% qty


class Unknown(Exception):
    """Order dikirim tapi hasilnya tidak diketahui (timeout / koneksi putus)."""


class Rejected(Exception):
    """Exchange menolak order. Pasti tidak terisi."""


class Exchange:
    """Antarmuka minimum. Tiap metode mengembalikan (qty_terisi, harga_rata2) atau melempar
    Rejected / Unknown. `cid` = client order id; mengirim cid yang sama dua kali tidak
    boleh membuat order kedua."""

    def spot_buy(self, sym, qty, cid): raise NotImplementedError
    def spot_sell(self, sym, qty, cid): raise NotImplementedError
    def perp_short(self, sym, qty, cid): raise NotImplementedError
    def perp_buy(self, sym, qty, cid): raise NotImplementedError
    def order_status(self, cid):
        """(qty_terisi, harga) kalau order cid sudah terisi, (0, 0) kalau pasti tidak,
        atau melempar Unknown."""
        raise NotImplementedError


class HaltError(Exception):
    pass


def halt_aktif(path=None):
    path = path or HALT_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"alasan": "file halt rusak, anggap HALT"}


def set_halt(alasan, detail=None, path=None):
    path = path or HALT_FILE
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"ts": time.time(), "alasan": alasan, "detail": detail or {}}, f, indent=1)
    os.replace(tmp, path)


def reset_halt(path=None):
    path = path or HALT_FILE
    if os.path.exists(path):
        os.remove(path)


def _catat(trade_id, leg, side, qty, ref, harga, status, path=None):
    path = path or FILLS_CSV
    baru = not os.path.exists(path)
    slip = ((harga / ref - 1) * 10000 * (1 if side in ("buy",) else -1)) if ref and harga else 0.0
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if baru:
            w.writerow(FILLS_HEADER)
        w.writerow([int(time.time()), trade_id, leg, side, f"{qty:.8f}", f"{ref:.8f}",
                    f"{harga:.8f}", f"{slip:.2f}", status])
    return slip


def _kirim(ex, fn, sym, qty, cid):
    """Kirim satu order. Hasil: ('ok', qty, harga) | ('tolak',) | ('hilang',) sesudah cek status."""
    try:
        q, p = fn(sym, qty, cid)
        return ("ok", q, p)
    except Rejected:
        return ("tolak",)
    except Exception:
        # Unknown ATAU galat tak terduga (mis. KeyError saat parsing respons). Order mungkin sudah
        # masuk di exchange, jadi jangan anggap gagal: tanya status dengan cid yang sama.
        pass
    # hasil tidak jelas: jangan kirim ulang buta, tanya status dengan cid yang sama
    for _ in range(STATUS_TRIES):
        try:
            q, p = ex.order_status(cid)
            return ("ok", q, p) if q > 0 else ("tolak",)
        except Exception:
            continue
    return ("hilang",)


def _unwind(ex, fn, sym, qty, cid_dasar, trade_id, ref, side, leg, fills_path):
    """Tutup eksposur sebanyak qty. Ulang sampai UNWIND_TRIES, cid berbeda per percobaan
    KECUALI percobaan sebelumnya berstatus hilang (dicek dulu supaya tidak ganda)."""
    sisa = qty
    for i in range(UNWIND_TRIES):
        cid = f"{cid_dasar}-u{i}"
        h = _kirim(ex, fn, sym, sisa, cid)
        if h[0] == "ok":
            _catat(trade_id, leg, side, h[1], ref, h[2], f"unwind{i}", fills_path)
            sisa -= h[1]
            if sisa <= qty * (1 - MIN_FILL_RATIO) + 1e-12:
                return True
        elif h[0] == "hilang":
            return False       # tidak tahu apakah terisi; berhenti, jangan menebak
    return False


def _buka_carry(ex, sym, notional, ref_spot, ref_perp, trade_id, halt_path=None, fills_path=None):
    """Buka satu posisi carry. Mengembalikan dict hasil:
       {"status": "ok"|"gagal_bersih"|"halt", "qty":..., "spot":(q,p), "perp":(q,p), "alasan":...}
    'gagal_bersih' = tidak ada eksposur tersisa. 'halt' = ada eksposur yang tidak bisa dipastikan,
    flag halt sudah ditulis dan caller WAJIB berhenti."""
    h = halt_aktif(halt_path)
    if h:
        return {"status": "halt", "alasan": f"sudah HALT: {h.get('alasan')}"}
    if notional <= 0 or ref_spot <= 0 or ref_perp <= 0:
        return {"status": "gagal_bersih", "alasan": "input tidak valid"}

    qty = notional / ref_spot

    # --- kaki 1: spot ---
    s = _kirim(ex, ex.spot_buy, sym, qty, f"{trade_id}-spot")
    if s[0] == "tolak":
        return {"status": "gagal_bersih", "alasan": "spot ditolak, belum ada eksposur"}
    if s[0] == "hilang":
        set_halt("status order spot tidak diketahui", {"sym": sym, "trade_id": trade_id}, halt_path)
        return {"status": "halt", "alasan": "status spot tidak diketahui"}
    sq, sp = s[1], s[2]
    if sq <= 0:
        return {"status": "gagal_bersih", "alasan": "spot terisi 0"}
    _catat(trade_id, "spot", "buy", sq, ref_spot, sp, "ok", fills_path)

    # --- kaki 2: perp, qty = yang terisi di spot ---
    p = _kirim(ex, ex.perp_short, sym, sq, f"{trade_id}-perp")
    if p[0] == "hilang":
        set_halt("status order perp tidak diketahui; spot sudah terisi",
                 {"sym": sym, "trade_id": trade_id, "spot_qty": sq}, halt_path)
        return {"status": "halt", "alasan": "status perp tidak diketahui", "spot": (sq, sp)}
    pq, pp = (p[1], p[2]) if p[0] == "ok" else (0.0, 0.0)
    if pq > 0:
        _catat(trade_id, "perp", "sell", pq, ref_perp, pp, "ok", fills_path)

    # --- samakan kedua kaki ---
    if pq >= sq * MIN_FILL_RATIO:
        return {"status": "ok", "qty": min(sq, pq), "spot": (sq, sp), "perp": (pq, pp)}

    lebih = sq - pq        # spot yang tidak punya lindung nilai
    if not _unwind(ex, ex.spot_sell, sym, lebih, f"{trade_id}-spot", trade_id, ref_spot,
                   "sell", "spot", fills_path):
        set_halt("unwind spot gagal; ada eksposur searah",
                 {"sym": sym, "trade_id": trade_id, "spot_qty": lebih, "perp_qty": pq}, halt_path)
        return {"status": "halt", "alasan": "unwind spot gagal", "spot": (sq, sp), "perp": (pq, pp)}
    if pq <= 0:
        return {"status": "gagal_bersih", "alasan": "perp gagal, spot sudah dijual balik"}
    # perp terisi sebagian dan kelebihan spot sudah dijual: posisi lebih kecil tapi netral
    return {"status": "ok", "qty": pq, "spot": (pq, sp), "perp": (pq, pp), "parsial": True}


def _tutup_carry(ex, sym, qty, ref_spot, ref_perp, trade_id, halt_path=None, fills_path=None):
    """Tutup posisi: beli balik perp dulu (hilangkan risiko likuidasi), lalu jual spot.
    Kalau perp gagal ditutup, spot DIPERTAHANKAN (tetap netral) dan HALT."""
    p = _kirim(ex, ex.perp_buy, sym, qty, f"{trade_id}-perp-close")
    if p[0] != "ok" or p[1] < qty * MIN_FILL_RATIO:
        set_halt("tutup perp gagal / parsial; spot sengaja ditahan agar tetap netral",
                 {"sym": sym, "trade_id": trade_id, "qty": qty}, halt_path)
        return {"status": "halt", "alasan": "tutup perp gagal"}
    _catat(trade_id, "perp", "buy", p[1], ref_perp, p[2], "close", fills_path)
    s = _kirim(ex, ex.spot_sell, sym, qty, f"{trade_id}-spot-close")
    if s[0] != "ok" or s[1] < qty * MIN_FILL_RATIO:
        set_halt("perp sudah ditutup tetapi spot belum terjual; eksposur long",
                 {"sym": sym, "trade_id": trade_id, "qty": qty}, halt_path)
        return {"status": "halt", "alasan": "jual spot gagal setelah perp tertutup"}
    _catat(trade_id, "spot", "sell", s[1], ref_spot, s[2], "close", fills_path)
    return {"status": "ok"}


def _jaga(fn, nama):
    """Bungkus buka/tutup: galat tak terduga di mana pun = eksposur tidak dipastikan -> HALT.
    Respons order tidak boleh jadi satu-satunya bukti posisi; lebih baik berhenti daripada menggantung."""
    import inspect

    def bungkus(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:
            arg = inspect.signature(fn).bind_partial(*a, **kw).arguments
            set_halt(f"galat tak terduga di {nama}; eksposur tidak dipastikan, cek exchange manual",
                     {"sym": arg.get("sym"), "jenis": type(e).__name__}, arg.get("halt_path"))
            return {"status": "halt", "alasan": f"galat tak terduga: {type(e).__name__}"}
    bungkus.__doc__ = fn.__doc__
    return bungkus


buka_carry = _jaga(_buka_carry, "buka_carry")
tutup_carry = _jaga(_tutup_carry, "tutup_carry")


class FakeExchange(Exchange):
    """Exchange tiruan berskrip. `skrip` = {nama_metode: [aksi, ...]} dipakai berurutan,
    aksi: 'ok' | 'tolak' | 'hilang' (order masuk tapi respon hilang) | 'hilang0'
    (respon hilang dan order TIDAK masuk) | ('parsial', rasio) | ('slip', bps)."""

    def __init__(self, skrip=None, harga=100.0):
        self.skrip = {k: list(v) for k, v in (skrip or {}).items()}
        self.harga = harga
        self.orders = {}        # cid -> (qty, harga)
        self.panggilan = []     # (metode, cid, qty)
        self.status_hilang = 0  # berapa kali order_status juga akan Unknown

    def _jalan(self, nama, sym, qty, cid):
        self.panggilan.append((nama, cid, qty))
        if cid in self.orders:                      # idempoten
            return self.orders[cid]
        aksi = self.skrip.get(nama, [])
        a = aksi.pop(0) if aksi else "ok"
        px = self.harga
        if a == "tolak":
            raise Rejected("ditolak")
        if a == "hilang0":
            raise Unknown("timeout, order tidak masuk")
        if isinstance(a, tuple) and a[0] == "parsial":
            qty = qty * a[1]
        if isinstance(a, tuple) and a[0] == "slip":
            px = self.harga * (1 + a[1] / 10000)
        self.orders[cid] = (qty, px)
        if a == "hilang":
            raise Unknown("timeout, order masuk")
        if a == "bug":                              # order masuk, tetapi parsing respons meledak
            raise KeyError("avgPrice")
        return self.orders[cid]

    def spot_buy(self, sym, qty, cid): return self._jalan("spot_buy", sym, qty, cid)
    def spot_sell(self, sym, qty, cid): return self._jalan("spot_sell", sym, qty, cid)
    def perp_short(self, sym, qty, cid): return self._jalan("perp_short", sym, qty, cid)
    def perp_buy(self, sym, qty, cid): return self._jalan("perp_buy", sym, qty, cid)

    def order_status(self, cid):
        if self.status_hilang > 0:
            self.status_hilang -= 1
            raise Unknown("status tidak terjangkau")
        return self.orders.get(cid, (0.0, 0.0))

    def eksposur(self):
        """Posisi bersih tiruan: (spot_qty, perp_short_qty)."""
        spot = perp = 0.0
        for cid, (q, _) in self.orders.items():
            if "-spot-close" in cid or ("-spot" in cid and "-u" in cid):
                spot -= q
            elif cid.endswith("-spot"):
                spot += q
            elif cid.endswith("-perp"):
                perp += q
            elif cid.endswith("-perp-close"):
                perp -= q
        return spot, perp


def selfcheck():
    import test_execution
    import unittest
    r = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_execution))
    return r.wasSuccessful()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selfcheck() else 1)
    print(__doc__)
