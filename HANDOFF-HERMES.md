# Serah-terima untuk Hermes (baca ini dulu)

Ditulis oleh Claude untuk Hermes dan Naufal. Semua kode di bawah sudah ada di `main`.
Bahasa: Indonesia. Tanggal: 2026-11-24.

## Aturan yang tidak boleh dilanggar
1. **Hanya testnet.** Tidak ada kode live, dan jangan menambahkannya tanpa persetujuan Naufal yang eksplisit.
2. **Kunci API hanya milik Naufal/Hermes.** Isi lewat env `BINANCE_TESTNET_KEY` dan `BINANCE_TESTNET_SECRET`.
   Jangan ditulis ke repo, log, atau chat. Kunci live tidak boleh dipakai di sini.
3. **Kalau HALT, berhenti dan lapor.** Jangan menghapus `execution_halt.json` sebelum posisi di exchange
   dicek manual dan cocok dengan `paper_carry_state.json`.
4. Jangan mengubah ambang risiko (`risk.py`) supaya "lebih banyak masuk posisi".

## Yang baru sejak commit `2e0fff0`
| Commit | Isi |
|---|---|
| `049f7fd` | `execution.py`: eksekusi dua kaki (spot dulu, lalu perp), unwind kaki yatim, HALT. 19 tes |
| `86622e5` | Alert Telegram dari `paper_carry` (masuk/keluar/kill switch/radar basi/error) + pemantau jarak likuidasi |
| `2d7f776` | `watchdog.py`: alert kalau `paper_carry` atau `scan_and_push` berhenti berdetak > 6 jam |
| `f85dcde` | `binance_testnet.py`: adapter Binance TESTNET (limit IOC, HMAC, klasifikasi galat) |
| commit ini | `paper_carry.py --testnet`: menyambungkan paper ke eksekusi testnet. 34 tes |

## Langkah aktivasi (urut)
1. `git pull --rebase origin main`
2. Selftest, semuanya harus OK:
   ```
   python3 paper_carry.py --selftest
   python3 execution.py --selftest
   python3 binance_testnet.py --selftest
   python3 watchdog.py --selftest
   ```
3. Cron watchdog: `*/30 * * * * cd ~/crypto-carry-radar && python3 watchdog.py`
4. Restart daemon `paper_carry` dan `scan_and_push` (supaya alert Telegram dan margin aktif). Mode paper murni tetap jalan.
5. Buat kunci testnet (spot: testnet.binance.vision, futures: testnet.binancefuture.com, keduanya terpisah),
   isi env, lalu **smoke test**: `python3 binance_testnet.py --smoke BTCUSDT`
   (buka lalu tutup sekitar 120 USDT, mencatat slippage ke `execution_fills.csv`).
6. **Tulis hasil smoke test di bagian "Hasil smoke test" di bawah file ini, apa adanya**, termasuk galat, lalu
   commit dan push. Format respons dan kode galat ditulis dari dokumentasi dan belum pernah menyentuh testnet
   sungguhan, jadi penyesuaian itu normal.
7. Hanya kalau smoke test bersih: jalankan `python3 paper_carry.py --loop --testnet`
   (nominal order `EXEC_NOTIONAL` = `NOTIONAL` = 600 USDT per posisi = plafon 20% dari `MODAL_BUKU` 3000,
   maksimum 3 posisi). Pastikan saldo testnet cukup: sekitar 3x600 di spot dan margin perp untuk 3x600.

## Cara kerja mode `--testnet`
- Paper tetap jadi pembukuan utama. Order nyata hanya ikut saat paper memutuskan masuk/keluar.
- Masuk: `execution.buka_carry`. Posisi dicatat dengan **harga isi nyata** dan field `exec` (trade_id, qty).
- Keluar: `execution.tutup_carry` (perp ditutup dulu, baru spot). Kalau gagal, posisi **tetap terbuka** di
  state, Telegram "EXEC HALT", dan dicoba lagi tick berikutnya dengan client id baru.
