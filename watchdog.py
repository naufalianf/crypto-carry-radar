#!/usr/bin/env python3
"""Pengecek daemon mati. Daemon yang mati tidak bisa memberi tahu dirinya sendiri, jadi
proses terpisah ini (dijalankan cron tiap 30 menit) membaca umur `generated_at` di
web/paper.json (ditulis paper_carry tiap tick) dan web/radar.json (ditulis scan_and_push).
Keduanya berdetak tiap 4 jam; lewat BATAS_JAM dianggap mati. Alert hanya saat status
BERUBAH (mati / pulih), disimpan di watchdog_state.json.

Cron contoh:  */30 * * * * cd ~/crypto-carry-radar && python3 watchdog.py
Uji:          python3 watchdog.py --selftest      Lihat status: python3 watchdog.py --status
"""
import calendar
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BATAS_JAM = 6.0          # tick 4 jam + toleransi 2 jam (scan/fetch yang lambat)
STATE = os.path.join(HERE, "watchdog_state.json")
TARGET = {"paper_carry": os.path.join(HERE, "web", "paper.json"),
          "scan_and_push": os.path.join(HERE, "web", "radar.json")}


def umur_jam(path, now):
    """Umur jam dari generated_at; None = file hilang/rusak/tanpa stempel (dianggap mati)."""
    try:
        with open(path) as f:
            gen = calendar.timegm(time.strptime(json.load(f)["generated_at"], "%Y-%m-%d %H:%M UTC"))
        return (now - gen) / 3600
    except (OSError, ValueError, KeyError, TypeError):
        return None


def periksa(now, target=None):
    """{nama: (mati?, umur_jam|None)}. Umur negatif besar (jam mundur) juga dianggap mati."""
    hasil = {}
    for nama, path in (target or TARGET).items():
        u = umur_jam(path, now)
        hasil[nama] = (u is None or u > BATAS_JAM or u < -1.0, u)
    return hasil


PAPER_STATE = os.path.join(HERE, "paper_carry_state.json")
TOL_QTY = 0.01           # selisih qty relatif yang dibiarkan (pembulatan step size)


def selisih(posisi, di_bursa, tol=TOL_QTY):
    """Bandingkan state dengan perp di bursa. Mengembalikan daftar kalimat; kosong = cocok.
    posisi: dict state["positions"]; di_bursa: {simbol: qty short}.
    Posisi paper murni (tanpa 'exec') harus NOL di bursa; posisi ber-exec harus sama qty-nya."""
    msg = []
    for sym in sorted(set(posisi) | set(di_bursa)):
        harus = float((posisi.get(sym) or {}).get("exec", {}).get("qty") or 0)
        ada = float(di_bursa.get(sym) or 0)
        if abs(ada - harus) > max(harus, ada) * tol:
            msg.append(f"{sym}: state {harus:g}, bursa {ada:g}")
    return msg


def cek_posisi(fetch=None, state_path=PAPER_STATE):
    """(bermasalah?, daftar selisih) | None bila tak bisa diperiksa (tanpa kunci / bursa tak terjangkau).
    Hanya membaca. None tidak mengubah status alert; kegagalan sementara tidak boleh membunyikan alarm."""
    st = _muat(state_path)
    if "positions" not in st:
        return None
    if fetch is None:
        try:
            import binance_testnet as bt
            bt._muat_env()
            fetch = bt.BinanceTestnet().perp_short_qty
        except Exception:
            return None                       # tanpa kunci = mode paper murni, tak ada yang direkonsiliasi
    try:
        bursa = fetch()
    except Exception:
        return None
    d = selisih(st["positions"], bursa)
    return (bool(d), d)


