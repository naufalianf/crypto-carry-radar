# Uji churn: apakah gaya Pine 5 menit bisa hidup setelah fee

**Tanggal:** 2026-11-27 · **Repo:** `naufalianf/crypto-carry-radar` · **Untuk:** Claude

## 1. Pertanyaan yang diuji

Ada postingan Threads (`@erickson.gb`, 2026-11-26) mengklaim bot bridge TradingView → Binance
menghasilkan +$1.550 dalam 3 hari dengan 134 trade tertutup, win rate 98%. Arsitekturnya nyata
(Pinescript di TradingView memberi sinyal, bridge meneruskan ke bursa), jadi yang diuji di sini
**bukan arsitekturnya**, tapi satu hal: apakah strategi bergaya indikator di bar 5 menit bisa
menghasilkan uang bersih setelah fee?

Ian minta uji ini setelah melihat klaim tersebut. Tidak ada yang diinstall, tidak ada kunci,
tidak ada order. Semua di data historis publik.

## 2. Metode

`uji_churn.py` (baru, stdlib saja, tanpa dependency):

- Data: `data-api.binance.vision` BTCUSDT, bar 5m/15m/1h/4h, 180 hari terakhir.
- Sinyal diputuskan di **close bar i**, order di **open bar i+1** — aturan anti look-ahead yang
  sama dengan `bot.py`, karena bug look-ahead pernah terjadi di proyek ini (TSMOM).
- Long-only spot, modal 100%, fee **0,1%/sisi** (taker Binance) + slippage **0,05%/sisi**.
  Satu putaran beli-jual = **0,3%** dari notional. Konstanta diambil dari `bot.py`, bukan angka baru.
- Tiga aturan indikator sederhana sebagai wakil gaya Pine: `sma_12_48` (tren),
  `breakout_48` (opening-range style), `rsi_14` (mean reversion).
- Selftest memastikan biaya benar: pada harga datar, beli-jual tiap bar harus rugi persis
  sebesar biaya per putaran. Lulus (`uji_churn selftest: OK`).

Biaya dipisah dari gerak harga (`bruto_pct` vs `biaya_pct`), supaya jelas mana yang salah:
sinyalnya atau ongkosnya.

## 3. Hasil

```
BTCUSDT — 180 hari
interval  bar     gerak median/bar  bar lolos biaya   aturan        trade  menang   bruto    biaya     NET
5m        51840   0,0522%           3,3%              sma_12_48       739   20,8%   -42,1%   110,7%   -92,9%
                                                     breakout_48     289   25,6%   -22,9%    43,3%   -67,1%
                                                     rsi_14          616   52,8%   +18,1%    92,4%   -81,5%
15m       17280   0,0897%          11,1%              sma_12_48       230   23,5%    +1,5%    34,5%   -49,8%
                                                     breakout_48      84   31,0%    +8,5%    12,6%   -17,0%
                                                     rsi_14          207   59,4%    -2,9%    31,0%   -48,8%
1h         4320   0,1754%          31,1%              sma_12_48        60   25,0%    +7,2%     9,0%   -11,7%
                                                     breakout_48      22   27,3%    -1,1%     3,3%   -10,7%
                                                     rsi_14           58   65,5%    +2,8%     8,7%   -16,4%
4h         1080   0,3618%          56,4%              sma_12_48        13   23,1%    +7,6%     2,0%    +1,3%
                                                     breakout_48       5   60,0%    +2,3%     0,8%    -0,3%
                                                     rsi_14           14   64,3%    -5,8%     2,1%    -7,3%
```

## 4. Temuan

**T1 — Sinyal 5 menit benar-benar ada, tapi ongkosnya menghapusnya.**
`rsi_14` di 5m menghasilkan **bruto +18,1%** — sinyal mean-reversion memang menangkap sesuatu.
Lalu biaya **92,4%** menghapusnya, net **−81,5%**. Ini bukan bukti sinyal jelek; ini bukti
frekuensi trade yang terlalu tinggi untuk ukuran gerak bar.

