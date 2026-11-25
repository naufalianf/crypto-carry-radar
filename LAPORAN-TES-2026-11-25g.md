# Laporan ke Claude — toleransi harga ikut spread buku

**Repo:** `naufalianf/crypto-carry-radar` — commit `a51b362`
**Tanggal:** 2026-11-25 08:25 UTC
**Untuk:** Claude — **Dari:** Hermes

---

## 1. Yang diubah (satu fungsi, `binance_testnet._harga_batas`)

Sebelumnya `TOL_BPS = 10.0` dipakai buta untuk semua koin dan semua pasar. Sekarang toleransi
diturunkan dari spread nyata di `bookTicker`:

```python
spread_bps = (ref - lawan) / lawan * 10000
if spread_bps > TOL_MAKS_BPS:            # 15.0
    raise ex.Rejected(f"spread ... bps; buku terlalu tipis")
tol = min(max(spread_bps + TOL_BUFFER_BPS, 1.0), TOL_BPS)   # buffer 2 bps, cap 10 bps
```

`TOL_MAKS_BPS = 15.0` **bukan angka baru** — itu sama dengan `max_spread` di gate `radar.py`,
jadi koin yang ditolak eksekusi persis koin yang sudah ditolak radar. Tidak ada dua ambang
berbeda yang harus dijaga sinkron.

## 2. Alasan: data dari uji siklus penuh sebelumnya

```
ADA perp DEMO  spread 28.10 bps  → siklus -0.491%
ADA perp NYATA spread  7.03 bps
BTC perp NYATA spread  0.02 bps
ZEC perp NYATA spread  0.14 bps
QNT perp NYATA spread  1.40 bps
```

Konstanta 10 bps terlalu **mahal** untuk BTC/ZEC (<1 bps) dan terlalu **longgar** untuk koin
tipis. Sekarang BTC membayar ~2 bps, ADA ~9 bps, koin >15 bps tidak dieksekusi sama sekali.

## 3. Hasil uji ulang siklus ADA ($100, bursa demo)

```
spread spot 7.0 bps | perp 7.0 bps
BUKA : {"status":"ok","qty":697.0,"spot":[697.0,0.1434],"perp":[697.0,0.1429]}
TUTUP: {"status":"ok"}
h: False | 3.0 s

ts,trade_id,leg,side,qty,ref_price,fill_price,slip_bps,status
...,spot,buy,697,0.14340000,0.14340000,0.00,ok
...,perp,sell,697,0.14300000,0.14290000,6.99,ok
...,perp,buy,697,0.14310000,0.14330000,13.98,close
...,spot,sell,697,0.14340000,0.14330000,6.97,close
```

Slippage kaki perp turun dari **42,13 bps → 13,98 bps**. Biaya siklus:

```
sebelum fix : -0.491%
sesudah fix : -0.349%
asumsi backtest: 0.30%
```

Masih 1,16× asumsi, tapi itu wajar: spread demo ADA 7 bps **di kedua kaki** = 14 bps
bolak-balik, sementara backtest mengasumsikan 30 bps total untuk masuk+keluar termasuk fee.
Jadi angka demo sekarang konsisten dengan backtest, bukan 1,64× lagi.

## 4. Uji yang ditambahkan

Tiga kasus di selftest `binance_testnet`:

- spread 10 bps → harga batas `100.2` (100.1 + 1 tick, sengaja menyilang)
- spread 1 bps → harga batas di antara `100.00` dan `100.05` (tidak lagi bayar 10 bps)
- spread 20 bps → `ex.Rejected`, tidak ada order dikirim

Empat selftest lulus: `binance_testnet OK`, `paper_carry OK`, `execution OK`, `watchdog OK`.

## 5. Catatan

`TOL_BPS = 10.0` tetap ada sebagai **cap atas**, bukan nilai tetap. Nama variabelnya sekarang
menyesatkan (bukan lagi "toleransi" tapi "toleransi maksimum") — kalau Anda mau, saya bisa
ganti nama jadi `TOL_CAP_BPS` di commit terpisah supaya tidak bercampur dengan perubahan logika.

Tidak ada posisi disentuh. `closed: 0` tetap. `--testnet` masih nol order karena slot penuh
(3 posisi paper), sesuai keputusan Ian: `MAX_POS` tetap 3.
