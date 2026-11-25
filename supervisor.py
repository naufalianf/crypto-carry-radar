#!/usr/bin/env python3
"""Penjaga daemon crypto-bot: menghidupkan ulang yang mati, mencadangkan state, dan
menulis detak jantung sendiri.

Kenapa ada: `watchdog.py` hanya MEMBERI TAHU kalau daemon mati, tidak menghidupkan.
Host ini container tanpa systemd dan tanpa root, jadi tidak ada supervisor sistem.
Proses ini mengisi lubang itu.

Cara kerja (tiap 60 detik):
  1. `bash start_all.sh` — skrip itu sudah idempoten: yang hidup dilewati, yang mati
     dinyalakan. Tidak ada logika start yang diduplikasi di sini.
  2. Cadangkan `paper_carry_state.json` ke `backups/` kalau isinya berubah (simpan 10 terakhir).
  3. Tulis `supervisor.json` — dibaca `watchdog.py`; kalau file ini basi, berarti supervisor
     sendiri mati dan Ian dapat alert Telegram.

Batas jujur: ini TIDAK tahan reboot. Container tidak punya systemd dan kita bukan root,
jadi setelah mesin nyala ulang tetap harus `bash start_all.sh` sekali. Yang supervisor
selesaikan: daemon mati di tengah jalan (OOM, exception, jaringan putus) hidup lagi sendiri
dalam 60 detik, bukan menunggu ada orang sadar.

Pakai: python3 supervisor.py --loop      (sekali: python3 supervisor.py)
Uji:   python3 supervisor.py --selftest
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "paper_carry_state.json")
HEARTBEAT = os.path.join(HERE, "supervisor.json")
BACKUP_DIR = os.path.join(HERE, "backups")
SIMPAN = 10                      # jumlah cadangan yang disimpan
JEDA = 60.0


def cadangkan(state=STATE, bak=BACKUP_DIR, simpan=SIMPAN, kini=None):
    """Salin state ke bak/ kalau isinya berubah. Nama: state-YYYYmmdd-HHMM.json.

    Hanya menyalin bila hash berbeda: tanpa ini, folder penuh salinan identik dan
    yang asli bisa tergeser keluar dari jendela `simpan`. Mengembalikan path baru
    atau None (tidak ada perubahan).
    """
    if not os.path.exists(state):
        return None
    with open(state, "rb") as f:
        isi = f.read()
    cap = hashlib.sha256(isi).hexdigest()[:16]
    os.makedirs(bak, exist_ok=True)
    terakhir = sorted(f for f in os.listdir(bak) if f.startswith("state-") and f.endswith(".json"))
    if terakhir:
        with open(os.path.join(bak, terakhir[-1]), "rb") as f:
            if hashlib.sha256(f.read()).hexdigest()[:16] == cap:
                return None
    kini = kini or time.time()
    # Detik + potongan hash: dua cadangan dalam menit yang sama tidak boleh saling menimpa.
    nama = "state-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime(kini)) + f"-{cap[:6]}.json"
    tujuan = os.path.join(bak, nama)
    with open(tujuan, "wb") as f:
        f.write(isi)
    lama = sorted(f for f in os.listdir(bak) if f.startswith("state-") and f.endswith(".json"))
    for f in lama[:-simpan]:
        os.remove(os.path.join(bak, f))
    return tujuan


def detak(path=HEARTBEAT, info=None, kini=None):
    """Tulis detak jantung atomik. `watchdog.py` membaca `generated_at` di sini."""
    kini = kini or time.time()
    data = {"generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(kini))}
    data.update(info or {})
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    return data


def jaga(skrip=None, kini=None, bak=BACKUP_DIR, state=STATE, hb=HEARTBEAT):
    """Satu putaran: hidupkan daemon yang mati, cadangkan state, tulis detak.

    Mengembalikan (keluaran start_all, path cadangan|None). start_all.sh yang menentukan
    siapa hidup dan siapa dinyalakan; kegagalannya TIDAK melempar supaya satu putaran
    gagal tidak mematikan penjaga. `bak`/`state`/`hb` bisa diarahkan agar uji tidak
    menyentuh berkas nyata.
    """
    skrip = skrip or os.path.join(HERE, "start_all.sh")
    out = ""
    rc = None
    try:
        r = subprocess.run(["bash", skrip], cwd=HERE, capture_output=True, text=True, timeout=180)
        out, rc = (r.stdout or "") + (r.stderr or ""), r.returncode
        if rc != 0:
            out += f"\n(start_all keluar {rc})"
    except (OSError, subprocess.SubprocessError) as e:
        out = f"start_all gagal: {type(e).__name__} {e}"
    b = cadangkan(state=state, bak=bak, kini=kini)
    detak(path=hb, info={"putaran": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(kini or time.time())),
                         "start_all": out.strip().splitlines()[-8:],
                         "cadangan": os.path.basename(b) if b else None}, kini=kini)
    return out, b


def loop(jeda=JEDA):
    print(f"[{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}] supervisor mulai: "
          f"putaran tiap {jeda:.0f} detik", flush=True)
    while True:
        try:
            out, bak = jaga()
            for baris in out.strip().splitlines():
                print(f"[{time.strftime('%H:%M', time.gmtime())}] {baris}", flush=True)
            if bak:
                print(f"[{time.strftime('%H:%M', time.gmtime())}] cadangan {os.path.basename(bak)}", flush=True)
        except Exception as e:                 # penjaga tidak boleh mati karena satu putaran
            print(f"putaran gagal: {type(e).__name__} {e}", flush=True)
        time.sleep(jeda)


def selftest():
    import tempfile
    d = tempfile.mkdtemp()
    st = os.path.join(d, "state.json")
    bak = os.path.join(d, "bak")
    hb = os.path.join(d, "hb.json")
    t0 = 1_800_000_000.0

    # state belum ada -> tidak ada cadangan, tidak melempar
    assert cadangkan(st, bak, kini=t0) is None

    with open(st, "w") as f:
        json.dump({"positions": {"AAA": {"exec": {"qty": 2.0}}}}, f)
    p1 = cadangkan(st, bak, kini=t0)
    assert p1 and os.path.exists(p1), "state baru harus dicadangkan"
    assert json.load(open(p1))["positions"]["AAA"]["exec"]["qty"] == 2.0, "isi harus utuh"

    # isi sama -> tidak menyalin lagi
    assert cadangkan(st, bak, kini=t0 + 60) is None, "isi identik tidak perlu salinan baru"

    # isi berubah -> salinan baru
    with open(st, "w") as f:
        json.dump({"positions": {"AAA": {"exec": {"qty": 3.0}}}}, f)
    p2 = cadangkan(st, bak, kini=t0 + 120)
    assert p2 and p2 != p1, "perubahan harus jadi salinan baru"
    assert len([f for f in os.listdir(bak) if f.startswith("state-")]) == 2

    # batas jumlah salinan
    for i in range(12):
        with open(st, "w") as f:
            json.dump({"n": i}, f)
        cadangkan(st, bak, simpan=10, kini=t0 + 200 + i)
    sisa = [f for f in os.listdir(bak) if f.startswith("state-")]
    assert len(sisa) == 10, f"harus simpan 10, dapat {len(sisa)}"
    assert json.load(open(os.path.join(bak, sorted(sisa)[-1])))["n"] == 11, "yang terbaru harus bertahan"

    # detak jantung
    detak(hb, {"x": 1}, kini=t0)
    d1 = json.load(open(hb))
    assert d1["generated_at"] == "2027-01-15 08:00 UTC" and d1["x"] == 1, d1
    detak(hb, {"x": 2}, kini=t0 + 60)
    assert json.load(open(hb))["x"] == 2, "detak harus menimpa"
    assert not os.path.exists(hb + ".tmp"), "file sementara harus hilang setelah os.replace"

    # jaga(): start_all gagal tidak melempar, detak tetap ditulis
    rusak = os.path.join(d, "rusak.sh")
    with open(rusak, "w") as f:
        f.write("exit 3\n")
    out, _ = jaga(rusak, kini=t0, bak=bak, state=st, hb=hb)
    assert "start_all" in out, out
    assert os.path.exists(hb), "detak harus tetap ditulis walau start_all gagal"

    shutil.rmtree(d, ignore_errors=True)
    print("supervisor selftest: OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--loop" in sys.argv:
        loop(float(os.environ.get("SUPERVISOR_JEDA", JEDA)))
    else:
        out, bak = jaga()
        print(out.strip() or "(tidak ada keluaran)")
        print("cadangan:", bak or "tidak berubah")
