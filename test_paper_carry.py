#!/usr/bin/env python3
"""Test paper_carry.py yang memanggil fungsi ASLI (tick, keluar, mark, load, save, lock).

Hanya jaringan yang ditiru (harga spot/perp, funding). State, CSV, log, dan radar.json
dipindah ke folder sementara. Jalankan: python3 test_paper_carry.py  (atau --selftest).
"""
import csv
import json
import os
import shutil
import tempfile
import time
import unittest

import paper_carry as pc
import risk

H = 3600.0
T0 = 1_800_000_000.0     # waktu simulasi tetap


def row(sym, apr, has_spot=True):
    return {"symbol": sym, "apr_7d": apr, "has_spot": has_spot, "bond_days": 100,
            "spread_bps": 5.0, "volume_musd": 100.0, "carry_cost_pct": 0.3, "depth_usd": 1000,
            # Field yang dipakai radar.gate sejak gate menilai kedua kaki. Tanpa ini
            # kandidat gugur karena "tak terbaca" — fixture harus berbentuk data nyata.
            "spot_spread_bps": 5.0, "spot_vol_musd": 100.0, "breakeven_days": 10.0}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.keep = (pc.STATE, pc.TRADES, pc.LOG, pc.RADAR_JSON, pc.PAPER_JSON,
                     pc.perp_info, pc.spot_price, pc.new_funding, pc.NOTIF)
        self.pesan = []
        pc.NOTIF = lambda t: self.pesan.append(t) or "terkirim"
        pc.STATE = os.path.join(self.dir, "state.json")
        pc.TRADES = os.path.join(self.dir, "trades.csv")
        pc.LOG = os.path.join(self.dir, "log.txt")
        pc.RADAR_JSON = os.path.join(self.dir, "radar.json")
        pc.PAPER_JSON = os.path.join(self.dir, "paper.json")
        self.spot, self.perp, self.funding = {}, {}, {}
        pc.spot_price = lambda s: self.spot.get(s, 100.0)
        pc.perp_info = lambda s: {"markPrice": str(self.perp.get(s, 100.0))}
        pc.new_funding = lambda s, since: self.funding.get(s, [])

    def tearDown(self):
        (pc.STATE, pc.TRADES, pc.LOG, pc.RADAR_JSON, pc.PAPER_JSON,
         pc.perp_info, pc.spot_price, pc.new_funding, pc.NOTIF) = self.keep
        shutil.rmtree(self.dir, ignore_errors=True)

    def radar(self, rows, now, umur_jam=0.0):
        gen = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now - umur_jam * H))
        with open(pc.RADAR_JSON, "w") as f:
            json.dump({"generated_at": gen, "rows": rows}, f)

    def tick(self, now):
        return pc.tick(now)

    def csv_rows(self):
        with open(pc.TRADES, newline="") as f:
            return list(csv.reader(f))


class TestMark(Base):
    def test_delta_neutral_net_adalah_funding_dikurangi_biaya(self):
        p = {"symbol": "X", "spot_entry": 100.0, "perp_entry": 101.0, "funding": 0.02, "cost": 0.004}
        self.spot["X"], self.perp["X"] = 110.0, 111.1       # spot +10%, perp +10%
        pc.mark(p)
        self.assertAlmostEqual(p["gross"], 0.02, places=9)
        self.assertAlmostEqual(p["net"], 0.016, places=9)

    def test_basis_melebar_merugikan_short_perp(self):
        p = {"symbol": "X", "spot_entry": 100.0, "perp_entry": 100.0, "funding": 0.0, "cost": 0.0}
        self.spot["X"], self.perp["X"] = 100.0, 101.0       # perp 1% lebih mahal
        pc.mark(p)
        self.assertAlmostEqual(p["net"], -0.01, places=9)


class TestEntry(Base):
    def test_rate_limit_dua_per_tick_dan_tanpa_spot_ditolak(self):
        self.radar([row("A", 10), row("B", 9), row("C", 8), row("D", 50, has_spot=False)], T0)
        st = self.tick(T0)
        self.assertEqual(sorted(st["positions"]), ["A", "B"], "maks 2 posisi baru per tick, D tanpa spot")
        self.radar([row("A", 10), row("B", 9), row("C", 8)], T0 + 4 * H)
        st = self.tick(T0 + 4 * H)
        self.assertEqual(sorted(st["positions"]), ["A", "B", "C"])

    def test_snapshot_basi_tidak_buka_posisi(self):
        self.radar([row("A", 10)], T0, umur_jam=10)
        st = self.tick(T0)
        self.assertEqual(st["positions"], {})

    def test_radar_hilang_tidak_buka_posisi(self):
        st = self.tick(T0)
        self.assertEqual(st["positions"], {})

    def test_snapshot_basi_tidak_memicu_keluar_dari_apr_lama(self):
        self.radar([row("A", 10)], T0)
        self.tick(T0)
        self.radar([row("A", 0.5)], T0 + 8 * H, umur_jam=10)    # basi: APR rendah itu tak boleh dipercaya
        st = self.tick(T0 + 8 * H)
        self.assertIn("A", st["positions"])


