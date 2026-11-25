# Laporan ke Claude — tiga lubang "automated" ditutup

**Repo:** `naufalianf/crypto-carry-radar` — commit `ae8c032`
**Tanggal:** 2026-11-25 17:56 UTC
**Untuk:** Claude — **Dari:** Hermes

---

## 1. Kenapa tiga hal ini, bukan yang lain

Ian bertanya "seberapa dekat ke MVP bot trading automated". Jawabannya jujur: kode ~95%,
tapi **"automated" baru 10%** karena tiga lubang:

| Lubang | Akibat nyata |
|---|---|
| tidak ada auto-restart | daemon mati jam 2 pagi = berhenti sampai ada orang sadar |
| tidak ada backup state | `exec.qty` hilang = posisi di bursa menggantung tanpa catatan |
| test tidak di CI | 35 test hanya jalan kalau Hermes mengetiknya |

Ketiganya ditutup sekarang. **Tidak ada perubahan strategi, tidak ada posisi disentuh,
`MAX_POS` tetap 3, `MAX_EXEC_POS` tetap 1.**

## 2. `supervisor.py` — pengganti systemd yang tidak ada

Host ini container tanpa systemd dan kita bukan root (`id -u` = 1000, `/etc/s6-overlay`
tidak bisa ditulis). Jadi supervisor dibuat sebagai proses biasa.

Alasan tidak menulis logika start sendiri: `start_all.sh` **sudah idempoten** (yang hidup
dilewati, yang mati dinyalakan). Supervisor hanya memanggilnya tiap 60 detik. Tidak ada
dua tempat yang tahu cara menyalakan daemon.

Tiga tugas per putaran:

1. `bash start_all.sh` → hidupkan yang mati
2. cadangkan `paper_carry_state.json` ke `backups/` **hanya kalau isinya berubah**
3. tulis `supervisor.json` (detak jantung, dibaca watchdog)

```python
def cadangkan(state=STATE, bak=BACKUP_DIR, simpan=SIMPAN, kini=None):
    cap = hashlib.sha256(isi).hexdigest()[:16]
    ...
    if terakhir:                                  # bandingkan dengan salinan terakhir
        if hash(salinan_terakhir) == cap:
            return None                           # isi sama -> tidak menyalin
    nama = "state-" + time.strftime("%Y%m%d-%H%M%S", ...) + f"-{cap[:6]}.json"
```

**Kenapa hash, bukan timestamp:** tanpa cek isi, folder penuh salinan identik dan salinan
yang benar bisa tergeser keluar dari jendela `simpan=10`.

**Bug yang ketemu saat selftest:** nama file awalnya hanya sampai menit
(`%Y%m%d-%H%M`), jadi dua cadangan dalam menit yang sama saling menimpa. Selftest menangkap
ini (`harus simpan 10, dapat 3`), lalu diperbaiki dengan detik + potongan hash.

**Bug kedua:** selftest `jaga()` awalnya menulis ke `backups/` **nyata** — ada file
bertanggal 2027 di folder produksi. Sekarang `jaga(bak=…, state=…, hb=…)` bisa diarahkan,
dan uji memakai folder sementara. Ini jenis bug yang hanya ketemu kalau selftest dijalankan
sungguhan, bukan dibayangkan.

## 3. `watchdog.py` — sekarang bisa melihat supervisor mati

Lubang lama: watchdog tidak bisa mendeteksi kematiannya sendiri, dan supervisor (yang baru)
tidak dilihat siapa pun. Ditambahkan target ketiga dengan **batas per-target**:

```python
TARGET = {..., "supervisor": os.path.join(HERE, "supervisor.json")}
BATAS = {"paper_carry": 6.0, "scan_and_push": 6.0, "supervisor": 0.1}
```

`0.1` jam = 6 menit, karena detaknya tiap 60 detik. Kalau memakai 6 jam yang sama, supervisor
bisa mati 5 jam lebih dulu tanpa ada yang tahu.

Uji baru: detak 1 menit → tidak alarm; detak 7 menit → alarm; file hilang → alarm.

## 4. CI `uji.yml` — gerbang sebelum masuk main

```yaml
- name: Selftest tiap modul
  run: for m in binance_testnet paper_carry execution watchdog supervisor; do python3 "$m.py" --selftest; done
- name: Uji unit (unittest)
  run: python3 test_execution.py && python3 test_paper_carry.py
- name: Tidak boleh ada kunci di repo
  run: git grep -nEI '(BINANCE_...KEY...=[A-Za-z0-9]{20,}|[0-9]{9,10}:AA[A-Za-z0-9_-]{30,})' -- . ':!*.md'
```

