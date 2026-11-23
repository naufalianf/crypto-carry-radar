# Radar Funding — versi Vercel

Dashboard pemantau peluang **carry funding** (delta-neutral). Tidak menyentuh saldo,
tidak butuh API key, tidak ada proses yang harus hidup terus.

## Kenapa versi ini ada

Versi lama (`../web/server.py`) butuh server Python hidup + tunnel + keepalive cron —
tiga titik gagal. Kalau salah satu mati, panel tidak bisa dibuka. Versi ini:

- **Halaman statis** (`index.html`) — Vercel yang melayani, tidak bisa mati.
- **Satu fungsi serverless** (`api/radar.py`) — memindai Binance dari sisi server,
  jadi tidak terpengaruh blokir ISP di sisi HP Bro.
- Data di-cache di edge Vercel **5 menit**, jadi request berikutnya instan dan
  Binance tidak dipanggil berlebihan.

Waktu pindai terukur: **60 koin ≈ 1,4 detik** (16 thread), jauh di bawah batas 10 detik.

## Deploy — cara paling gampang (tanpa install apa pun)

1. Taruh folder ini di sebuah repo GitHub (upload lewat web GitHub juga bisa).
2. Buka vercel.com → **Add New → Project → Import** repo tadi.
3. **Framework Preset: Other**. Kalau folder ini ada di dalam repo, set
   **Root Directory = web_vercel**.
4. **Deploy**. Selesai — dapat URL `https://<nama>.vercel.app`.

## Deploy — cara CLI

```bash
cd web_vercel
npx vercel --prod
```

## Variabel opsional

| Nama | Default | Arti |
| --- | --- | --- |
| `RADAR_TOP` | 60 | jumlah koin yang dipindai (dari perp kripto paling likuid) |
| `RADAR_THRESHOLD` | 8 | ambang APR (%) supaya koin ditandai "lolos gate" |

Set di Vercel → Settings → Environment Variables.

## Uji lokal

```bash
cd web_vercel
python3 -c "
import sys, threading, time, urllib.request, json
sys.path.insert(0,'.')
from api import radar as m
from http.server import ThreadingHTTPServer
srv = ThreadingHTTPServer(('127.0.0.1', 8899), m.handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.5)
print(json.load(urllib.request.urlopen('http://127.0.0.1:8899/api/radar'))['alerts'])
srv.shutdown()"
```

Lalu buka `http://127.0.0.1:8899` lewat server statis (`python3 -m http.server 8898`)
untuk melihat halamannya.

## Batas yang perlu diingat

- Vercel **tidak menyimpan state**. Paper trading dan backtest tetap dijalankan di
  host/VPS (`../paper_carry.py`, `../runner.py`, `../bot.py`).
- Aturan gate di `api/radar.py` adalah **salinan** dari `../radar.py`. Kalau salah satu
  diubah, ubah dua-duanya.
- Fungsi ini hanya membaca data publik. Tidak ada order, tidak ada API key.

## Isi gate

Koin ditandai "lolos" hanya kalau semua ini benar:

- punya **pasar spot** (tanpa itu carry mustahil),
- umur listing ≥ 30 hari,
- spread perp ≤ 15 bps,
- volume 24 jam ≥ $50jt,
- "balik modal" > 3 hari (APR tidak liar).
