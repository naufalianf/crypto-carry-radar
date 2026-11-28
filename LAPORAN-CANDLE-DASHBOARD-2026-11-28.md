# Candle di dashboard — apa yang ditambahkan

**Commit:** `ee3132c` · **Live:** https://crypto-carry-radar-webvercel.vercel.app/

## Yang berubah

Klik nama simbol di tabel → panel candlestick muncul di bawah tabel. Tiga selang:
**1 jam / 4 jam / 1 hari**, 120 candle, label harga di kanan, label waktu di bawah.

Sebelumnya nama simbol adalah tautan ke `binance.com/futures/...` — dan itu **mati** di
jaringan Indonesia karena Internet Positif memblokir domain `binance.com`. Jadi tautan lama
tidak berguna. Sekarang tautan itu diganti panel grafik internal.

## Sumber data: kenapa spot, bukan perpetual

Satu-satunya domain Binance yang **lolos Internet Positif** dan mengirim CORS `*` adalah
`data-api.binance.vision` (Spot API publik). `fapi.binance.com` mengirim CORS `*` juga, tapi
domainnya diblokir di jaringan pengguna — jadi tidak mungkin dipakai dari browser.

Konsekuensi yang ditulis terus terang di panel: **candle spot, bukan perpetual**. Untuk carry
delta-neutral, arah harga tidak penting (dua kaki saling menutup), jadi candle spot sudah cukup
untuk melihat volatilitas dan likuiditas. Yang tidak bisa dilihat dari grafik ini: funding.

## Nol beban tambahan

- Tidak ada data baru di repo. Browser memanggil API publik langsung.
- Tidak ada dependensi baru. SVG ditulis dengan string, tanpa library chart.
- Tidak ada perubahan di `radar.py` atau pipeline data.

## Perilaku saat gagal

15 dari 45 koin di radar **tidak punya pasar spot** (`has_spot: false`). Untuk koin itu,
panel tidak mencoba fetch lalu menampilkan `Failed to fetch` — pesan yang tidak menjelaskan
apa pun. Radar sudah tahu jawabannya, jadi panel langsung bilang:

> `VELVETUSDT tidak punya pasar spot`
> `Candle diambil dari pasar spot Binance; koin ini hanya ada di futures.`
> `Carry butuh dua kaki. Tanpa pasar spot, koin ini tidak bisa dipakai walau APR-nya tinggi.`

```js
const row = (data?.rows || []).find(r => r.symbol === sym);
if (row && row.has_spot === false) { gagalCandle(sym, "tidak punya pasar spot"); return; }
```

## Verifikasi

Lokal (`preview` di `127.0.0.1:8913`, data dari raw GitHub):

```
BTCUSDT 4 jam   -> 120 candle, meta "4 jam · 120 candle · terakhir 59274 -21.99%"
BTCUSDT 1 hari  -> 120 candle, meta berubah benar
VELVETUSDT      -> "grafik tidak tersedia", pesan ramah, nol error konsol
```

Live di Vercel (setelah deploy, fetch ulang dari domain publik):

```
rows 20, klik BTCUSDT -> "4 jam · 120 candle · terakhir 59226 -22.05%", 120 rect
```

Cek visual desktop + mobile: candle jelas, wick terbaca, label Y dan grid sejajar (grid
`y=238/181/124/67/10`, label `y=242/185/128/71/14` — selisih 4px = baseline teks), tidak ada
tumpang tindih, `scrollWidth == innerWidth` di 390px (tidak ada overflow horizontal).

Bug yang ketemu saat uji visual dan sudah diperbaiki: tombol selang harian awalnya ditulis
`1h`, sama dengan jam (`1h`). Diganti label penuh `1 jam / 4 jam / 1 hari`. `aria-pressed`
ditambahkan supaya pembaca layar tahu selang mana yang aktif.

## Yang belum

- **Funding tidak divisualkan.** Grafik funding per koin (yang sebenarnya jadi sumber untung)
  sudah ada dalam bentuk sparkline kolom "tren 30h". Kalau mau grafik funding besar seperti
  candle, datanya sudah ada di `radar.json` (`spark`, 30 titik) — tinggal digambar.
- **Zoom/pan tidak ada.** 120 candle tetap; untuk melihat lebih detail perlu ganti selang.
- **Perp klines tidak bisa dari browser Indonesia.** Kalau nanti perlu candle perp, harus
  lewat server (snapshot `radar.json`), bukan fetch langsung.