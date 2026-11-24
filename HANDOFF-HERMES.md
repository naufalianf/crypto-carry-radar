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
   (nominal order `EXEC_NOTIONAL` = 150 USDT per posisi, maksimum 3 posisi).

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
- 30 hari paper baru dihitung sejak daemon di-restart dengan kode terbaru.

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

(belum ada percobaan)
