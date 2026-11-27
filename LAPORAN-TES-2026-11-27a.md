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