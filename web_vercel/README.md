# Radar Funding — versi Vercel

Halaman statis untuk memantau peluang carry delta-neutral (beli spot + short
perpetual) dari data publik Binance. Tidak menyentuh saldo, tidak butuh API key.

## Arsitektur — Vercel TIDAK memanggil Binance

`fapi.binance.com` membalas **HTTP 451 Unavailable For Legal Reasons** untuk IP
cloud (AWS/GCP/Vercel), apa pun region yang dipilih. Futures API juga tidak punya
domain publik pengganti seperti `data-api.binance.vision` di Spot API. Fungsi
serverless di sini tidak akan pernah berhasil memanggil Binance Futures.

Pembagiannya:

```
mesin lokal (bisa akses Binance)          Vercel (statis)
  scan_and_push.py                          index.html
    → radar.scan()                          → fetch radar.json dari
    → web/radar.json                          raw.githubusercontent.com
    → git commit + push                       → render tabel
```

## Deploy

1. Vercel → **Add New Project** → import repo `naufalianf/crypto-carry-radar`
2. **Root Directory: `web_vercel`** — wajib, kalau tidak build gagal
3. Framework Preset: **Other**, tanpa build command, tanpa env var
4. Deploy

Repo harus **public** supaya `raw.githubusercontent.com` bisa dibaca browser.

## Pipeline data

Di mesin yang bisa akses Binance:

```bash
python3 scan_and_push.py --run      # sekali: scan + commit + push
python3 scan_and_push.py --loop     # tiap 4 jam
```

Snapshot lebih dari 6 jam memunculkan peringatan "data basi" di banner.

## Uji lokal

```bash
python3 preview_vercel.py --port 8901
```

Menyajikan `web_vercel/index.html` apa adanya. Data tetap diambil dari GitHub,
jadi yang diuji sama persis dengan yang nanti tampil di Vercel.

## Batas yang perlu diingat

- Data **setelat snapshot terakhir** (4 jam), bukan real-time per request.
  Untuk funding carry berhorizon hari, ini tidak signifikan.
- Kalau mesin pemindai mati, panel menampilkan data basi + peringatan.
- Tombol "muat ulang" hanya menarik snapshot terbaru; tidak memicu pemindaian baru.
- Vercel **tidak menyimpan state**. Paper trading dan backtest tetap di
  host/VPS (`../paper_carry.py`, `../runner.py`, `../bot.py`).
- Aturan gate hanya ada di `../radar.py`. Folder ini tidak menyimpan salinan,
  jadi tidak ada risiko dua versi berbeda.

## Isi gate

Koin ditandai "lolos" hanya kalau semua ini benar:

- punya **pasar spot** (tanpa itu carry mustahil),
- umur listing ≥ 30 hari,
- spread perp ≤ 15 bps,
- volume 24 jam ≥ $50jt,
- APR 7d ≥ ambang (default 8%),
- "balik modal" > 3 hari (APR tidak liar).
