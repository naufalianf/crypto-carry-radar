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
   *Koreksi 2026-11-24: sebelumnya ditandai lulus padahal plafon 20% hanya dipakai `plan_order`;
   `paper_carry` memakai 1000/posisi (167% plafon). Sekarang `NOTIONAL = risk.batas_notional(MODAL_BUKU)`
   = 600 dan ada `assert` saat modul dimuat. Posisi lama (1000) tetap tercatat apa adanya.*
7. Rekonsiliasi posisi otomatis: kalau dua kaki tidak seimbang, bot menutup dan memberi tahu.
   *Status: logikanya sudah ada di `execution.py` (urutan spot lalu perp, unwind kaki yatim,
   status order tak jelas -> HALT, tutup perp dulu baru spot), 19 tes lulus dengan exchange
   tiruan dan uji mutasi. Adapter TESTNET ada di `binance_testnet.py` (limit IOC, URL testnet
   ditulis mati, tidak ada mode live; diuji dengan transport tiruan, BELUM pernah menyentuh
   testnet sungguhan). Berikutnya: `python3 binance_testnet.py --smoke BTCUSDT` dengan kunci
   testnet, lalu minimal 2 minggu di testnet sebelum uang sungguhan.*
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

## Pembaruan penjaga risiko (24 Nov 2026)

Terinspirasi pola `drawdown-circuit-breaker` dan `trader-memory-core` (repo claude-trading-skills) serta
pengalaman praktisi bot di Threads, ditulis ulang dengan stdlib. Semuanya di `risk.py` / `paper_carry.py`
dan dites oleh `test_paper_carry.py` (`python3 paper_carry.py --selftest`):

- Kill switch berlapis 1d/7d/30d (1% / 2% / 3% dari modal buku), dihitung dari kurva PnL kumulatif.
  Batas lama 3%/hari praktis tak terjangkau: stop per posisi hanya 0,33% dari modal buku.
- Jeda 24 jam setelah 2 posisi tertutup rugi beruntun; jeda 24 jam per simbol setelah keluar; maks 2 posisi baru per tick.
- Fail closed: `radar.json` > 6 jam atau tak terbaca -> tanpa posisi baru; `paper_carry_state.json` rusak -> berhenti, tidak dibuat ulang.
- Lock per tick dan simpan state atomik. Jurnal `paper_carry_trades.csv` berheader, memuat APR masuk/keluar dan funding yang dijanjikan vs didapat.
- Syarat Tahap 2 ("paper carry >= 30 hari") sekarang bisa dinilai dari jurnal itu, bukan dari tebakan.
