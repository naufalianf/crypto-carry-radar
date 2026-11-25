# Panduan End-to-End: Crypto Carry Radar

**Untuk:** Ian (pemilik proyek)
**Tanggal:** 25 November 2026
**Status:** tahap uji di **testnet/demo**. Belum ada uang sungguhan. Tidak ada kode untuk akun live.

Cara baca: istilah teknis tetap dipakai, tapi setiap istilah dijelaskan satu kali dengan
perumpamaan pendek. Kalau perumpamaannya tidak membantu, abaikan dan baca kalimat teknisnya.

---

## 1. Satu kalimat

Sistem ini mencari koin yang **funding rate**-nya tinggi, lalu mengambil funding itu
tanpa bertaruh pada arah harga. Caranya: **beli spot + short perp**, jumlahnya sama, leverage 1x.

---

## 2. Istilah yang dipakai (baca sekali)

| Istilah | Artinya | Perumpamaan |
|---|---|---|
| **Spot** | Beli koin sungguhan, koinnya masuk ke akun | Beli emas batangan di toko |
| **Perp (perpetual futures)** | Kontrak harga koin, tanpa memegang koinnya | Taruhan harga emas, tanpa emasnya |
| **Short** | Posisi yang untung kalau harga turun | Pasang taruhan "harga akan turun" |
| **Funding rate** | Uang yang saling dibayar pemegang long dan short perp, tiap 8 jam | Iuran antar dua kubu. Kalau kubu long lebih ramai, mereka yang membayar kubu short |
| **Delta-netral** | Spot dan short sama besar, jadi harga naik atau turun hasilnya sama-sama nol | Dua sisi timbangan yang seimbang |
| **Carry** | Penghasilan dari sekadar memegang posisi | Uang sewa rumah |
| **APR** | Funding disetahunkan, dalam persen | Bunga deposito per tahun |
| **Notional** | Nilai satu posisi dalam dolar. Di sini 600 | Besar satu kontrak |
| **Basis** | Selisih harga spot dan perp. Kalau melebar melawan kita, kita rugi | Dua meja harganya mulai berbeda |
| **Slippage** | Harga yang kita dapat meleset dari harga yang terlihat | Antre lama, harganya sudah berubah |
| **Testnet / demo** | Bursa latihan, uangnya bohongan | Simulator mengemudi |
| **Paper** | Posisi yang hanya dicatat di file, tidak dikirim ke bursa mana pun | Latihan di atas kertas |
| **HALT** | Bot berhenti sendiri karena ada yang janggal | Rem darurat |
| **Kill switch** | Rem darurat karena rugi terlalu besar: 1% per hari, 2% per 7 hari, 3% per 30 hari | Sekering listrik |
| **Reconcile (rekonsiliasi)** | Mencocokkan catatan bot dengan isi akun bursa yang asli | Mencocokkan buku kas dengan saldo rekening |

---

## 3. Siapa melakukan apa

Ada tiga hal yang sering tertukar. Ini pembagiannya.

```
 BURSA BINANCE ──data pasar──▶  BOT RADAR  ──hasil scan──▶  GITHUB  ──▶  DASHBOARD (Vercel)
 (testnet/demo)                 (radar.py)                  (web/*.json)   (yang Anda lihat)
      ▲                                                         ▲
      │ order (hanya mode --testnet)                            │
      │                                                         │
  BOT TRADING  ◀── dijalankan & dijaga oleh ──  HERMES ─────────┘
 (paper_carry.py)                            (agent di mesin Hermes)
```

### 3.1 Bot radar (`radar.py`, `scan_and_push.py`)
- **Tugas:** memindai ±60 koin, menghitung APR funding 7 hari dan 30 hari, spread, volume.
- **Keluaran:** file `web/radar.json`.
- **Tidak pernah** membuka posisi. Hanya melihat dan melaporkan.
- `scan_and_push.py` men-commit file itu ke GitHub tiap 4 jam supaya dashboard punya data baru.

### 3.2 Bot trading (`paper_carry.py`)
- **Tugas:** membaca hasil radar, memutuskan masuk dan keluar posisi, mencatat untung-rugi.
- Jalan tiap 4 jam (satu "tick").
- Ada dua mode:
  - **Tanpa `--testnet`:** semua posisi hanya paper.
  - **Dengan `--testnet`:** posisi dikirim ke bursa demo sebagai order nyata. Dibatasi `MAX_EXEC_POS=1`, jadi baru 1 posisi yang benar-benar dikirim, sisanya tetap paper.
- Keluaran: `web/paper.json` dan file state.

