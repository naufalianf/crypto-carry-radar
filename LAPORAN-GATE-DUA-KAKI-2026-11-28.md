# Gate dua kaki — apa yang ditutup dan apa yang sengaja tidak

**Commit:** `7f44627` (spread spot) · `be45d76` (likuiditas spot) · `a342ca5` (satu sumber gate)

## Masalah yang ditemukan

Candle yang saya bangun **tidak dipakai sistem sama sekali** — itu jawaban jujur yang sudah
saya sampaikan. Tapi pertanyaan "apakah ini benar-benar cocok" memaksa saya membaca jalur
keputusan, dan di situ ada dua lubang nyata.

**Lubang 1 — spread kaki spot tidak pernah dinilai.**

`radar.py:146` menghitung `spot_spread_bps` dan memasukkannya ke `radar.json`. Gate tidak
pernah membacanya. Gate hanya menilai `spread_bps` (perp).

Data nyata saat itu:

```
ROBOUSDT   spread perp 6,26 bps   spread spot 31,30 bps
```

Kaki spot 31,3 bps = **2x batas gate**. Koin itu lolos gate tanpa satu pun pemeriksaan
likuiditas di kaki yang justru menelan biaya masuk-keluar.

**Lubang 2 — gate ada dua, dan salinannya tidak ikut berubah.**

`paper_carry.py:459` punya aturan kandidat sendiri, disalin dari gate lama:

```python
return (r.get("has_spot") and r["bond_days"] >= 30 and r["apr_7d"] >= ENTRY_APR
        and (r["spread_bps"] or 99) <= 15.0 and r["volume_musd"] >= 50.0)
```

Artinya perbaikan gate di `radar.py` **tidak menjangkau jalur yang benar-benar membuka
posisi**. Pada hari perbaikan, hasil kedua gate kebetulan sama (0 koin beda) — tapi itu
kebetulan, bukan jaminan. Dua salinan aturan risiko yang bisa menyimpang diam-diam adalah
bug yang menunggu waktu.

## Yang diperbaiki

**Gate menilai kedua kaki.** `radar.gate()` sekarang menolak kalau `spot_spread_bps` di atas
batas, atau tidak terbaca:

```python
sp = r.get("spot_spread_bps")
if sp is None:
    bad.append("spread spot tak terbaca")
elif sp > max_spread:
    bad.append(f"spread spot {sp:.1f} bps")
```

**Likuiditas spot diukur terhadap ukuran order kita, bukan ambang pasar.** Ini bagian yang
saya hampir salah. Rencana awal saya: `min_spot_vol = 50 jt`. Saya ukur dulu dampaknya:

```
min_spot_vol 50 jt  -> gugur 36 dari 45 koin
min_spot_vol 100 jt -> gugur 40 dari 45 koin
   termasuk BTC (volume spot 1.005 jt) dan ETH (505 jt)
```

Ambang absolut **salah sasaran**: BTC punya volume spot 1.005 jt, tapi yang penting bukan
angka pasar — yang penting order kita 600 dolar tidak menggerakkan harga. Order 600 di pasar
1.005 jt = **0,0001%**.

Jadi aturannya berbasis rasio:

```python
ORDER_USD = 600.0            # nominal satu posisi, dari risk.batas_notional(3000)
MAX_ORDER_VOL_PCT = 0.05     # order <= 0,05% volume spot 24 jam
MAX_ORDER_DEPTH_PCT = 5.0    # order masuk+keluar <= 5% kedalaman 20 level spot
```

Dua tahap, supaya tidak menambah 60 request per scan:

1. Tahap 1 — gate tanpa kedalaman spot (kunci `depth_spot_usd` belum ada, jadi cek itu
   dilewati). Volume spot diambil dari **satu** request `ticker/24hr` spot, bukan 60 klines.
2. Tahap 2 — hanya untuk koin yang masih lolos: ukur kedalaman spot (1 request per koin,
   biasanya 0–3 koin), lalu gate diulang.

**Satu sumber gate.** `paper_carry.layak()` sekarang:

```python
def layak(r):
    return not radar.gate(r, ENTRY_APR)
```

Tidak ada lagi salinan aturan.