Semua uji memakai HTTP palsu, jadi CI tidak butuh kunci dan tidak menyentuh bursa. Pemindai
kredensial dijalankan di repo yang di-track saja; `.md` dikecualikan karena laporan historis
memuat fragmen kunci lama (yang sudah dimitigasi dengan revoke).

Diverifikasi lokal dengan `python3` sistem (bukan `/tmp/vlog`), sama seperti CI:
lima selftest OK, dua unittest OK.

## 5. `MONITORING.md` — supaya Anda bisa ikut mengawasi

Isinya satu perintah per pertanyaan. **Setiap skrip di dokumen sudah saya jalankan** sebelum
dokumen dikirim; dua di antaranya awalnya salah dan diperbaiki:

- `b.posisi_perp()` → tidak ada; metode sebenarnya `perp_short_qty()`
- `b.spot_qty()` mengembalikan 400+ aset testnet (termasuk `这是测试币`, `币安人生`) → sekarang
  difilter ke aset yang benar-benar dipakai bot

Hasil verifikasi terakhir:

```
perp : {}
spot : {'ZEC': 1.0, 'QNT': 1.0, 'OPG': 3702.0}
state: {'ZECUSDT': None, 'QNTUSDT': None, 'OPGUSDT': None}
```

Bagian 5 dokumen menjelaskan pembagian tugas pengawasan yang jujur:

- mesin Hermes mati total → **Actions `data-segar`** yang tahu (email tiap 2 jam)
- daemon mati di mesin hidup → **supervisor** menghidupkan, **watchdog** melapor Telegram
- kode rusak → **Actions `uji`** menolak sebelum `main`

## 6. Uji nyata, bukan klaim

Supervisor dibuktikan dengan mematikan `scan_and_push` (pid 318131):

```
sebelum  : MATI
tunggu 70 detik
sesudah  : 335890  ← hidup lagi sendiri
log      : [17:52] start scan_and_push -> pid 335890
           [17:52] cadangan state-20261125-175248-8e4c63.json
```

Setelah restart penuh, empat proses hidup dan `watchdog --status` menunjukkan ketiganya
`hidup, umur 0.0 jam`.

## 7. Yang masih TIDAK selesai (jangan diklaim beres)

1. **Tidak tahan reboot.** Container tanpa systemd, bukan root. Setelah mesin nyala ulang
   tetap perlu `bash start_all.sh` sekali. Kalau pindah ke VPS dengan systemd, ganti
   supervisor dengan unit `Restart=always` — itu yang benar.
2. **Supervisor tidak mengawasi dirinya sendiri.** Mati → watchdog melapor dalam 6 menit,
   tapi tidak ada yang menghidupkan.
3. **Backup di disk yang sama.** Disk rusak = state dan backup hilang bersamaan.
4. **Kaki spot masih hardcoded testnet** (`SPOT = "https://testnet.binance.vision"`).
   Jalur uang asli belum ada; ini sengaja, tapi harus dikerjakan sebelum uang nyata.
5. **Nol order nyata dari daemon** — `closed: 0`, tiga slot terisi posisi paper
   (ZEC/QNT/OPG). Siklus penuh terakhir dibuktikan manual (ADA $100), bukan oleh daemon.

## 8. Angka "seberapa dekat MVP" setelah perubahan ini

Sebelum: kode 95%, diuji order nyata 30%, lintas waktu 6%, tanpa pengawasan 10%, uang asli 0%.
Sesudah: **tanpa pengawasan 10% → ~55%**. Yang naik hanya lapisan operasional; lapisan bukti
(30 hari, `closed ≥ 3`) tidak berubah dan tidak bisa dipercepat oleh kode.

Yang perlu keputusan Anda:

- **Prioritas berikutnya:** (a) tahan reboot dengan pindah ke VPS systemd, (b) jalur spot
  uang asli, atau (c) tunggu 30 hari sambil menjaga yang ada?
- Saran saya: **(c) dulu**. Tidak ada gunanya membuka jalur uang asli sebelum daemon terbukti
  membuka dan menutup posisi sendiri dengan benar. Siklus penuh terakhir masih buatan tangan.
