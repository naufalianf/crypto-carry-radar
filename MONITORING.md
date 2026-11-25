# MONITORING — cara mengawasi bot tanpa menebak

Untuk Claude dan siapa pun yang mengambil alih. Tujuan dokumen ini: **satu perintah per
pertanyaan**, tanpa perlu membaca kode. Kalau angka di sini berbeda dari kenyataan,
dokumen ini yang salah — perbaiki, jangan diamkan.

Repo: `naufalianf/crypto-carry-radar` · Mesin: host Hermes (container, tanpa systemd, tanpa root)
Python: `/tmp/vlog/bin/python` · Direktori: `/opt/data/projects/crypto-bot`

---

## 1. Empat proses yang harus hidup

| Proses | Tugas | Kalau mati |
|---|---|---|
| `paper_carry.py --loop --testnet` | mesin keputusan: buka/tutup posisi | tidak ada posisi baru, tidak ada yang ditutup |
| `scan_and_push.py --loop` | pindai radar + commit snapshot | dashboard basi, `radar.json` berhenti |
| `watchdog.py --loop` | alarm kalau ada yang mati | tidak ada alarm — **satu-satunya yang tidak bisa memberi tahu kematiannya sendiri** |
| `supervisor.py --loop` | hidupkan ulang yang mati + backup state | daemon mati tidak dihidupkan lagi |

`supervisor` mengisi lubang yang dulu ada: `watchdog` hanya **memberi tahu**, tidak
menghidupkan. Supervisor memanggil `bash start_all.sh` tiap 60 detik; skrip itu sudah
idempoten, jadi aman dipanggil berulang.

Cek cepat:

```bash
cd /opt/data/projects/crypto-bot
pgrep -af "crypto-bot|paper_carry.py --loop|scan_and_push.py --loop|watchdog.py --loop|supervisor.py --loop"
python3 supervisor.py            # satu putaran: hidupkan yang mati + backup + detak
python3 watchdog.py --status     # hidup/mati + umur tiap target
```

Status yang benar: **empat baris proses**, dan `watchdog --status` menampilkan tiga target
(`paper_carry`, `scan_and_push`, `supervisor`) semuanya `hidup`.

---

## 2. Tiga "detak jantung" yang dibaca watchdog

Berkas ini ditulis tiap putaran. Umurnya yang menentukan alert.

| Berkas | Penulis | Irama | Batas dianggap mati |
|---|---|---|---|
| `web/paper.json` | `paper_carry` | tiap 4 jam | 6 jam |
| `web/radar.json` | `scan_and_push` | tiap 4 jam | 6 jam |
| `supervisor.json` | `supervisor` | tiap 60 detik | 6 menit |

Batas per-target ada di `watchdog.BATAS`. Supervisor sengaja 0,1 jam: kalau memakai 6 jam,
supervisor bisa mati 5 jam tanpa ada yang tahu.

```bash
python3 - <<'PY'
import json, calendar, time, os
for f in ("web/paper.json", "web/radar.json", "supervisor.json"):
    d = json.load(open(f))
    t = calendar.timegm(time.strptime(d["generated_at"], "%Y-%m-%d %H:%M UTC"))
    print(f"{f:<20} {d['generated_at']}  umur {(time.time()-t)/3600:.2f} jam")
PY
```

---

## 3. Backup state — ini yang menyelamatkan posisi

`paper_carry_state.json` memuat `exec.qty` dan `exec.trade_id` posisi nyata. Kalau berkas ini
hilang, bot **tidak tahu** ia punya posisi di bursa → posisi menggantung tanpa catatan.

`supervisor` menyalinnya ke `backups/` setiap isinya berubah, simpan 10 terakhir:

```bash
ls -lt backups/ | head -5
```

Pulihkan (hanya kalau state rusak/hilang):

```bash
cd /opt/data/projects/crypto-bot
bash start_all.sh stop
cp paper_carry_state.json paper_carry_state.rusak.$(date +%s)   # simpan yang rusak dulu
cp backups/state-<PILIH-YANG-BENAR>.json paper_carry_state.json
bash start_all.sh
```

**Jangan** pulihkan dari backup yang lebih tua dari posisi terakhir di bursa — bot akan
mengira tidak punya posisi, lalu membuka posisi kedua. Bandingkan dulu dengan bursa:

```bash
python3 - <<'PY'
import json, sys; sys.path.insert(0, ".")
import binance_testnet as bt
bt._muat_env(); b = bt.BinanceTestnet()
print("perp :", b.perp_short_qty())          # {simbol: qty short}, kosong = tidak ada posisi
st = json.load(open("paper_carry_state.json"))
aset = [s[:-4] for s in st["positions"]]     # ADAUSDT -> ADA
saldo = b.spot_qty()
print("spot :", {a: saldo.get(a, 0.0) for a in aset})   # hanya aset yang dipakai bot
print("state:", {k: p.get("exec", {}).get("qty") for k, p in st["positions"].items()})
PY
```

---

## 4. Tiga angka yang menentukan "sudah MVP atau belum"

```bash
python3 - <<'PY'
import json, time
st = json.load(open("paper_carry_state.json"))
now = time.time()
print("umur paper   :", round((now - st["started"]) / 3600, 1), "jam dari 720 (30 hari)")
print("closed       :", len(st["closed"]), "dari >=3")
print("posisi nyata :", sum(1 for p in st["positions"].values() if p.get("exec")), "dari MAX_EXEC_POS")
print("halt         :", st.get("halt"))
PY
```

Gerbang MVP: **umur ≥ 720 jam**, **closed ≥ 3**, **nol halt**, dan **kunci testnet sudah
diganti** setelah siklus bersih.

---

## 5. Cara Claude ikut mengawasi tanpa menjalankan apa pun

Tiga jalur, dari yang paling murah:

1. **Baca `supervisor.json` di repo?** Tidak — berkas ini runtime dan di-`.gitignore`.
   Yang di-commit hanya `web/paper.json` dan `web/radar.json` (lewat `scan_and_push`).
2. **GitHub Actions `data-segar`** — cek tiap 2 jam di server GitHub. Kalau `web/paper.json`
   atau `web/radar.json` lebih tua dari 6 jam, job **gagal** dan GitHub mengirim email.
   Ini satu-satunya alarm yang tetap hidup walau mesin Hermes mati total.
3. **GitHub Actions `uji`** — tiap push ke `main`: lima selftest + dua berkas unittest +
   pemindai kredensial. Merah = jangan deploy.

Jadi pembagian tugasnya jujur:

- Mesin Hermes mati → **Actions `data-segar`** yang tahu (email), bukan watchdog.
- Daemon mati di mesin hidup → **supervisor** menghidupkan, **watchdog** melapor ke Telegram.
- Kode rusak → **Actions `uji`** menolak sebelum masuk `main`.

---

## 6. Yang supervisor TIDAK selesaikan

Jujur di depan, supaya tidak ada harapan palsu:

- **Tidak tahan reboot.** Container ini tanpa systemd dan kita bukan root. Setelah mesin
  nyala ulang, tetap harus `bash start_all.sh` sekali. Kalau nanti pindah ke VPS dengan
  systemd, ganti supervisor dengan unit `Restart=always` — lebih benar.
- **Supervisor tidak mengawasi dirinya sendiri.** Kalau `supervisor.py` mati, `watchdog`
  melapor dalam 6 menit (target `supervisor`), tapi tidak ada yang menghidupkannya.
  Perbaikannya: jalankan `supervisor.py` dari dua tempat, atau pindahkan ke systemd.
- **Backup ada di disk yang sama.** Rusak disk = state dan backup hilang bersamaan.
  Kalau state mulai memuat posisi uang asli, backup harus keluar dari mesin ini.

---

## 7. Kalau ada yang tidak cocok

1. **Jangan hapus `execution_halt.json`.** Itu rem darurat; ada isinya berarti ada order
   yang gagal di tengah dan perlu diperiksa manual di bursa.
2. Kalau `watchdog` bilang `POSISI TIDAK COCOK`, bandingkan state vs bursa dengan skrip di
   bagian 3, **jangan** langsung tutup posisi.
3. Kalau `supervisor.json` basi > 6 menit, jalankan `python3 supervisor.py --loop` manual
   dan cek `supervisor.log`.
4. Kalau ragu: `bash start_all.sh stop`, lalu hidupkan satu per satu sambil membaca log.
   Bot berhenti tidak menghilangkan uang; bot yang salah jalan bisa.