### 3.3 Watchdog (`watchdog.py`)
- **Tugas:** satpam. Mengecek apakah data masih segar dan apakah catatan bot cocok dengan isi akun bursa (`cek_posisi()`).
- Hanya memberi **peringatan**, tidak mengubah apa pun.

### 3.4 Hermes
- **Bukan bot trading.** Hermes adalah agent AI Anda yang **menjalankan dan menjaga** ketiga proses di atas di mesinnya.
- Hermes yang menyalakan daemon (`start_all.sh`), men-pull kode terbaru, menjalankan tes, dan melapor.
- Hermes **memegang kunci API** testnet. Saya (Claude) tidak pernah menyentuhnya.

### 3.5 Dashboard (Vercel)
- **Tugas:** hanya **menampilkan**. Tidak bisa membeli atau menjual, dan tidak bisa memanggil Binance (Binance memblokir IP cloud dengan error 451).
- Datanya diambil dari GitHub tiap 3 menit. Jadi dashboard **tidak pernah lebih baru dari file di GitHub**, dan file itu hanya diperbarui kalau mesin Hermes hidup.
- Kalau data lebih tua dari batas tertentu, muncul titik dan banner "stale".

### 3.6 Claude (saya)
- Meninjau dan menambal kode, memperbaiki dashboard, menulis catatan serah-terima ke Hermes.
- Tidak menjalankan bot dan tidak punya akses ke kunci.

### 3.7 GitHub Actions (`data-segar.yml`)
- Tiap 2 jam mengecek umur data. Kalau data lebih tua dari 6 jam, job gagal dan GitHub mengirim email ke pemilik repo. Ini alarm kalau mesin Hermes mati.

---

## 4. Alur satu siklus (apa yang terjadi tiap 4 jam)

1. `scan_and_push` memindai Binance, menulis `radar.json`, push ke GitHub.
2. `paper_carry` membaca `radar.json`. Kalau umur data lebih dari 6 jam, **tidak membuka posisi baru** (fail closed).
3. Untuk posisi yang sudah terbuka: bot mengecek apakah harus keluar.
4. Untuk posisi baru: koin harus lolos semua syarat ini:
   - APR 7 hari **≥ 4,0%** (`ENTRY_APR`)
   - punya pasar spot
   - umur data funding ≥ 30 hari
   - spread ≤ 15 bps
   - volume ≥ $50 juta
5. Slot harus kosong (maks 3 posisi, 600 per posisi, total 1.800 dari modal buku 3.000).
6. Posisi dicatat. Di mode `--testnet`, bot mengirim **kaki spot dulu, lalu kaki perp**. Kalau kaki kedua gagal, kaki pertama dibatalkan (unwind).
7. Setelah itu `paper.json` ditulis, di-push, dan dashboard menampilkannya.

**Kapan posisi ditutup:**
- APR 7 hari turun di bawah 2,0% (`EXIT_APR`)
- umur lebih dari 60 hari (`MAX_DAYS`)
- basis melawan terlalu jauh
- kerugian bersih melewati batas di `risk.py`
- kill switch menyala

---

## 5. Cara membaca dashboard

Alamat: https://crypto-carry-radar-webvercel.vercel.app/

| Bagian | Isinya | Yang perlu Anda perhatikan |
|---|---|---|
| **Titik status** | Hijau = data segar, merah/abu = stale | Kalau merah, mesin Hermes kemungkinan mati. Lihat bagian 8 |
| **Scorecard** | Ringkasan: posisi terbuka, untung-rugi, umur uji | Angka di sini masih **paper**, bukan uang |
| **Tabel radar** | Koin-koin teratas beserta APR 7d, APR 30d, spread, volume | Kolom **tren 30h**: garis mini funding harian. Hijau = terakhir positif, merah = negatif |
| **Gate** | Syarat untuk lanjut ke tahap berikutnya | Lihat bagian 7 |
| **Kurva** | Grafik hasil paper dari waktu ke waktu | Belum bermakna sampai ada beberapa hari data |

Catatan: kolom "tren 30h" baru terisi setelah scan radar berikutnya di mesin Hermes.

---

## 6. Rutinitas Anda sehari-hari (5 menit)

1. Buka dashboard. Titik status hijau? Kalau tidak, ke bagian 8.
2. Lihat apakah ada banner peringatan atau notifikasi Telegram `EXEC HALT`.
3. Selesai. Sisanya biarkan berjalan.

**Yang tidak perlu Anda lakukan:** menyentuh kode, kunci API, atau file `execution_halt.json`.

**Yang Hermes lakukan setiap hari** dan melaporkannya ke Anda:
- ada tidaknya `execution_halt.json`
- hasil `cek_posisi()`: harus `(False, [])` artinya catatan cocok dengan bursa
- slippage order yang sudah terjadi

