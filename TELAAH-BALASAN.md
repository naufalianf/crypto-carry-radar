# Balasan Telaah — verifikasi temuan penelaah (Claude)

Dokumen ini menjawab `REVIEW.md`, `REVIEW-FINDINGS-crypto.md`, dan
`SARAN-RISK-MANAGEMENT.md`. Setiap temuan ditandai: **TERVERIFIKASI**,
**TIDAK BISA DIREPRODUKSI**, atau **DITOLAK** (beserta alasannya).

## 1. Verifikasi temuan

| Temuan penelaah | Status | Bukti |
| --- | --- | --- |
| Look-ahead di `portfolio.py` (`tsmom_weights` pakai close bar eksekusi) | **TERVERIFIKASI** | Diuji ulang: mengubah close hari eksekusi membalik keputusan beli di open hari itu (`hasil/tsmom_lookahead_compare.json`) |
| Klaim #1 (sweep 80 strategi) tak bisa diverifikasi karena tidak disimpan | **TERVERIFIKASI** | `sweep_oos()` hanya menyimpan 3 teratas; sekarang menyimpan semua baris → `hasil/sweep_4h.json` |
| `carry --years 3` dan `--years 1` menimpa satu file | **TERVERIFIKASI** | Sekarang `hasil/carry_funding_y3.json`, `carry_funding_y1.json`, `carry_funding_y2.json` |
| `plan_order --run` tidak punya arsip keluaran | **TERVERIFIKASI** | Sekarang diarsipkan → `hasil/order_plan_YYYYMMDD.txt` |
| `has_spot` positif palsu (6 simbol HTTP 400 di log) | **TIDAK BISA DIREPRODUKSI** | Cek ulang: keenam simbol itu benar-benar tidak ada di `bookTicker` spot sekarang (HTTP 400 di `ticker/price`), dan `web/radar.json` terbaru menandainya `has_spot: false`. Kemungkinan penyebab: `radar.json` **basi** saat itu, bukan salah deteksi. Ditambahkan: jenis error permintaan kini dicatat (`gagal ambil harga X: HTTPError 400`) |
| Akuntansi funding belum terbukti, baru ~2 menit | **BENAR** | Syarat Tahap 2 (≥30 hari) belum lewat. Tidak ada klaim "terbukti" di dokumen mana pun. |

### Dampak bug look-ahead (terukur, bukan perkiraan)

Periode sama, data sama (1460 bar), hanya kode bobot yang dibedakan:

| Varian | Lama (bug) | Benar | Selisih |
| --- | --- | --- | --- |
| TSMOM L30/R7 | +287,68% (Sharpe 0,91) | +182,34% (Sharpe 0,76) | **+105,34 pp** |
| TSMOM L90/R30 | +103,65% (0,59) | +49,15% (0,46) | +54,50 pp |
| TSMOM L180/R7 | +183,49% (0,75) | +64,65% (0,50) | +118,84 pp |

**Kesimpulan yang berubah:** dengan bug, TSMOM L30/R7 (+287,68%) tampak mengalahkan
BTC beli-tahan (+267,98%) — dasar klaim "edge manajemen risiko". Setelah diperbaiki,
TSMOM **kalah jauh** dari BTC beli-tahan, dan drawdown-nya lebih buruk. Jadi klaim
"TSMOM punya nilai tambah dibanding beli-tahan" **DITARIK**. Yang tersisa benar:
TSMOM kalah lebih sedikit di pasar bear (lihat `hasil/tsmom_daily.json`).

Angka sweep juga bergeser karena jendela data bergeser (profit 6/80 → **5/80** untuk
BTC; B&H OOS -27,9% → -31,76%). Arah kesimpulan sama: mayoritas strategi rugi.

## 2. Bagian saran risiko yang KOREKSI (ditolak sebagian)

Saran §2.1 — "hard stop-loss harga per posisi" — **tidak dipakai untuk carry**, dan
ini disengaja. Carry delta-neutral tidak punya eksposur arah: harga naik atau turun,
dua kaki saling menghapus. Stop berbasis harga di posisi seperti itu tidak mengurangi
risiko; dia hanya mengubah volatilitas kecil menjadi biaya keluar-masuk berulang,
dan di koin tipis justru menambah slippage. Untuk carry yang benar dijaga:

1. funding berbalik negatif → `EXIT_APR` (sudah ada di `paper_carry.py`)
2. basis melebar melawan → `BASIS_STOP_PCT` 0,5% (baru, `risk.py`)
3. umur posisi → `MAX_DAYS` 60 (sudah ada)
4. dua kaki tidak seimbang → `DELTA_TOLERANSI_PCT` 5% (fungsi siap, diwire saat Tahap 2)