**T2 — Gerak median per bar jauh di bawah biaya satu putaran.**
5m: gerak khas **0,0522%** vs biaya **0,3%** = **5,7× lebih besar**. Hanya **3,3%** bar 5m yang
geraknya melewati biaya. Di 4h, gerak khas 0,3618% > 0,3%, jadi 56,4% bar lolos.

**T3 — Semakin tinggi timeframe, semakin kecil kerugiannya, dan pada 4h akhirnya positif.**
Net: 5m −92,9% → 15m −49,8% → 1h −11,7% → **4h +1,3%** (sma_12_48). Pola monoton ini adalah
tanda bahwa penyebab rugi adalah **biaya per trade**, bukan sinyal yang salah arah.

**T4 — Kalaupun positif, hasilnya tidak layak.**
`4h sma_12_48` net **+1,3% dalam 180 hari = ~2,6%/tahun**, dari **13 trade** — sampel terlalu
kecil untuk disimpulkan. Carry bot kita **+7,5%/tahun** dengan 1.094 hari data.
Jadi jalur indikator ini, bahkan di titik terbaiknya, **5,8× lebih buruk** daripada carry.

**T5 — Klaim 45 trade/hari secara aritmetika sulit masuk akal.**
45 trade × 0,3% = **13,5% notional per hari** yang harus ditutup fee. Profit poster $357,83
dibagi 59 trade = **$6,06/trade**. Kalau notional $600, itu **+1,01% net per trade**, artinya
perlu gerak bruto **1,31% per trade** — padahal median gerak bar 5m di BTC cuma **0,052%**.
Untuk mencapai itu perlu rata-rata gerak ~25× median bar, konsisten selama 59 trade berturut-turut.
Mungkin kalau memakai koin volatil / leverage besar, tapi **bukan** dari BTC spot 5m biasa.

## 5. Kesimpulan untuk Ian

Jalur "Pine → bridge → Binance" **bukan jalan yang lebih baik** untuk tujuan Ian:

1. Untuk bisa untung, frekuensi trade harus turun ke sekitar satu per beberapa hari.
   Pada frekuensi itu, bot carry kita sudah menghasilkan lebih banyak dengan risiko lebih kecil.
2. Scalping 5m/15m di spot Binance **rugi secara aritmetika** sebelum strateginya dibahas.
   Ini bukan soal indikatornya pintar atau tidak.
3. Klaim win rate 98% pada 45 trade/hari adalah **tanda risiko ekor**, bukan bukti kualitas:
   134 trade dengan 3 loss berarti satu loss buruk (~$1.550) menghapus seluruh 131 kemenangan.
   Rasio 44:1.

**Keputusan:** tidak perlu membangun bridge. Tidak ada jalur uang baru yang terbuka dari sini.

## 6. Yang tetap berguna dari latihan ini

- `uji_churn.py` sekarang ada sebagai **alat penolak ide**: setiap kali ada strategi baru
  (dari mana pun, termasuk dari Claude), jalankan dulu di 4 timeframe. Kalau biaya > bruto,
  selesai — tanpa perlu menulis bot, tanpa perlu VPS, tanpa perlu langganan TradingView.
- Angka **0,3% per putaran** sekarang terukur terhadap 180 hari data nyata, bukan asumsi.

## 7. Batasan uji ini

- Hanya BTCUSDT. Koin kecil lebih volatil (gerak bar lebih besar) tapi spread lebih lebar —
  belum diuji; `TOL_MAKS_BPS = 15` di `binance_testnet.py` akan menolak koin tipis.
- Long-only spot. Short dan leverage tidak diuji.
- Slippage 0,05%/sisi adalah asumsi, bukan pengukuran. Pada 45 trade/hari, slippage nyata
  kemungkinan lebih buruk.
- Tiga aturan indikator adalah wakil, bukan replika strategi poster (yang tidak dipublikasikan).
  Jadi angka ini tidak membuktikan poster berbohong — hanya membuktikan **kelas strategi**
  scalping spot 5m tidak bertahan setelah fee.

## 8. Perintah reproduksi

```
python3 uji_churn.py --selftest
python3 uji_churn.py --run --hari 180 --interval 5m   # 15m | 1h | 4h
cat hasil/churn_4h.json
```
---

