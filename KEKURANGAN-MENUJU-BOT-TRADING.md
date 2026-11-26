# Apa yang Masih Kurang Agar Ini Jadi Bot Trading

**Status per 2026-11-26 ~02:00 UTC** · Ditulis oleh Claude untuk Ian (Hermes boleh baca).
Sumber: repo `main` (commit Hermes `ae8c032` + laporan `754e379`, snapshot radar `b0e7276`).

## 1. Ringkasan satu paragraf

Kode bot sudah hampir lengkap: radar, logika masuk/keluar, batas risiko, eksekusi dua kaki,
HALT, watchdog, supervisor, CI. **Yang belum ada adalah bukti.** Belum ada satu pun order nyata
yang dikirim oleh daemon, belum ada posisi yang tertutup (`closed: 0`), dan baru sekitar
1,5 hari dari 30 hari yang disyaratkan. Sisa pekerjaan sebagian besar adalah menunggu pasar,
bukan menulis kode.

## 2. Sudah ada (jangan dikerjakan ulang)

| Bagian | Keterangan |
|---|---|
| Radar + dashboard | Hidup, dengan alarm data basi (GitHub Actions `data-segar`) |
| Logika masuk/keluar | Filter masuk, keluar karena APR < 2%, umur 60 hari, funding negatif |
| Batas risiko `risk.py` | Notional 20% modal, leverage 1x, maks 3 posisi, kill switch 1/2/3% |
| Eksekusi dua kaki | Spot dulu, lalu perp; kaki kedua gagal = kaki pertama dibatalkan |
| HALT | `execution_halt.json` menghentikan eksekusi sampai dicek manual |
| `MAX_EXEC_POS=1` | Hanya 1 posisi dikirim ke bursa, sisanya paper |
| Watchdog | Cek kesegaran data + rekonsiliasi posisi dengan bursa, kirim alarm |
| Supervisor | Menghidupkan ulang daemon yang mati, backup state, detak jantung |
| CI `uji.yml` | Selftest + unit test + pemindai kunci sebelum masuk `main` |
| Panduan | `PANDUAN-END-TO-END.md/.pdf`, `MONITORING.md` |

## 3. Yang kurang, berurutan

### A. Bukti dari dunia nyata (penghalang utama)

| # | Kekurangan | Kondisi sekarang | Bisa dipercepat? |
|---|---|---|---|
| A1 | **Order testnet pertama dari daemon** | 0. Tiga slot penuh posisi paper (ZEC, QNT, OPG) | Tidak, menunggu satu posisi tertutup |
| A2 | **Satu posisi tertutup secara alami** | `closed: 0`. APR semua posisi masih sekitar 4-5%, batas keluar 2% | Tidak, menunggu pasar |
| A3 | **`cek_posisi()` cocok dengan bursa setelah order daemon** | Belum pernah diuji. Siklus penuh terakhir (ADA $100) dilakukan manual | Setelah A1 |
| A4 | **Slippage dan selisih funding terukur** | Belum ada data | Setelah A1-A2 |
| A5 | **30 hari paper berjalan** | ~1,5 hari. Selesai paling cepat sekitar 24 Desember 2026 | Tidak |
| A6 | **Minimal 3 posisi tertutup** | 0 | Tidak |
| A7 | **Sekitar 2 minggu testnet tanpa HALT yang tak terjelaskan** | Belum mulai | Tidak |

Catatan: Bug 13 muncul pada percobaan order pertama. Wajar jika A1/A3 menemukan bug baru.
Itu tujuan tahap ini, bukan kegagalan.

### B. Lubang operasional (dari laporan Hermes, bagian 7)

| # | Lubang | Dampak | Perbaikan |
|---|---|---|---|
| B1 | Tidak tahan reboot (container tanpa systemd) | Mesin restart = daemon mati sampai ada yang menjalankan `bash start_all.sh` | Pindah ke VPS dengan systemd (`Restart=always`) |
| B2 | Supervisor tidak diawasi supervisor lain | Mati = watchdog lapor dalam 6 menit, tidak ada yang menghidupkan | Terselesaikan oleh B1 |
| B3 | Backup state di disk yang sama | Disk rusak = state dan backup hilang bersamaan | Salin berkala ke tempat lain |
| B4 | Kegagalan permanen (mis. kunci kedaluwarsa) tidak berisik | Bot diam, tampak sehat | Alarm khusus untuk error otorisasi berulang |

### C. Hal yang sengaja belum ada (wajib sebelum uang asli)

| # | Item | Catatan |
|---|---|---|
| C1 | Jalur spot uang asli | Host spot masih hardcoded `testnet.binance.vision`. Sengaja belum dibuat |
| C2 | Kunci API asli dengan izin minimum | Hanya trade, tanpa withdraw, dengan IP whitelist. Dibuat sendiri oleh Ian |
| C3 | Pemodelan biaya yang belum ada | Delisting, funding saat keluar lebih awal, rumus likuidasi masih perkiraan |
| C4 | Perintah tutup manual `--close SIMBOL` | Belum ada. Opsional, lewat jalur penutupan resmi, **belum disetujui** |

## 4. Dua definisi "MVP"

| | Syarat | Perkiraan waktu |
|---|---|---|
| **MVP teknis** | Satu siklus buka-tutup bersih oleh daemon di testnet, `cek_posisi()` cocok, selisih funding terukur | Hari sampai minggu. Tergantung kapan slot kosong |
| **MVP siap uang nyata** | A1-A7 selesai, B1 dan C1-C3 dikerjakan | Paling cepat akhir Desember 2026, jika tidak ada HALT tak terjelaskan |

## 5. Estimasi kematangan

| Lapisan | Perkiraan |
|---|---|
| Kode | ~95% |
| Operasional tanpa pengawasan | ~55% |
| Diuji order nyata | ~30% (hanya manual) |
| Bukti lintas waktu (30 hari, closed ≥ 3) | ~5% |
| Siap uang asli | 0% |

## 6. Yang perlu dilakukan sekarang

**Ian:** tidak ada tindakan wajib. Rutinitas harian 5 menit di `PANDUAN-END-TO-END.md` bagian 6.
Keputusan yang terbuka hanya jika ingin mempercepat A1: (1) tunggu alami (saran saya),
(2) setujui perintah `--close` (C4), atau (3) turunkan `ENTRY_APR` khusus testnet.
Opsi (3) tidak boleh menyentuh `risk.py`.

**Hermes:** jaga proses tetap hidup, laporkan segera saat ada posisi tertutup atau order
pertama terkirim. Saat itu jalankan `cek_posisi()` dan lampirkan hasilnya.
Jika ada HALT: berhenti dan lapor, jangan hapus `execution_halt.json` sebelum bursa dicek manual.

**Claude:** siap memeriksa setiap laporan, menambal bug dari order pertama, dan menyiapkan
B4 (alarm kegagalan permanen) jika disetujui.

## 7. Saran

Setuju dengan Hermes: **tunggu 30 hari dulu, jangan buka jalur uang asli** sebelum daemon
terbukti membuka dan menutup posisi sendiri dengan benar.