- Posisi bertanda `exec` tidak akan ditutup di paper kalau daemon dijalankan tanpa `--testnet`.
- Reset setelah pemeriksaan manual: `python3 paper_carry.py --reset-exec-halt`
- Kill switch lama (`--reset-halt`) dan HALT eksekusi adalah dua hal berbeda. Dua-duanya bisa menghentikan entri.

## Yang diukur selama testnet (minimal 2 minggu sebelum membahas uang sungguhan)
- `execution_fills.csv`: kolom `slip_bps` per kaki. Ini biaya nyata yang belum pernah terukur (paper memakai markPrice).
- Berapa kali HALT terjadi dan penyebabnya.
- Apakah qty spot dan perp selalu sama (cek manual di akun testnet, bandingkan dengan `exec.qty`).
- Seberapa sering order IOC terisi parsial atau nol.

## Keterbatasan yang diketahui (jangan diklaim sudah beres)
- Adapter belum pernah menyentuh testnet. Semua uji memakai transport tiruan.
- Likuiditas buku testnet tipis dan harganya beda dari pasar asli: slippage di sana menguji alur, bukan memperkirakan biaya riil.
- client id disimpan di memori adapter. Restart di tengah order berarti `order_status` melempar Unknown, lalu HALT. Aman, tapi perlu cek manual.
- Rumus jarak likuidasi hanya perkiraan isolated margin dengan maintenance margin 0,5%. Cocokkan dengan data akun asli sebelum live.
- Watchdog berjalan di mesin yang sama dengan daemon. Kalau Hermes mati total, tidak ada yang memberi tahu.
- Belum dimodelkan: saldo spot yang tertahan, delisting saat posisi terbuka, funding yang dibayar saat perp ditutup lebih awal.
- PDF panduan masih berisi angka lama.
- Nominal posisi turun dari 1000 ke 600 pada 2026-11-24. Posisi lama tetap 1000 di pembukuan; PnL sebelum dan sesudah tanggal itu tidak sebanding dalam dolar. Hitungan 30 hari tidak di-reset (`started` dipertahankan saat restart).
- `paper_carry_state.json` sudah di-untrack git (`.gitignore`) sejak 2026-11-25: state memuat `exec.trade_id`/`exec.qty` posisi nyata, rollback git = kehilangan jejak posisi di exchange. Sama untuk `paper_state.json` dan `*_log.txt`.
- `execution_fills.csv` di-ignore (berubah tiap order, risiko konflik sama dengan state).
  Bukti slippage dirangkum ke laporan berkala, bukan hidup di git.

## Syarat sebelum live (belum terpenuhi, jangan dilompati)
Smoke test bersih, 2 minggu testnet tanpa HALT yang tak terjelaskan, slippage terukur dan masuk akal terhadap
asumsi biaya 0,3%, kunci live hanya izin trade (withdraw mati, IP whitelist), dan persetujuan eksplisit Naufal.

## Hasil smoke test (diisi Hermes, jangan diisi Claude)
Aturan mengisi:
- **Jangan menulis kunci API, secret, atau signature.** Kalau ada galat yang memuat URL bertanda tangan, hapus bagian `signature=...`.
- Tempel keluaran asli, jangan diringkas. Galat yang tampak sepele sering justru petunjuk utama.
- Satu entri per percobaan. Tambahkan di bawah entri terakhir, jangan menimpa entri lama.
- Setelah mengisi: `git pull --rebase origin main`, commit, push.

Format entri (salin, lalu isi):
```
### Percobaan N, <tanggal dan jam>
- Commit yang dijalankan: <git rev-parse --short HEAD>
- Perintah: python3 binance_testnet.py --smoke BTCUSDT
- Selftest 4 modul: OK / GAGAL (tulis yang gagal)
- Hasil: BERSIH / GALAT / TERISI SEBAGIAN
- Keluaran asli perintah di atas:
  <tempel di sini>
- Isi execution_fills.csv (baris baru saja): <tempel>
- Saldo akun testnet setelahnya: spot BTC = ?, posisi perp BTCUSDT = ?  (harus sama-sama 0)
- Ada file execution_halt.json? ya / tidak
- Catatan: <apa pun yang terasa janggal>
```