class TestExit(Base):
    def test_keluar_menulis_jurnal_dengan_header_dan_kolom_sejajar(self):
        self.radar([row("A", 10)], T0)
        self.tick(T0)
        self.radar([row("A", 1.0)], T0 + 48 * H)
        st = self.tick(T0 + 48 * H)
        self.assertEqual(st["positions"], {})
        rows = self.csv_rows()
        self.assertEqual(rows[0], pc.TRADES_HEADER)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[1]), len(pc.TRADES_HEADER))
        d = dict(zip(rows[0], rows[1]))
        self.assertEqual(d["simbol"], "A")
        self.assertEqual(d["hari"], "2.00")
        self.assertEqual(d["apr_keluar_pct"], "1.0")
        self.assertTrue(d["alasan"].startswith("APR turun"))
        self.assertAlmostEqual(float(d["funding_harapan_pct"]), 10 * 2 / 365, places=3)

    def test_header_tidak_diulang(self):
        self.radar([row("A", 10), row("B", 10)], T0)
        self.tick(T0)
        self.radar([row("A", 1.0), row("B", 1.0)], T0 + 4 * H)
        self.tick(T0 + 4 * H)
        rows = self.csv_rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(1 for r in rows if r == pc.TRADES_HEADER), 1)


class TestChurn(Base):
    def test_simbol_yang_baru_keluar_ditahan_24_jam(self):
        self.radar([row("A", 10)], T0)
        self.tick(T0)
        self.radar([row("A", 1.0)], T0 + 1 * H)
        self.tick(T0 + 1 * H)                                      # A keluar
        self.radar([row("A", 10)], T0 + 2 * H)
        self.assertEqual(self.tick(T0 + 2 * H)["positions"], {}, "baru keluar 1 jam lalu")
        self.radar([row("A", 10)], T0 + 26 * H)
        self.assertIn("A", self.tick(T0 + 26 * H)["positions"], "jeda 24 jam sudah lewat")

    def test_dua_rugi_beruntun_memberi_jeda_semua_simbol(self):
        self.radar([row("A", 10), row("B", 9)], T0)
        self.tick(T0)
        self.radar([row("A", 1.0), row("B", 1.0), row("C", 10)], T0 + 4 * H)
        self.assertEqual(self.tick(T0 + 4 * H)["positions"], {}, "A dan B keluar rugi (biaya), C diblokir")
        self.radar([row("C", 10)], T0 + 8 * H)
        self.assertEqual(self.tick(T0 + 8 * H)["positions"], {}, "masih dalam jeda 24 jam")
        self.radar([row("C", 10)], T0 + 30 * H)
        self.assertIn("C", self.tick(T0 + 30 * H)["positions"])