def _muat(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def jalankan(now=None, kirim=None, target=None, state_path=STATE, cek=cek_posisi):
    """Kirim alert untuk perubahan status. Mengembalikan daftar pesan yang dicoba kirim."""
    now = now or time.time()
    if kirim is None:
        import radar
        kirim = radar.send
    lama = _muat(state_path)
    baru, pesan = dict(lama), []
    for nama, (mati, u) in periksa(now, target).items():
        if mati and not lama.get(nama):
            ket = "file hilang/rusak" if u is None else f"terakhir berdetak {u:.1f} jam lalu"
            pesan.append(f"DAEMON MATI? {nama}: {ket} (batas {BATAS_JAM:.0f} jam). "
                         f"Cek proses di Hermes dan restart.")
        elif not mati and lama.get(nama):
            pesan.append(f"{nama} berdetak lagi (umur {u:.1f} jam).")
        baru[nama] = mati
    r = cek() if cek else None
    if r is not None:
        bad, detail = r
        if bad and not lama.get("rekonsiliasi"):
            pesan.append("POSISI TIDAK COCOK dengan bursa: " + "; ".join(detail) +
                         ". Cek exchange manual; jangan hapus execution_halt.json sebelum itu.")
        elif not bad and lama.get("rekonsiliasi"):
            pesan.append("Posisi state dan bursa cocok lagi.")
        baru["rekonsiliasi"] = bad
    for m in pesan:
        try:
            kirim(m)
        except Exception as e:
            print(f"gagal kirim: {e}")
            return pesan                      # state tidak disimpan -> dicoba lagi 30 menit lagi
    tmp = state_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(baru, f)
    os.replace(tmp, state_path)
    return pesan


def selftest():
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "x.json")
    sp = os.path.join(d, "s.json")
    tg = {"d": p}
    t0 = calendar.timegm(time.strptime("2026-01-01 12:00 UTC", "%Y-%m-%d %H:%M UTC"))

    def tulis(gen):
        with open(p, "w") as f:
            json.dump({"generated_at": gen}, f)
    kirim = []
    tulis("2026-01-01 11:00 UTC")                                   # umur 1 jam
    assert jalankan(t0, kirim.append, tg, sp, cek=None) == [], "sehat tidak mengirim"
    assert jalankan(t0 + 7 * 3600, kirim.append, tg, sp, cek=None)[0].startswith("DAEMON MATI"), "basi -> alert"
    assert jalankan(t0 + 8 * 3600, kirim.append, tg, sp, cek=None) == [], "tidak diulang selagi mati"
    tulis("2026-01-01 20:00 UTC")
    assert "berdetak lagi" in jalankan(t0 + 8.5 * 3600, kirim.append, tg, sp, cek=None)[0], "pulih -> kabar"
    assert jalankan(t0 + 9 * 3600, kirim.append, tg, sp, cek=None) == [], "pulih tidak diulang"
    os.remove(p)
    assert "hilang" in jalankan(t0 + 9 * 3600, kirim.append, tg, sp, cek=None)[0], "file hilang dianggap mati"
    with open(p, "w") as f:
        f.write("{rusak")
    assert umur_jam(p, t0) is None
    tulis("2026-01-02 12:00 UTC")                                   # jam depan 24 jam (jam mundur)
    assert periksa(t0, tg)["d"][0] is True, "stempel dari masa depan dianggap mati"
    # gagal kirim -> state tidak maju, dicoba lagi
    sp2 = os.path.join(d, "s2.json")
    tulis("2026-01-01 00:00 UTC")
    def gagal(_):
        raise OSError("down")
    jalankan(t0, gagal, tg, sp2, cek=None)
    assert not os.path.exists(sp2), "state tidak boleh tersimpan bila kirim gagal"
    assert len(jalankan(t0, kirim.append, tg, sp2, cek=None)) == 1, "dicoba lagi di putaran berikutnya"
    # rekonsiliasi posisi
    pos = {"AAA": {"exec": {"qty": 2.0}}, "BBB": {}}              # BBB = paper murni
    assert selisih(pos, {"AAA": 2.0}) == []
    assert selisih(pos, {"AAA": 2.01}) == [], "pembulatan kecil dibiarkan"
    assert len(selisih(pos, {"AAA": 2.0, "BBB": 1.0})) == 1, "paper murni tak boleh ada perp di bursa"
    assert len(selisih(pos, {})) == 1, "state ber-exec tapi bursa kosong"
    assert len(selisih(pos, {"AAA": 2.0, "CCC": 0.5})) == 1, "posisi yatim di bursa"
    sp3, ps = os.path.join(d, "s3.json"), os.path.join(d, "ps.json")
    with open(ps, "w") as f:
        json.dump({"positions": pos}, f)
    tulis("2026-01-01 11:00 UTC")
    cocok = lambda: cek_posisi(lambda: {"AAA": 2.0}, ps)
    salah = lambda: cek_posisi(lambda: {}, ps)
    assert jalankan(t0, kirim.append, tg, sp3, cek=cocok) == []
    assert "TIDAK COCOK" in jalankan(t0, kirim.append, tg, sp3, cek=salah)[0]
    assert jalankan(t0, kirim.append, tg, sp3, cek=salah) == [], "tidak diulang selagi tidak cocok"
    assert "cocok lagi" in jalankan(t0, kirim.append, tg, sp3, cek=cocok)[0]
    def putus():
        raise OSError("bursa tak terjangkau")
    assert cek_posisi(putus, ps) is None, "bursa tak terjangkau bukan alarm"
    print("watchdog selftest: OK")


def loop(jeda=1800.0):
    """Jalankan pemeriksaan berulang tanpa cron. Jeda bawaan 30 menit, sama
    dengan jadwal cron yang disarankan di docstring. Periksa langsung sekali
    saat naik (kalau daemon sudah mati, jangan tunggu 30 menit), lalu berulang."""
    print(f"[{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}] watchdog mulai: "
          f"periksa tiap {jeda/60:.0f} menit, batas {BATAS_JAM:.0f} jam", flush=True)
    while True:
        try:
            for m in jalankan():
                print(f"[{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}] {m}", flush=True)
        except Exception as e:              # jangan biarkan satu putaran mematikan pemantau
            print(f"putaran gagal: {e}", flush=True)
        time.sleep(jeda)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--status" in sys.argv:
        for n, (mati, u) in periksa(time.time()).items():
            print(f"{n:<14} {'MATI' if mati else 'hidup':<6} umur {'-' if u is None else f'{u:.1f} jam'}")
    elif "--loop" in sys.argv:
        loop()
    else:
        for m in jalankan():
            print(m)