## Verifikasi nyata

```
radar.py --selftest    -> selfcheck OK (gate 6 aturan)
                          10 kasus uji: spread spot 40 bps ditolak, tak terbaca ditolak,
                          order 600$ di pasar 1 jt ditolak (0,06% > 0,05%),
                          pasar 500 jt lolos, kedalaman 20rb ditolak, 100rb lolos
scan 60 koin           -> 0 lolos (sama seperti sebelumnya)
paper_carry --selftest -> 35 test OK
unittest discover      -> 57 test OK
6 selftest modul       -> semua OK
```

Gate baru diuji pada ambang eksekusi nyata (4%):

```
ZECUSDT   6,52%  volspot 117,9jt  order/vol 0,0005%  depth 108.287  -> LOLOS
BTCUSDT   5,04%  volspot 1004,7jt order/vol 0,0001%  depth 522.204  -> LOLOS
HYPEUSDT  4,46%  volspot  33,7jt  order/vol 0,0018%  depth  91.589  -> LOLOS
ROBOUSDT  4,45%  volspot   4,4jt  order/vol 0,0136%  depth  60.387  -> tolak
   alasan: spread spot 34,8 bps + volume perp 43 jt (bukan karena aturan baru)
```

Koin bagus tetap lolos. ROBO gugur karena alasan yang sudah ada sebelumnya.

Daemon setelah restart: 4 proses hidup, tick normal, 3 posisi `TAHAN`, tidak ada
`execution_halt.json`.

## Kesalahan saya selama mengerjakan ini

1. **Bangun candle sebelum membaca gate.** Kalau saya baca jalur keputusan lebih dulu, lubang
   `spot_spread_bps` ketemu sebelum satu baris grafik ditulis.
2. **Rencana `min_spot_vol` absolut** akan menolak BTC dan ETH. Ketemu karena saya ukur
   dampaknya sebelum menulis kode, bukan sesudah.
3. **`paper_carry.py` kandidat gagal 28 test** setelah disatukan ke `radar.gate`, karena
   fixture uji tidak punya field baru dan `gate` memakai `r["breakeven_days"]` (akses
   langsung). Dua perbaikan: `gate` pakai `.get()`, dan fixture diisi bentuk data nyata.
   Fixture yang tidak berbentuk data nyata adalah alasan test tidak menangkap bug kelas ini.

## Yang sengaja TIDAK dilakukan

**Candle tidak dicabut.** Alasan: sudah live, nol beban (tidak ada data di repo, browser
memanggil API publik langsung), nol dependensi. Nilainya untuk melihat volatilitas koin
sebelum pasang modal. Kalau mau dicabut, satu commit.

**`min_spot_vol` absolut tidak ditambahkan.** Ditolak setelah diukur: menolak BTC/ETH,
nol manfaat untuk order 600 dolar.

**Ambang APR tidak diturunkan.** Gate sekarang 10%, `ENTRY_APR` 4%. Hari ini nol koin lolos
di 10%, dan hanya 3 koin bersih lolos di 4% (ZEC/BTC/HYPE). Menurunkan ambang = mengubah
kondisi masuk, itu keputusan strategi, bukan perbaikan bug.

## Sisa pekerjaan yang saya lihat

- **`depth_usd` di `radar.json` masih kedalaman PERP**, sedangkan gate memakai
  `depth_spot_usd` yang hanya diisi untuk koin yang lolos. Kolom "kapasitas" di dashboard
  karena itu menampilkan angka perp. Kalau mau kolom itu jujur, tampilkan keduanya.
- **`ORDER_USD = 600` disalin ke `radar.py`**, karena `radar.py` tidak mengimpor `risk.py`.
  Kalau plafon notional berubah di `risk.py`, angka ini wajib ikut diubah. Ini duplikasi yang
  saya pilih sadar (impor `risk` dari `radar` akan membuat siklus), tapi belum ada penjaga
  otomatis yang membandingkan keduanya.
- **Web dashboard belum menampilkan `spot_vol_musd`** dan `spot_spread_bps`. Datanya sudah
  ada di JSON. Tanpa ditampilkan, orang tidak bisa melihat kenapa koin tertentu gugur.