class TestKillSwitch(Base):
    def test_halt_mengunci_lalu_reset_membuka(self):
        self.radar([row("A", 10), row("B", 9)], T0)
        self.tick(T0)
        # bangun rugi nyata: spot jatuh, perp tetap -> kaki spot rugi 2,5% + biaya 0,3% = net -2,8% per posisi ($16,8 dari 600)
        self.spot["A"] = self.spot["B"] = 97.5
        self.perp["A"] = self.perp["B"] = 100.0
        self.radar([row("A", 10), row("B", 9), row("C", 8)], T0 + 4 * H)
        st = self.tick(T0 + 4 * H)
        self.assertEqual(st["positions"], {}, "kena net stop / kill switch, semua tertutup")
        self.assertIsNotNone(st.get("halt"), "rugi 2 x $16,8 = $33,6 >= 1% dari 3000 harus mengunci")
        self.assertEqual(st["halt"]["level"], "harian")

        self.spot.clear(), self.perp.clear()
        self.radar([row("C", 8)], T0 + 40 * H)
        self.assertEqual(self.tick(T0 + 40 * H)["positions"], {}, "terkunci walau jeda sudah lewat")

        pc.reset_halt()
        self.radar([row("C", 8)], T0 + 41 * H)
        self.assertIn("C", self.tick(T0 + 41 * H)["positions"], "setelah reset boleh masuk lagi")
        self.assertIsNone(pc.load().get("halt"), "jendela dimulai ulang, tidak langsung terkunci lagi")

    def test_jendela_pnl(self):
        st = {"base_pnl": 0.0, "pnl_hist": [{"t": T0 - 8 * 86400, "pnl": 0.0},
                                            {"t": T0 - 2 * 86400, "pnl": -40.0},
                                            {"t": T0 - 3600, "pnl": -55.0}]}
        d1, d7, d30 = pc.perubahan_pnl(st, T0, -60.0)
        self.assertAlmostEqual(d1, -20.0)
        self.assertAlmostEqual(d7, -60.0)
        self.assertAlmostEqual(d30, -60.0)

    def test_kerugian_pelan_mingguan_tertangkap(self):
        # Tiap hari rugi $20 (0,67% < batas harian 1%), tapi 4 hari = $80 >= 2% mingguan ($60).
        total, hist = 0.0, []
        for h in range(5):
            hist.append({"t": T0 + h * 86400, "pnl": total})
            total -= 20.0
        st = {"base_pnl": 0.0, "pnl_hist": hist}
        d1, d7, d30 = pc.perubahan_pnl(st, T0 + 5 * 86400, total)
        level, _, _ = risk.cek_drawdown(pc.MODAL_BUKU, d1, d7, d30)
        self.assertEqual(level, "mingguan")


class TestNotif(Base):
    def cari(self, kata):
        return [t for t in self.pesan if kata in t]

    def test_masuk_dan_keluar_dikirim(self):
        self.radar([row("A", 10)], T0)
        self.tick(T0)
        self.assertEqual(len(self.cari("MASUK A")), 1)
        st = pc.load()
        pc.mark(st["positions"]["A"])
        pc.keluar(st, "A", st["positions"]["A"], "uji", T0 + H)
        self.assertEqual(len(self.cari("KELUAR A")), 1)

    def test_kill_switch_dikirim_sekali_dan_menyebut_cara_reset(self):
        self.radar([row("A", 10), row("B", 9)], T0)
        self.tick(T0)
        self.spot["A"] = self.spot["B"] = 97.5
        self.radar([row("A", 10), row("B", 9)], T0 + 4 * H)
        self.tick(T0 + 4 * H)
        self.radar([row("C", 8)], T0 + 8 * H)
        self.tick(T0 + 8 * H)
        ks = self.cari("KILL SWITCH")
        self.assertEqual(len(ks), 1, "tick berikutnya selagi HALT tidak boleh mengirim ulang")
        self.assertIn("--reset-halt", ks[0])

    def test_radar_basi_dikirim_sekali_lalu_pulih(self):
        self.radar([row("A", 10)], T0, umur_jam=10)
        self.tick(T0)
        self.radar([row("A", 10)], T0 + 4 * H, umur_jam=10)
        self.tick(T0 + 4 * H)
        self.assertEqual(len(self.cari("TIDAK BUKA POSISI")), 1, "kondisi sama tidak diulang tiap tick")
        self.radar([row("A", 10)], T0 + 8 * H)
        self.tick(T0 + 8 * H)
        self.assertEqual(len(self.cari("kembali normal")), 1)

    def test_margin_memberi_peringatan_sekali_lalu_pulih(self):
        self.radar([row("A", 10)], T0)
        self.tick(T0)
        self.spot["A"] = self.perp["A"] = 175.0      # pompa 75%: spot ikut naik, net aman, tapi short mendekati likuidasi
        self.radar([row("A", 10)], T0 + 4 * H)
        self.tick(T0 + 4 * H)
        self.tick(T0 + 5 * H)
        m = self.cari("MARGIN")
        self.assertEqual(len(m), 1, "tidak diulang selama level sama")
        self.assertIn("BAHAYA", m[0])
        self.spot["A"] = self.perp["A"] = 100.0
        self.tick(T0 + 9 * H)
        self.assertEqual(len(self.cari("Margin A kembali aman")), 1)

    def test_margin_darurat_menutup_posisi(self):
        self.radar([row("A", 10)], T0)
        self.tick(T0)
        self.spot["A"] = self.perp["A"] = 190.0      # tinggal ~4% ke likuidasi
        self.radar([row("A", 10)], T0 + 4 * H)
        st = self.tick(T0 + 4 * H)
        self.assertNotIn("A", st["positions"])
        self.assertIn("likuidasi", st["closed"][-1]["exit_reason"])

    def test_telegram_error_tidak_menggagalkan_tick(self):
        def meledak(t):
            raise OSError("telegram down")
        pc.NOTIF = meledak
        self.radar([row("A", 10)], T0)
        st = self.tick(T0)
        self.assertIn("A", st["positions"], "posisi tetap dibuka walau notifikasi gagal")