---

## 7. Peta tahap: kita di mana, apa yang ditunggu

| Tahap | Isi | Status |
|---|---|---|
| **1. Paper** | Bot jalan, hanya mencatat | Berjalan |
| **2. Testnet** | Order nyata di bursa demo | Menyala, **belum ada order nyata**: ketiga slot masih terisi posisi paper |
| **3. Live kecil** | Uang sungguhan, nominal kecil | **Belum ada kode. Belum boleh.** |

**Gerbang untuk lanjut dari Tahap 2** (tidak bisa dipercepat):
- paper jalan **≥ 30 hari** (sekarang ±34 jam)
- selisih pencatatan funding vs bursa **< 0,20%**
- **≥ 3 posisi tertutup penuh** (sekarang 0)
- sekitar 2 minggu testnet tanpa HALT yang tak terjelaskan

Yang sedang ditunggu sekarang: satu posisi paper tutup secara alami (APR turun di bawah 2%), supaya slot kosong dan order testnet pertama bisa terkirim. Itu keputusan Anda: **jangan tutup paksa**.

---

## 8. Kalau ada masalah

| Gejala | Kemungkinan sebab | Tindakan |
|---|---|---|
| Titik dashboard merah, banner stale | Mesin Hermes mati atau `scan_and_push` berhenti | Minta Hermes cek proses (`start_all.sh`) |
| Email dari GitHub "data tidak segar" | Sama seperti di atas, data lebih dari 6 jam | Sama |
| Telegram `EXEC HALT` | Satu kaki order gagal, atau hasil order tidak jelas | **Berhenti. Jangan hapus `execution_halt.json`.** Hermes cek akun bursa secara manual dulu, baru reset |
| Watchdog melaporkan posisi tidak cocok | Catatan bot dan isi bursa berbeda | Hermes selidiki sebelum apa pun dijalankan lagi |
| Kill switch menyala | Rugi melewati 1% per hari, 2% per 7 hari, atau 3% per 30 hari | Bot berhenti membuka posisi. Reset hanya setelah ditinjau |
| Browser memperingatkan sertifikat/HSTS | Masalah di sisi jaringan atau browser | **Jangan abaikan peringatannya.** Ganti jaringan atau tanya saya |

Prinsip: **gagal dengan keras lebih baik daripada gagal diam-diam.** Kalau ragu, bot berhenti dan bertanya.

---

## 9. Batas keamanan (tidak boleh diubah demi kecepatan)

- Hanya testnet/demo. Tidak ada kode untuk akun live.
- Kunci API hanya di mesin Hermes, lewat variabel lingkungan atau file `.testnet.env` (izin 600) di luar repo. **Tidak pernah** di repo, log, atau chat.
- Jangan pakai kunci dari akun asli.
- Setelah selesai uji, kunci testnet dicabut dan dibuat ulang.
- Batas di `risk.py` tidak dilonggarkan: maks 3 posisi, 20% modal per posisi, leverage 1x, kill switch berlapis.
- Respons order **bukan bukti** posisi ada. Yang jadi bukti adalah akun bursa, dicek lewat rekonsiliasi.

---

## 10. Kekurangan yang masih ada (jujur)

- Funding paper belum bisa dibandingkan dengan funding bursa sampai ada order nyata.
- Rumus jarak likuidasi hanya perkiraan.
- Koin yang di-delist dan funding saat penutupan dini belum dimodelkan.
- Pengecekan saldo spot hanya batas bawah (apa yang ada di akun tidak boleh kurang dari catatan).
- Kegagalan permanen yang tenang, misalnya kunci kedaluwarsa, belum tentu memunculkan alarm.
- Panduan lama `PANDUAN-BAHASA-BAYI` berisi angka lama. Pakai panduan ini sebagai acuan.
- Tampilan dashboard terbaru belum diperiksa saya di browser sungguhan.

---

## 11. Peta file (kalau Anda penasaran)

| File | Fungsi |
|---|---|
| `radar.py`, `scan_and_push.py` | Bot radar dan pengirim data |
| `paper_carry.py` | Bot trading (paper dan `--testnet`) |
| `execution.py`, `binance_testnet.py` | Kirim order dua kaki ke bursa demo |
| `risk.py` | Semua batas keamanan |
| `watchdog.py` | Satpam dan rekonsiliasi |
| `web_vercel/index.html` | Dashboard |
| `start_all.sh` | Menyalakan semua proses (dipakai Hermes) |
| `HANDOFF-HERMES.md` | Prosedur untuk Hermes |
| `LAPORAN-TES-*.md` | Hasil uji dari Hermes |
