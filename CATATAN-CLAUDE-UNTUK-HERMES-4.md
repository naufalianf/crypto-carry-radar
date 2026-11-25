# Catatan Claude untuk Hermes, 4

Ditulis untuk: Hermes (agen operator di mesin bot). Dua perubahan, keduanya read-only, tidak menyentuh `risk.py` maupun jalur order.

## Yang berubah

1. **bb9135b** `.github/workflows/data-segar.yml`. Berjalan di GitHub tiap 2 jam, gagal (dan GitHub mengirim email ke pemilik repo) kalau `web/paper.json` atau `web/radar.json` lebih tua dari 6 jam. Menutup celah "watchdog mati tidak ada yang tahu". Tanpa secret. Tidak perlu tindakan darimu, kecuali: **jangan hentikan push `scan_and_push` dan `paper_carry` ke GitHub**, itu yang diperiksa.
2. **63f62ef** Watchdog kini juga memeriksa kaki spot. `BinanceTestnet.spot_qty()` membaca `/api/v3/account` (read-only). Aturannya satu arah: tiap posisi ber-`exec` harus punya saldo aset dasar >= qty (toleransi 1,2%). Kelebihan saldo diabaikan karena akun testnet punya saldo bawaan. Spot tak terjangkau dilewati, tidak membunyikan alarm.

## Yang perlu kamu lakukan

```
git pull --rebase origin main
python3 watchdog.py --selftest && python3 binance_testnet.py --selftest
# restart daemon watchdog, lalu uji pada kondisi nyata:
python3 -c "import watchdog as w; print(w.cek_posisi())"
```
Harapan: `(False, [])`. Kalau berisi pesan `spot:`, **jangan abaikan**: bandingkan saldo spot di bursa dengan `exec.qty` di `paper_state` lebih dulu, lalu laporkan. Jangan menutup posisi untuk "menenangkan" alarm.

## Sisa gerbang Tahap 2 (tidak bisa dipercepat lewat kode)

- Paper carry >= 30 hari, selisih funding < 0,20%, >= 3 posisi tertutup penuh. Per 2026-11-25: ~33 jam, `closed: 0`.
- Agar data slippage dan selisih funding mulai terkumpul sekarang, jalankan `--testnet` dan **mulai dari 1 posisi dulu**. Naikkan ke 3 setelah satu siklus buka-tutup bersih.
- Tiap hari: ada/tidaknya `execution_halt.json`, posisi state vs bursa (perp dan spot), slippage per order.
- Kalau HALT: berhenti dan laporkan. Jangan hapus `execution_halt.json` sebelum bursa diperiksa manual.
- Setelah pengujian selesai: cabut (revoke) key testnet yang pernah lewat chat dan buat ulang, simpan hanya di `.testnet.env` mode 600 di luar repo.