class TestExportWeb(Base):
    def test_paper_json_ringkas_dan_konsisten(self):
        self.radar([row("A", 10)], T0)
        self.tick(T0)
        self.radar([row("A", 1.0)], T0 + 48 * H)
        self.tick(T0 + 48 * H)
        with open(pc.PAPER_JSON) as f:
            d = json.load(f)
        self.assertEqual(d["n_closed"], 1)
        self.assertEqual(d["positions"], [])
        self.assertEqual(d["closed"][0]["symbol"], "A")
        self.assertAlmostEqual(d["pnl"]["total"], -1.8, places=1, msg="biaya 0,3% x 600")
        self.assertEqual(d["limits"]["harian"], risk.KILL_SWITCH_HARIAN_PCT)
        self.assertFalse(os.path.exists(pc.PAPER_JSON + ".tmp"))


class TestKetahanan(Base):
    def test_state_rusak_berhenti_dan_tidak_ditimpa(self):
        with open(pc.STATE, "w") as f:
            f.write("{bukan json")
        with self.assertRaises(RuntimeError):
            self.tick(T0)
        with open(pc.STATE) as f:
            self.assertEqual(f.read(), "{bukan json")

    def test_simpan_atomik_tanpa_sisa_tmp(self):
        self.radar([row("A", 10)], T0)
        self.tick(T0)
        self.assertFalse(os.path.exists(pc.STATE + ".tmp"))
        self.assertIn("A", pc.load()["positions"])

    def test_lock_segar_melewati_tick_lock_basi_diambil_alih(self):
        self.radar([row("A", 10)], T0)
        lock = pc.STATE + ".lock"
        open(lock, "w").close()
        self.assertIsNone(pc.tick(T0), "lock segar -> tick lain sedang jalan")
        self.assertFalse(os.path.exists(pc.STATE))
        old = time.time() - 3600
        os.utime(lock, (old, old))
        self.assertIsNotNone(pc.tick(T0), "lock basi harus diambil alih")
        self.assertFalse(os.path.exists(lock), "lock dilepas setelah tick")

    def test_gagal_nilai_satu_posisi_tidak_menggagalkan_tick(self):
        self.radar([row("A", 10), row("B", 9)], T0)
        self.tick(T0)

        def rusak(s):
            if s == "A":
                raise OSError("delisted")
            return 100.0
        pc.spot_price = rusak
        self.radar([row("A", 10), row("B", 9)], T0 + 4 * H)
        st = self.tick(T0 + 4 * H)
        self.assertEqual(sorted(st["positions"]), ["A", "B"], "A ditahan dengan angka lama, tick tetap selesai")