### Percobaan 1, 2026-11-25 02:38 UTC — SPOT SAJA (`--spot`)
- Commit yang dijalankan: `7ca664f` (+ perubahan adapter yang belum di-commit saat uji)
- Perintah: `python3 binance_testnet.py --smoke BTCUSDT --spot`
- Selftest 4 modul: OK (paper_carry 34 tes, execution 19 tes, binance_testnet, watchdog)
- Hasil: **BERSIH** — dua order FILLED, saldo kembali, nol sisa
- Keluaran asli:
```
BTCUSDT: ask 59221.77 bid 59221.76 spread 0.0 bps | target 120 USDT
qty: 0.002 (nilai ~118.44 USDT)
beli: qty 0.002 harga 59221.77 ref 59221.77 slip +0.00 bps
jual: qty 0.002 harga 59221.76 ref 59221.76 slip -0.00 bps
sisa aset: {'BTC': 1.0}
SPOT SMOKE SELESAI — slippage tercatat di execution_fills.csv
```
- Isi `execution_fills.csv`:
```
ts,trade_id,leg,side,qty,ref_price,fill_price,slip_bps,status
1795575518,SMOKE1795575518,spot,buy,0.00200000,59221.77000000,59221.77000000,0.00,ok
1795575520,SMOKE1795575518,spot,sell,0.00200000,59221.76000000,59221.76000000,-0.00,ok
```
- Verifikasi independen di exchange (bukan dari respons order, tapi query ulang):
```
SMOKE1795575518B | status: FILLED | executedQty: 0.002 | cumQuote: 118.44354 | orderId: 17571472
SMOKE1795575518J | status: FILLED | executedQty: 0.002 | cumQuote: 118.44352 | orderId: 17571474
BTC free 1.00000000 (utuh, tidak ada sisa) | USDT free 9999.99996
```
- Saldo akun testnet setelahnya: spot BTC = **1.00000000** (saldo awal 1 BTC, tidak bertambah —
  0,002 dibeli lalu 0,002 dijual), posisi perp BTCUSDT = **tidak diuji** (kunci futures belum ada)
- Ada file `execution_halt.json`? **tidak**
- Catatan:
  1. **Slippage 0,00 bps itu mencurigakan-tapi-benar.** Order IOC limit menyilang harga terbaik
     di buku testnet yang sangat tipis; 0,002 BTC ≈ 118 USDT terserap di satu level. Ini **bukan**
     bukti biaya riil — justru menguatkan bahwa testnet tidak bisa dipakai memperkirakan biaya
     pasar asli. Jangan pakai angka ini untuk mengisi asumsi 0,3%.
  2. **Spread tercatat 0,0 bps** (ask 59221.77 / bid 59221.76). Di pasar asli BTC spread-nya
     beberapa bps. Buku testnet memang tidak realistis.
  3. Baris kedua `slip_bps` tercatat `-0.00`. `tutup_carry`/`_catat` memberi tanda negatif untuk
     sisi jual; hasilnya angka negatif nol. Tidak salah hitung, hanya tampilan.
  4. Jumlah BTC awal akun 1,0 membuat "sisa aset" tidak bisa dibaca sebagai "bersih" secara
     langsung — harus dibandingkan dengan saldo sebelum order. Sudah dibandingkan: 1,0 -> 1,0.

### Percobaan 2, 2026-11-25 02:41 UTC — DUA KAKI, gagal di gerbang kunci
- Perintah: `python3 binance_testnet.py --smoke BTCUSDT`
- Hasil: **GALAT (diharapkan)** — kaki futures menolak kunci spot SEBELUM order apa pun
- Keluaran asli:
```
KAKI FUTURES DITOLAK (kode -2015): Invalid API-key, IP, or permissions for action
Kunci spot tidak berlaku di testnet futures — Binance memisah dua akun itu.
```
- Saldo: tidak berubah, nol order terkirim ke spot (setup futures jalan lebih dulu)
- Ada file `execution_halt.json`? tidak
- Catatan: bukti langsung bahwa satu pasang kunci tidak cukup — lihat temuan 8 di
  `CATATAN-HERMES-UNTUK-CLAUDE.md`.

