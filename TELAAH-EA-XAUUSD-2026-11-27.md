# Telaah thread EA XAUUSD (@yoseandreas) — 2026-11-27

**Untuk:** Claude · **Repo:** `naufalianf/crypto-carry-radar` · **Sumber:** threads.com/share/BAPWzOx2NX

## 0. Ringkas

Tiga klaim masuk: EA tick-delta grid ($50→$380), EA single entry ($10k→$319k), dan
saran teknis "order flow XAUUSD tidak reliable, pakai GC". Dua klaim angka **tidak lolos
uji aritmetika**; satu saran teknis **benar**.

Tidak ada yang diambil untuk bot carry. Bot carry delta-neutral 1x tidak punya kekerabatan
dengan grid martingale berleverage.

## 1. Harga emas nyata periode klaim

Diambil dari PAXGUSDT (token emas 1:1 oz, Binance), 1–26 Nov 2026:

```
open 1 Nov   3.899,26
close 26 Nov 3.561,46     = -8,66%
low          3.425,17  (25 Nov)
high         4.125,29  (9 Nov)
range                 = 20,44% = $700,12/oz
```

Bulan Nov 2026 adalah **longsor emas**, bukan pasar tenang.

## 2. Klaim @yoseandreas: $50 → $380 (cent 5.000 → 33.081)

Angka sendiri: profit $330 dalam ~19 hari, equity $380, drawdown 0,07%, 0.01 lot bertumpuk.

Aritmetika:

```
0.01 lot XAUUSD = 1 oz. harga $3.655 -> notional $3.655/posisi
margin 1:500 = $7,31/posisi      -> $50 muat 6,8 posisi
margin 1:100 = $36,55/posisi     -> $50 muat 1,4 posisi
```

Kesimpulan yang bisa diuji: dengan range emas **$700/oz**, enam posisi 0.01 lot yang menangkap
sebagian gerak itu bernilai **sampai $4.200**. Klaimnya hanya **$330**. Artinya profit itu
**mudah** dihasilkan tanpa keahlian apa pun selain arah short yang benar di pasar yang longsor.

Drawdown 0,07% = **$0,27** di pasar bergerak 20%. Dua kemungkinan:
1. EA menutup rugi sangat cepat (maka win rate tinggi, tapi satu gerakan salah menghapus banyak), atau
2. Screenshot diambil pada momen equity di puncak, bukan maksimum drawdown sepanjang 19 hari.

Yang **tidak** dia sebutkan: modal minimum untuk bertahan, dan drawdown terdalam yang pernah terjadi.
Drawdown 0,07% pada grid 6 posisi **tidak mungkin** bertahan kalau emas bergerak 3% melawan arah —
dan emas bergerak >2% di **7 dari 26 hari** periode itu.

## 3. Klaim @adipuratama: $10k → $319k (Jan–Nov 2026)

Ini klaim yang paling mudah dipatahkan, karena datanya ada.

```
emas 1 Jan 2026  : 4.337
emas 26 Nov 2026 : 3.654,8   = -15,7%  (TURUN 10 bulan)
klaim return     : +3.090% = 31,9x
```

Perhatikan: klaimnya **31,9x** pada periode ketika **harga emas turun 15,7%**. Untuk hasil
seperti itu, EA harus menangkap hampir setiap ayunan naik dan turun. Itu bukan EA, itu
ramalan.

Uji batas fisiknya:

```
ekuitas $10.000, margin 1:500 -> notional maksimum $5.000.000 = 1.368 oz emas
gerak emas 1% = $36,55/oz x 1.368 oz = $50.000 = 500% ekuitas
gerak emas 0,2% = 100% ekuitas
```

Dengan leverage maksimum yang diizinkan broker, **gerak 0,2% sudah melikuidasi akun**.
Backtest yang menghasilkan 31,9x pasti memakai asumsi yang tidak bisa dieksekusi:
slippage nol, spread nol, fill sempurna, atau tanpa stop-out. Dan dia sendiri bilang
"masih dikembangkan karena takut cuma hoki" — instingnya benar.

## 4. Saran @krisrawitno: pakai GC untuk order flow — BENAR

XAUUSD di broker retail adalah **proxy** dari Gold Futures (GC/COMEX). Broker retail tidak punya
akses ke order book COMEX; yang mereka punya hanya agregasi likuiditas sendiri. Jadi:

- "order flow XAUUSD" di MT5 = order flow **broker itu**, bukan pasar emas dunia.
- Tick volume MT5 = jumlah tick yang dikirim broker, bukan volume nyata.
- Tick-delta dari data seperti ini mengukur **perilaku broker**, bukan ketidakseimbangan pasar.

Ini satu-satunya bagian thread yang secara teknis solid. Kalau seseorang mau serius dengan
order flow emas, datanya harus dari CME (GC futures), berbayar.

## 5. Uji apakah emas beda kelas dari crypto

Alat yang sama (`uji_churn.py`), PAXGUSDT sebagai proxy emas, biaya 100 bps/putaran,
tiga jendela 180 hari terpisah:

```
iv   aturan        kini     -180h   -360h   putusan
1h   breakout_48  -11,0%    +1,9%  +11,3%   campur (26 trade)
1h   rsi_14       -31,9%   -15,8%   -5,6%   rugi terus (49 trade)
1h   sma_12_48    -17,8%    +7,6%   -4,1%   campur (56 trade)
4h   breakout_48   -0,5%    +0,5%  +19,2%   campur (3 trade)
4h   rsi_14       -17,3%    -3,2%   +5,2%   campur (17 trade)
4h   sma_12_48    -11,4%   +10,2%  +18,1%   campur (11 trade)
```

**0 dari 6 kombinasi** lolos tiga jendela. Emas **tidak** berbeda kelas dari crypto untuk
strategi indikator: hasil positif muncul di satu jendela lalu hilang di jendela lain.
Perbedaan emas vs crypto adalah **volatilitas**, bukan **predictability**.

## 6. Keputusan untuk bot kita

Tidak ada yang diambil. Tiga alasan:

1. **Beda spesies.** Bot carry: delta-neutral, 1x, dua kaki berlawanan arah, pendapatan dari
   funding. Grid martingale: searah, berleverage, tanpa stop loss. Tidak ada sumbu pembanding.
2. **Klaim angkanya gugur.** $10k→$319k secara fisik tidak mungkin pada leverage 1:500 dengan
   emas turun 15,7%. Klaim $50→$380 mungkin, tapi tidak membuktikan keahlian.
3. **Tidak ada kode yang bisa diambil.** "Tick-delta grid + order flow + EMA50" adalah nama
   strategi, bukan algoritma. Tidak ada detail entry, ukuran grid, atau aturan keluar.

Yang tetap berguna dari thread ini: **saran #3** — kalau suatu hari kita menyentuh emas,
jangan pakai data order flow XAUUSD retail. Pakai GC. Itu pengetahuan nyata dan gratis.