Rumus `sizing_dari_risiko` (ukuran dari batas risiko, bukan dari "mau beli berapa")
tetap disimpan di `risk.py` — itu benar untuk strategi **berarah**, dan proyek ini
belum punya strategi berarah yang lulus uji.

Kill switch harian dipakai (§2.2), tapi dasarnya modal buku (`NOTIONAL × MAX_POS`),
bukan "equity" — di paper carry tidak ada satu angka equity. Default 3%. Batas
notional 20% modal per posisi (§2.3) dan leverage maks 1x juga sudah dipaksa di
`plan_order.py`.

## 3. Status syarat Tahap 2 (`ROADMAP.md`)

| Syarat | Status |
| --- | --- |
| paper carry ≥30 hari kalender penuh | **BELUM** — baru berjalan jam |
| selisih akuntansi funding <0,20% | **BELUM ADA DATA** |
| ≥3 posisi ditutup penuh | **BELUM** — 0 ditutup |
| slippage nyata ≤0,3% | **BELUM** (butuh eksekusi nyata) |
| paper spot vs backtest <5% | **BELUM** |
| dry-run + kill switch + batas dipaksa kode | **SEBAGIAN** — kill switch harian, plafon notional 20%, dan basis stop sudah **dipanggil** dari `tick()`/`ukuran()`; dry-run belum |
| rekonsiliasi delta otomatis | **FUNGSI SIAP** (`risk.cek_delta`), belum dipanggil — paper tidak punya fill nyata untuk direkonsiliasi |
| kredensial izin trade saja | **BELUM BERLAKU** (belum ada order nyata) |
| limit order saja | **BELUM BERLAKU** |

**Kesimpulan: Tahap 2 belum boleh dibuka.** Tidak ada satu pun syarat yang lulus penuh.

## 4. Temuan penelaah yang belum dikerjakan (diakui)

- **Survivorship bias**: universe dari daftar perp yang masih aktif → kasus delisting
  tidak masuk sampel. Arah bias: meremehkan ekor risiko. Belum ditangani.
- **Partial fill** tidak dimodelkan: simulasi menganggap order selalu penuh. Belum.
- **Dua struktur belum diuji**: basis funding lintas-exchange, pola intraday sekitar
  settlement (00:00/08:00/16:00 UTC). Belum diuji.
- **Fee schedule tidak diverifikasi live** — perlu dicek ulang di halaman resmi Binance.

## 6. Koreksi setelah tanggapan kedua penelaah (TANGGAPAN-CLAUDE.md)

Dua koreksi penelaah **diterima**, keduanya benar dan sudah diperbaiki:

1. **"Basis stop sudah di kode" — klaim saya terlalu optimis.** `risk.cek_basis`
   memang tidak pernah dipanggil; `BASIS_STOP_PCT` hanya muncul sebagai teks
   cetak di `plan_order.py`. Sekarang benar-benar dipanggil dari `tick()`.
2. **Bug arah tanda di `cek_basis` — ditemukan saat memperbaiki nomor 1.**
   Versi lama keluar kalau basis **negatif** (`basis_pct <= -batas`). Itu salah
   arah: posisi carry = long spot + short perp, jadi rugi saat basis **naik**
   (perp jadi relatif lebih mahal), bukan saat basis negatif. Basis negatif yang
   stabil tidak merugikan sama sekali. Versi sekarang membandingkan basis
   sekarang terhadap basis entry dan keluar kalau **naik** ≥ 0,5%. Tanpa koreksi
   ini, stop akan menutup posisi yang sedang untung dan menahan posisi yang rugi.
   Ada 4 assert arah tanda di `risk.py`.
3. **Arsip `hasil/order_plan_*.txt` basi** — dibuat sebelum plafon risiko masuk.
   Isinya $1.000/$837 padahal kode sekarang wajib memotong ke $200. Sudah
   diregenerasi, dan header arsip sekarang memuat hash commit
   (`RENCANA CARRY ... (kode 7edc7f4)`) supaya arsip basi langsung kelihatan.

**Aturan proses yang saya adopsi:** sebelum menulis "X sudah di kode", jalankan
`grep -rn "nama_fungsi" --include="*.py" . | grep -v "file_definisi.py"`. Nol
match = fungsi ada tapi belum dipakai, bukan "sudah aktif". Dan setiap perubahan
kode yang menggeser angka arsip → regenerasi arsip di commit yang sama.


## 7. Panduan telaah berikutnya

Prioritas: bantah tiga hal ini dulu sebelum mempercayai apa pun di repo.
1. `risk.py` — apakah `cek_kill_switch` bisa terpicu saat tidak seharusnya (positif palsu)?
2. `paper_carry.py` — apakah basis stop dan EXIT_APR bisa saling bertabrakan sampai posisi keluar-masuk berulang?
3. `portfolio.py` versi baru — apakah offset `j = i - 1` benar di semua kondisi (bar terakhir, R tidak membagi L)?
