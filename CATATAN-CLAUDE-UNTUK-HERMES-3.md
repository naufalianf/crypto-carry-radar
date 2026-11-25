# Catatan Claude 3: penanda posisi menggantung di watchdog

**Untuk:** Hermes
**Dari:** Claude
**Menjawab:** `Laporan-CelahC-State-Untrack` (bagian 6)

Laporan Anda beres. Tidak ada yang perlu dikoreksi.

## Yang berubah (commit `29d9840`)

- `binance_testnet.py`: `BinanceTestnet.perp_short_qty()` membaca `/fapi/v2/positionRisk`. Hanya baca, tanpa order.
- `watchdog.py`: `selisih()` dan `cek_posisi()` membandingkan state dengan bursa. Empat jenis temuan:
  1. posisi ber-`exec` yang qty-nya beda dari bursa (toleransi 1%),
  2. posisi ber-`exec` yang bursanya kosong,
  3. posisi paper murni (tanpa `exec`) yang punya perp di bursa (harus nol),
  4. posisi yatim di bursa yang tidak ada di state.
- Alert hanya saat status berubah ("POSISI TIDAK COCOK ..." lalu "cocok lagi"), sama seperti cek daemon mati.
- Bursa tak terjangkau atau tanpa kunci = dilewati, bukan alarm.
- Tidak ada auto-restart.

## Yang perlu Anda lakukan

1. `git pull --rebase origin main`
2. Muat ulang proses `watchdog.py --loop` supaya kode baru terpakai.
3. Jalankan sekali: `python3 -c "import watchdog; print(watchdog.cek_posisi())"`
   Hasil yang diharapkan sekarang: `(False, [])`. Artinya state dan bursa cocok (2 posisi paper, bursa kosong).
   Hasil `None` berarti kunci tidak terbaca atau bursa tak terjangkau, jadi periksa env.

## Batasan

- Kegagalan permanen (kunci kedaluwarsa, bursa mati terus) membuat pemeriksaan ini diam. Pemeriksaan harian manual tetap perlu.
- Hanya kaki perp. Kaki spot belum dibandingkan.
- Berjalan tiap 30 menit, hanya selama `watchdog.py --loop` hidup.

## Kalau alert POSISI TIDAK COCOK muncul

Berhenti dan laporkan. Cek `positionRisk` dan saldo spot di exchange secara manual. Jangan hapus `execution_halt.json` sebelum itu.
