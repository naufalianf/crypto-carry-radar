# REVIEW.md — untuk penelaah (Claude atau manusia)

> **Baca juga `TELAAH-BALASAN.md`** — balasan atas telaah pertama: temuan yang
> terverifikasi, bug look-ahead yang sudah diperbaiki beserta dampak terukurnya,
> dan bagian saran risiko yang sengaja tidak dipakai (beserta alasannya).

Tujuan file ini: memberi penelaah pijakan untuk **membantah**, bukan menyetujui.
Semua angka di bawah bisa direproduksi sendiri dengan perintah yang tertera. Kalau
angka tidak cocok saat Bro jalankan, anggap laporan ini salah dan cari penyebabnya.

## Aturan main proyek ini

1. Tanpa dependency pihak ketiga. Semua stdlib Python. Data dari endpoint publik Binance.
2. Tidak ada API key, tidak ada order. `plan_order.py` hanya menyusun rencana untuk dieksekusi manual.
3. Biaya dimasukkan sejak awal: taker spot 0,1%, taker perp 0,05%, dua kali (masuk+keluar).
4. Sinyal dihitung dari bar yang sudah tutup, eksekusi di bar berikutnya (anti look-ahead).
5. Anti cherry-pick: yang diuji SEMUA strategi/kombinasi, bukan hanya yang menang.

## Klaim dan cara membantahnya

| Klaim | Reproduksi | Angka yang dilaporkan |
| --- | --- | --- |
| Tidak ada edge di SMA/mean-reversion 4 jam | `python3 bot.py --selftest && python3 bot.py --sweep --interval 4h --years 3` | profit 6/80 BTC, 5/80 ETH; median strategi kalah dari beli-tahan |
| Pemenang parameter tidak stabil (indikasi overfitting) | `python3 bot.py --walkforward --interval 4h` | BTC 10/23 window profit; parameter pemenang berganti 13 kali |
| TSMOM harian = manajemen risiko, bukan mesin profit | `python3 portfolio.py --selftest && python3 portfolio.py --run --years 4` | **KLAIM LAMA DITARIK**: bug look-ahead membuat TSMOM tampak menang. Setelah diperbaiki: TSMOM L30/R7 +182% vs BTC +268% (kalah). Lihat `TELAAH-BALASAN.md` |
| Carry funding positif tapi menyusut | `python3 carry.py --selftest && python3 carry.py --run --years 3` (ulangi dengan `--years 2` dan `--years 1`) | APR 7,44% -> 4,82% -> 3,18%; filter funding justru memperburuk |
| Koin ber-APR tinggi hampir semua tidak punya pasar spot | `python3 radar.py --run --top 60 --threshold 8` | 10 dari 10 kandidat APR tertinggi tanpa pasar spot -> carry mustahil |
| Kapasitas orderbook membatasi ukuran posisi | `python3 plan_order.py --run --capital 1000` | QNT: kapasitas pita 0,1% ~$6.459 -> ukuran dipotong ke $646 |
| Akuntansi funding paper carry benar | lihat `paper_carry_log.txt` dan `paper_carry_state.json` | net = funding - biaya; tidak ada funding dihitung dua kali |

## Yang paling ingin saya (penulis) dibantah

1. **Look-ahead halus.** Apakah ada tempat di mana harga bar yang sama dipakai untuk
   sinyal dan eksekusi? Lihat `bot.py` fungsi backtest dan `carry.py`.
2. **Akuntansi funding.** `paper_carry.py` mencatat funding per `fundingTime` dengan
   penanda terakhir. Cari kemungkinan double count atau periode terlewat.
3. **Asumsi dua kaki terisi sempurna.** Rencana order menganggap kedua kaki terisi di
   harga bid/ask yang sama. Kalau salah satu tidak terisi, hasilnya bukan delta-neutral.
   Apakah ini terlalu optimistis? Bagaimana cara mengukurnya?
4. **Survivor bias.** Universe diambil dari daftar perp yang **masih** ada hari ini. Koin
   yang delisting tidak ikut terhitung. Seberapa besar dampaknya ke angka carry?
5. **Fee dan slippage.** Apakah 0,1%/0,05% taker realistis untuk akun kecil? Bagaimana
   kalau kena VIP 0 vs VIP 1, atau kalau order kena partial fill?
6. **Dataran edge.** Kalau kesimpulannya "tidak ada edge di arah", apakah ada struktur
   lain yang belum diuji (misal basis spot-perp antar exchange, atau funding intraday)?
   Sebutkan yang paling masuk akal untuk diuji berikutnya, beserta cara mengujinya.

## Ruang lingkup yang belum dikerjakan

- Eksekusi otomatis (Tahap 2/3 di `ROADMAP.md`) belum ada, dan syarat naik tahapnya kuantitatif.
- `runner.py` (paper spot) dan `paper_carry.py` belum jalan 30 hari — lihat syarat Tahap 2.
- Panel Vercel hanya membaca data publik; tidak menyimpan state.