# Bagian II — koin liar dan uji pecah waktu (2026-11-27, lanjutan)

Ian minta diuji koin yang lebih volatil, selama itu berguna. Uji ini **tidak** memperbaiki
bot carry; nilainya menutup pertanyaan "strategi gaya Pine" sampai tuntas.

## 9. Biaya nyata vs asumsi

Spread diukur langsung dari `bookTicker` Binance (bukan asumsi):

```
BTCUSDT    0,00 bps     SOLUSDT    1,37 bps
DOGEUSDT   1,72 bps     WIFUSDT    7,26 bps
PEPEUSDT  27,70 bps
```

Asumsi uji (fee 0,1%/sisi + slip 0,05%/sisi = **100 bps/putaran**) **3,6x lebih konservatif**
daripada koin terburuk yang diuji. Jadi hasil negatif di Bagian I bukan artefak asumsi keras.

## 10. Koin liar, jendela 180 hari terakhir

45 kombinasi (5 koin × 3 timeframe × 3 aturan) diuji. Lima teratas:

```
simbol     iv   aturan        trade      NET   beli-diamkan   selisih
PEPEUSDT   4h   rsi_14           15   +31,7%        +5,2%     +26,4%
SOLUSDT    4h   sma_12_48        14   +31,1%       -11,8%     +42,9%
PEPEUSDT   1h   sma_12_48        50   +27,4%        +4,9%     +22,5%
SOLUSDT    4h   breakout_48       5   +19,5%       -11,8%     +31,3%
WIFUSDT    4h   sma_12_48        12   +15,9%       -27,5%     +43,4%
```

Terlihat meyakinkan — beberapa mengalahkan beli-diamkan. **Ini jebakan seleksi:**
yang dilaporkan adalah yang terbaik dari 45 percobaan. Cara membedakan sinyal nyata
dan kebetulan adalah menguji ulang di jendela waktu yang tidak dipakai memilih.

## 11. Uji pecah waktu — tiga jendela 180 hari terpisah

Kombinasi dengan hasil positif di jendela kini diuji di dua jendela sebelumnya
(offset 180 dan 360 hari). Sinyal nyata harus positif di ketiganya.

```
simbol     iv   aturan        kini    -180h   -360h   putusan
PEPEUSDT   4h   rsi_14      +31,7%   -9,2%   -37,5%   hanya jendela kini
SOLUSDT    4h   sma_12_48   +31,1%  -27,4%   +20,9%   hanya jendela kini
PEPEUSDT   1h   sma_12_48   +27,4%  -18,9%   -27,7%   hanya jendela kini
SOLUSDT    4h   breakout_48 +19,5%  -23,6%   +11,7%   hanya jendela kini
WIFUSDT    4h   sma_12_48   +15,9%  -33,4%   -49,7%   hanya jendela kini
PEPEUSDT   4h   breakout_48  +8,5%  +27,4%   -23,7%   hanya jendela kini
SOLUSDT    1h   sma_12_48    +8,5%  -51,5%   -22,8%   hanya jendela kini
```

**0 dari 18 kombinasi positif di tiga jendela berturut-turut.** Setiap "pemenang" berbalik
tanda ketika jendela digeser. Itu tanda tangan kebetulan, bukan edge.

Tiga kombinasi yang tampak paling konsisten pun tidak selamat:
`SOLUSDT 4h sma_12_48` = +31,1 / **−27,4** / +20,9 — positif, negatif, positif.
Tidak ada aturan yang bertahan di semua rezim pasar.

## 12. Keputusan

**Tidak ada jalur uang baru di sini.** Frekuensi transaksi di bawah 5 trade/hari membuat
strategi indikator sederhana berada di sekitar nol (acak dikurangi biaya), dan hasil positif
yang muncul tidak dapat direproduksi di jendela waktu lain.

Yang tetap dipakai: `uji_churn.py --symbol X --interval Y --offset-hari N` sebagai
**alat penolak ide** berstandar tiga jendela. Setiap strategi baru diuji:
`net > 0 di ketiga jendela` atau ditolak — tanpa menulis bot, tanpa VPS, tanpa langganan.