### Percobaan 3, 2026-11-25 04:31 UTC — DUA KAKI, BERSIH (kunci hanyalah "Demo Trading API")
- Perintah: `python3 binance_testnet.py --smoke BTCUSDT`
- Hasil: **BERSIH** — dua kaki dibuka dan ditutup, posisi datar, tidak ada sisa
- Keluaran asli:
```
FUT host: https://demo-fapi.binance.com
buka: {'status': 'ok', 'qty': 0.002, 'spot': (0.002, 59050.74), 'perp': (0.002, 59025.9)}
tutup: {'status': 'ok'}
```
- Isi `execution_fills.csv` (empat baris terakhir):
```
ts,trade_id,leg,side,qty,ref_price,fill_price,slip_bps,status
1795581874,SMOKE1795581873,spot,buy,0.002,59050.74,59050.74,0.00,ok
1795581875,SMOKE1795581873,perp,sell,0.002,59085.00,59025.90,10.00,ok
1795581876,SMOKE1795581873,perp,buy,0.002,59122.00,59181.20,10.01,close
1795581876,SMOKE1795581873,spot,sell,0.002,59050.74,59050.73,0.00,close
```
- Verifikasi independen setelahnya: `PERP amt 0.0000` (datar), `SPOT BTC 1.00000000`,
  `SPOT USDT 9999.78168`, `FUT wallet 4999.55857`. Tidak ada posisi maupun order menggantung.
- Ada file `execution_halt.json`? tidak
- Catatan (semua ini bug yang ketemu dan diperbaiki saat percobaan):
  1. **Kunci "Demo Trading API" BUKAN kunci testnet lama.** Ditolak `-2015` oleh
     `testnet.binancefuture.com`, diterima oleh `demo-fapi.binance.com`. Host futures
     dipindah ke demo, bisa ditimpa lewat `BINANCE_TESTNET_FUT_HOST`.
  2. **Futures tidak mengirim `avgPrice`.** Kode lama membaca `js["avgPrice"]` untuk
     semua respons futures → `KeyError` padahal order `FILLED`. Akibatnya smoke pertama
     meninggalkan short 0,002 BTC menggantung (ditemukan lewat `/fapi/v2/positionRisk`,
     bukan dari respons order). Sudah ditutup manual, lalu `_avg_harga()` dibuat tahan
     empat bentuk respons. **Pelajaran: jangan pernah percaya respons order sebagai bukti
     posisi — query ulang posisi.**
  3. **`slip_bps` kaki perp diukur terhadap harga SPOT.** Percobaan 2 sempat mencatat
     +4,96 dan +23,45 bps yang bukan slippage, melainkan basis spot-perp. Sekarang
     referensi perp diambil dari `fapi/v1/ticker/bookTicker`.
  4. Slippage perp yang terukur **+10,00 bps = tepat `TOL_BPS`**, artinya order limit IOC
     menyilang sebesar toleransi. Itu angka wajar untuk buku demo, tetap **bukan**
     perkiraan biaya pasar asli.
  5. IP mesin Hermes sempat kena `-1003 IP banned` di host futures lama karena terlalu
     banyak request saat diagnosis (bukan karena kode bot). Endpoint publik tidak terpengaruh.

### Percobaan 4, 2026-11-25 04:38 UTC — verifikasi ulang setelah perbaikan referensi harga
```
buka: {'status': 'ok', 'qty': 0.002, 'spot': (0.002, 59050.74), 'perp': (0.002, 59025.9)}
tutup: {'status': 'ok'}
PERP amt 0.0000 | SPOT BTC 1.00000000 | FUT wallet 4999.55857326
```
Selftest 4 modul: OK. Nol posisi menggantung.
