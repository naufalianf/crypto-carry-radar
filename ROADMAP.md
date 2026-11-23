# Roadmap — dari alat bantu keputusan ke bot yang eksekusi

Aturan dasar: **naik tahap hanya kalau syarat pengujian di tahap sebelumnya terbukti lulus.**
Kalau tidak lulus, bot tetap di tahap itu. Tidak ada naik tahap berdasarkan perasaan atau
karena "sudah lama dibangun".

---

## Tahap 0 — riset dan uji (SELESAI)

Yang sudah diuji dan hasilnya dicatat di skill `crypto-trading-bot-validation`:

- 80 strategi SMA/mean-reversion 4h: tidak ada edge (param pemenang berganti 13x di 23 window).
- TSMOM 10 koin harian: seri dengan beli-tahan di bull, kalah lebih sedikit di bear. Manajemen risiko, bukan mesin profit.
- Funding carry delta-neutral: positif tapi menyusut (7,44% -> 3,18% APR). Filter funding justru memperburuk.
- Radar funding: 701 perp kripto; peluang APR tinggi hampir semua **tidak punya pasar spot** -> tidak bisa dieksekusi.

Kesimpulan: edge tidak ada di indikator. Yang bisa diukur dan diandalkan: **APR funding riil,
biaya eksekusi, kapasitas orderbook** — itulah yang dihitung bot sekarang.

## Tahap 1 — rencana order (SELESAI)

`plan_order.py` — menghitung ukuran posisi dari kedalaman orderbook nyata, harga dua kaki,
biaya, hari balik modal, margin, aturan keluar. Output: pesan siap eksekusi manual.
Bot **tidak** menyentuh API key, **tidak** mengirim order.

Belum terpasang: pengiriman otomatis ke Telegram (`--send`). Tinggal butuh token bot.

---

## Tahap 2 — semi-otomatis (BELUM. Butuh semua syarat ini)

Bot menyiapkan order, Bro menyetujui satu tombol di Telegram. Bot mengirim order hanya
setelah persetujuan.

**Syarat pengujian — semua wajib, tidak bisa ditawar:**

1. `paper_carry.py` jalan **>= 30 hari kalender penuh** tanpa celah log lebih dari 24 jam.
2. Selisih net paper vs hitungan teori **< 0,20%** per posisi (bukti akuntansi funding benar).
3. Minimal **3 posisi ditutup penuh** lewat aturan keluar (bukan cuma dibuka).
4. Slippage nyata tidak pernah melebihi **0,3%** dari harga di rencana order.
5. `paper spot` (runner.py): selisih equity vs backtest **< 5%**.
6. Ada dan lulus: mode **dry-run** (menyusun order tanpa mengirim), **kill switch**,
   batas notional dan batas rugi harian **dipaksa di kode**, bukan cuma di dokumen.
7. Rekonsiliasi posisi otomatis: kalau dua kaki tidak seimbang, bot menutup dan memberi tahu.
8. Kredensial: API key **hanya izin trade, withdraw dimatikan**, IP whitelist, disimpan di
   env/file terpisah, tidak pernah masuk kode atau log.
9. **Limit order saja.** Tidak ada market order di koin tipis.

## Tahap 3 — penuh otomatis (BELUM. Butuh Tahap 2 lulus dulu)

**Syarat tambahan:**

1. Tahap 2 jalan **>= 60 hari** dengan **>= 20 order nyata** dan nol intervensi darurat.
2. Slippage nyata rata-rata **<= 0,15%** per kaki.
3. Tombol stop teruji: menutup semua posisi **< 60 detik**.
4. Batas rugi harian dan batas posisi teruji benar-benar memicu, bukan hanya ada di kode.
5. Modal awal dibatasi kecil (misal 5% dari dana), naik bertahap setelah 90 hari bersih.
6. Ada pemantauan yang memberi tahu kalau bot mati, posisi tak seimbang, atau margin menipis.

---

## Yang tidak boleh dilanggar di tahap mana pun

- API key tanpa izin withdraw. Selalu.
- Tidak ada order nyata tanpa ada rencana tertulis yang bisa diperiksa ulang.
- Dua kaki carry selalu sama besar; kalau satu gagal, satunya ditutup.
- Tidak ada naik tahap tanpa bukti tertulis dari pengujian, bukan dari keyakinan.
- Exchange: Binance global bukan pedagang berlisensi OJK. Ini keputusan risiko milik pemilik dana,
  bukan sesuatu yang bisa disembunyikan oleh bot.
