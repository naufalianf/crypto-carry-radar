#!/usr/bin/env python3
"""Tes execution.py dengan FakeExchange berskrip. Fokus: apa pun yang gagal, tidak boleh
tersisa posisi searah tanpa HALT. Jalankan: python3 test_execution.py"""
import csv
import os
import shutil
import tempfile
import unittest

import execution as ex


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.halt = os.path.join(self.dir, "halt.json")
        self.fills = os.path.join(self.dir, "fills.csv")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def buka(self, fake, tid="T1", notional=1000.0):
        return ex.buka_carry(fake, "ABC", notional, 100.0, 100.0, tid, self.halt, self.fills)

    def tutup(self, fake, qty, tid="T1"):
        return ex.tutup_carry(fake, "ABC", qty, 100.0, 100.0, tid, self.halt, self.fills)

    def baris(self):
        with open(self.fills, newline="") as f:
            return list(csv.DictReader(f))


class Normal(Base):
    def test_dua_kaki_terisi(self):
        f = ex.FakeExchange()
        r = self.buka(f)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["qty"], 10.0)
        self.assertEqual(f.eksposur(), (10.0, 10.0))
        self.assertIsNone(ex.halt_aktif(self.halt))

    def test_slippage_tercatat_dengan_tanda_benar(self):
        f = ex.FakeExchange({"spot_buy": [("slip", 20)], "perp_short": [("slip", -10)]})
        self.buka(f)
        b = {x["leg"]: float(x["slip_bps"]) for x in self.baris()}
        self.assertAlmostEqual(b["spot"], 20.0, places=1)    # beli lebih mahal = buruk = positif
        self.assertAlmostEqual(b["perp"], 10.0, places=1)    # jual lebih murah = buruk = positif

    def test_tutup_normal_eksposur_nol(self):
        f = ex.FakeExchange()
        self.buka(f)
        self.assertEqual(self.tutup(f, 10.0)["status"], "ok")
        self.assertEqual(f.eksposur(), (0.0, 0.0))


class KakiGagal(Base):
    def test_spot_ditolak_perp_tidak_dikirim(self):
        f = ex.FakeExchange({"spot_buy": ["tolak"]})
        r = self.buka(f)
        self.assertEqual(r["status"], "gagal_bersih")
        self.assertFalse([p for p in f.panggilan if p[0] == "perp_short"])
        self.assertEqual(f.eksposur(), (0.0, 0.0))

    def test_perp_ditolak_spot_dijual_balik(self):
        f = ex.FakeExchange({"perp_short": ["tolak"]})
        r = self.buka(f)
        self.assertEqual(r["status"], "gagal_bersih")
        self.assertEqual(f.eksposur(), (0.0, 0.0))
        self.assertIsNone(ex.halt_aktif(self.halt))

    def test_perp_parsial_kelebihan_spot_dijual(self):
        f = ex.FakeExchange({"perp_short": [("parsial", 0.5)]})
        r = self.buka(f)
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r.get("parsial"))
        sp, pp = f.eksposur()
        self.assertAlmostEqual(sp, pp)         # tetap netral
        self.assertAlmostEqual(sp, 5.0)

    def test_perp_respon_hilang_tapi_order_masuk_tidak_digandakan(self):
        f = ex.FakeExchange({"perp_short": ["hilang"]})
        r = self.buka(f)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len([p for p in f.panggilan if p[0] == "perp_short"]), 1)
        self.assertEqual(f.eksposur(), (10.0, 10.0))

    def test_perp_respon_hilang_order_tidak_masuk_spot_dijual(self):
        f = ex.FakeExchange({"perp_short": ["hilang0"]})
        r = self.buka(f)
        self.assertEqual(r["status"], "gagal_bersih")
        self.assertEqual(f.eksposur(), (0.0, 0.0))

    def test_spot_parsial_perp_sebesar_spot_yang_terisi(self):
        f = ex.FakeExchange({"spot_buy": [("parsial", 0.6)]})
        r = self.buka(f)
        self.assertEqual(r["status"], "ok")
        sp, pp = f.eksposur()
        self.assertAlmostEqual(sp, 6.0)
        self.assertAlmostEqual(pp, 6.0, msg="perp harus sebesar spot yang terisi, bukan qty rencana")

    def test_retry_dengan_cid_sama_idempoten(self):
        f = ex.FakeExchange()
        a = f.spot_buy("ABC", 5, "X")
        b = f.spot_buy("ABC", 5, "X")
        self.assertEqual(a, b)
        self.assertEqual(len(f.orders), 1)


class Halt(Base):
    def test_status_perp_tidak_pernah_jelas_halt(self):
        f = ex.FakeExchange({"perp_short": ["hilang"]})
        f.status_hilang = 99
        r = self.buka(f)
        self.assertEqual(r["status"], "halt")
        self.assertIsNotNone(ex.halt_aktif(self.halt))

    def test_status_spot_tidak_jelas_halt_dan_perp_tidak_dikirim(self):
        f = ex.FakeExchange({"spot_buy": ["hilang"]})
        f.status_hilang = 99
        r = self.buka(f)
        self.assertEqual(r["status"], "halt")
        self.assertFalse([p for p in f.panggilan if p[0] == "perp_short"])

    def test_unwind_gagal_halt(self):
        f = ex.FakeExchange({"perp_short": ["tolak"], "spot_sell": ["tolak"] * 5})
        r = self.buka(f)
        self.assertEqual(r["status"], "halt")
        self.assertEqual(len([p for p in f.panggilan if p[0] == "spot_sell"]), ex.UNWIND_TRIES)

    def test_setelah_halt_tidak_ada_order_baru(self):
        ex.set_halt("uji", path=self.halt)
        f = ex.FakeExchange()
        r = self.buka(f, tid="T2")
        self.assertEqual(r["status"], "halt")
        self.assertEqual(f.panggilan, [])

    def test_file_halt_rusak_dianggap_halt(self):
        with open(self.halt, "w") as fh:
            fh.write("{rusak")
        self.assertIsNotNone(ex.halt_aktif(self.halt))
        f = ex.FakeExchange()
        self.assertEqual(self.buka(f)["status"], "halt")
        self.assertEqual(f.panggilan, [])

    def test_reset_halt_membuka_kembali(self):
        ex.set_halt("uji", path=self.halt)
        ex.reset_halt(self.halt)
        self.assertEqual(self.buka(ex.FakeExchange())["status"], "ok")


class Penutupan(Base):
    def test_tutup_perp_gagal_spot_ditahan_dan_halt(self):
        f = ex.FakeExchange()
        self.buka(f)
        f.skrip["perp_buy"] = ["tolak"]
        r = self.tutup(f, 10.0)
        self.assertEqual(r["status"], "halt")
        self.assertFalse([p for p in f.panggilan if p[0] == "spot_sell"],
                         "spot tidak boleh dijual selagi perp masih terbuka")
        self.assertEqual(f.eksposur(), (10.0, 10.0))

    def test_tutup_spot_gagal_setelah_perp_tertutup_halt(self):
        f = ex.FakeExchange()
        self.buka(f)
        f.skrip["spot_sell"] = ["tolak"]
        self.assertEqual(self.tutup(f, 10.0)["status"], "halt")
        self.assertIsNotNone(ex.halt_aktif(self.halt))

    def test_input_tidak_valid(self):
        f = ex.FakeExchange()
        self.assertEqual(ex.buka_carry(f, "ABC", 0, 100, 100, "T", self.halt, self.fills)["status"],
                         "gagal_bersih")
        self.assertEqual(f.panggilan, [])


if __name__ == "__main__":
    unittest.main()