class TestExec(Base):
    """Eksekusi nyata (opt-in) dengan FakeExchange: kegagalan tidak boleh meninggalkan posisi gelap."""

    def setUp(self):
        super().setUp()
        import execution
        self.exm = execution
        self.keep_ex = (pc.EXCHANGE, execution.HALT_FILE, execution.FILLS_CSV)
        execution.HALT_FILE = os.path.join(self.dir, "halt.json")
        execution.FILLS_CSV = os.path.join(self.dir, "fills.csv")
        self.fake = execution.FakeExchange()
        pc.EXCHANGE = self.fake

    def tearDown(self):
        pc.EXCHANGE, self.exm.HALT_FILE, self.exm.FILLS_CSV = self.keep_ex
        super().tearDown()

    def test_masuk_membuka_dua_kaki_dan_menyimpan_exec(self):
        self.radar([row("A", 10)], T0)
        st = self.tick(T0)
        self.assertEqual(st["positions"]["A"]["exec"]["qty"], 6.0)       # 600 / 100
        self.assertEqual(self.fake.eksposur(), (6.0, 6.0))

    def test_tanpa_exchange_tidak_ada_order(self):
        pc.EXCHANGE = None
        self.radar([row("A", 10)], T0)
        st = self.tick(T0)
        self.assertNotIn("exec", st["positions"]["A"])
        self.assertEqual(self.fake.panggilan, [])

    def test_batas_posisi_nyata_max_exec_pos(self):
        """Tahap uji: hanya MAX_EXEC_POS posisi yang dikirim ke bursa; sisanya tetap paper."""
        lama = pc.MAX_EXEC_POS
        pc.MAX_EXEC_POS = 1
        try:
            self.radar([row("A", 10), row("B", 9)], T0)
            st = self.tick(T0)
            self.assertEqual(sorted(st["positions"]), ["A", "B"], "kedua posisi tetap dibuka di paper")
            self.assertIn("exec", st["positions"]["A"])
            self.assertNotIn("exec", st["positions"]["B"], "posisi kedua tidak boleh dikirim ke bursa")
            self.assertEqual(self.fake.eksposur(), (6.0, 6.0), "hanya satu kaki nyata")
        finally:
            pc.MAX_EXEC_POS = lama

    def test_gagal_bersih_tidak_membuat_posisi(self):
        self.fake.skrip["spot_buy"] = ["tolak"]
        self.radar([row("A", 10)], T0)
        st = self.tick(T0)
        self.assertEqual(st["positions"], {})
        self.assertEqual(self.fake.eksposur(), (0.0, 0.0))

    def test_halt_eksekusi_menghentikan_entri_dan_memberi_tahu_sekali(self):
        self.exm.set_halt("uji", path=self.exm.HALT_FILE)
        self.radar([row("A", 10), row("B", 9)], T0)
        st = self.tick(T0)
        self.assertEqual(st["positions"], {})
        self.assertEqual(self.fake.panggilan, [])
        self.radar([row("A", 10)], T0 + 4 * H)
        self.tick(T0 + 4 * H)
        self.assertEqual(len([m for m in self.pesan if "EXEC HALT" in m]), 1, "tidak spam")

    def test_keluar_menutup_kaki_nyata(self):
        self.radar([row("A", 10)], T0)
        self.tick(T0)
        self.radar([row("A", 1.0)], T0 + 48 * H)
        st = self.tick(T0 + 48 * H)
        self.assertEqual(st["positions"], {})
        self.assertEqual(self.fake.eksposur(), (0.0, 0.0))

    def test_tutup_gagal_posisi_tetap_terbuka_dan_dicoba_lagi(self):
        self.radar([row("A", 10)], T0)
        self.tick(T0)
        self.fake.skrip["perp_buy"] = ["tolak"]
        self.radar([row("A", 1.0)], T0 + 48 * H)
        st = self.tick(T0 + 48 * H)
        self.assertIn("A", st["positions"], "kaki nyata masih terbuka, jangan dianggap tutup")
        self.assertEqual(self.fake.eksposur(), (6.0, 6.0))
        self.assertTrue([m for m in self.pesan if "EXEC HALT" in m])
        self.radar([row("A", 1.0)], T0 + 52 * H)
        st = self.tick(T0 + 52 * H)               # percobaan kedua berhasil (cid baru)
        self.assertEqual(st["positions"], {})
        self.assertEqual(self.fake.eksposur(), (0.0, 0.0))

    def test_posisi_nyata_tanpa_exchange_tidak_ditutup_di_paper(self):
        self.radar([row("A", 10)], T0)
        self.tick(T0)
        pc.EXCHANGE = None
        self.radar([row("A", 1.0)], T0 + 48 * H)
        st = self.tick(T0 + 48 * H)
        self.assertIn("A", st["positions"])

    def test_percobaan_tutup_memakai_cid_berbeda(self):
        self.radar([row("A", 10)], T0)
        self.tick(T0)
        self.fake.skrip["perp_buy"] = ["tolak"]
        self.radar([row("A", 1.0)], T0 + 48 * H)
        self.tick(T0 + 48 * H)
        self.radar([row("A", 1.0)], T0 + 52 * H)
        self.tick(T0 + 52 * H)
        cids = [p[1] for p in self.fake.panggilan if p[0] == "perp_buy"]
        self.assertEqual(len(cids), 2)
        self.assertEqual(len(set(cids)), 2, "cid yang sama akan ditolak exchange sebagai duplikat")

    def test_halt_di_koin_pertama_menghentikan_koin_berikutnya(self):
        self.fake.skrip["spot_buy"] = ["hilang"]
        self.fake.status_hilang = 99
        self.radar([row("A", 10), row("B", 9)], T0)
        st = self.tick(T0)
        self.assertEqual(st["positions"], {})
        self.assertFalse([p for p in self.fake.panggilan if p[1].startswith("B-")], "B tidak boleh disentuh setelah HALT")

    def test_harga_entry_memakai_harga_isi(self):
        self.fake.skrip["spot_buy"] = [("slip", 50)]          # beli 0.5% lebih mahal
        self.radar([row("A", 10)], T0)
        st = self.tick(T0)
        self.assertAlmostEqual(st["positions"]["A"]["spot_entry"], 100.5, places=2)


if __name__ == "__main__":
    unittest.main()
