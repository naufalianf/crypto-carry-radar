# Yang harus dilakukan Ian — urutan, satu per satu

Dibuat 2026-11-28. Sisa pekerjaan yang **hanya bisa** dikerjakan Ian.

---

## LANGKAH 1 — Buat akun di Binance (kalau belum ada)

KYC wajib: KTP + selfie. Prosesnya 1–2 hari kerja, kadang lebih kalau antrean ramai.

---

## LANGKAH 2 — Isi saldo

**Jangan kirim dana dulu.** Tunggu sampai Langkah 3 dan 4 beres. Akun kosong tidak bisa
diuji, tapi akun berisi dengan kunci yang belum diuji = risiko yang tidak perlu.

---

## LANGKAH 3 — Buat API key dengan izin minimum

Menu: **Profil → API Management → Create API**.

Centang **HANYA**:
- ✅ Enable Spot & Margin Trading
- ✅ Enable Futures

Jangan centang apa pun yang lain.

**JANGAN** centang:
- ❌ Enable Withdrawals  ← ini yang paling penting
- ❌ Enable Internal Transfer
- ❌ Enable Universal Transfer
- ❌ Permissions → apapun selain trading

**IP whitelist** (opsional tapi sangat disarankan):
Masukkan `43.157.228.18` — IP server tempat bot berjalan.
Tanpa whitelist, kunci bisa dipakai dari mana saja kalau bocor. Dengan whitelist, kunci hanya
bisa dipakai dari server ini, jadi bocornya kunci di luar server tidak berguna.

---

## LANGKAH 4 — Simpan kunci di tempat yang benar

Kunci **tidak boleh** masuk chat, kode, atau git. Simpan di file `.env` di mesin/server,
mode 600, di luar repo.

Format (isi dengan nilai asli):

```
BINANCE_LIVE_KEY=..._key_spot_izin_trade_saja
BINANCE_LIVE_SECRET=..._secret_spot
BINANCE_LIVE_FUT_KEY=..._key_futures
BINANCE_LIVE_FUT_SECRET=..._secret_futures
```

Kalau satu kunci dipakai untuk spot dan futures (Binance kadang mengizinkan), baris FUT
boleh dikosongkan — kode akan jatuh ke kunci spot.

**Kalau Bro mau saya yang menyimpan:** kirim lewat chat = JANGAN. Yang benar: Bro tulis
sendiri ke file. Kalau perlu saya bantu, saya bisa siapkan file kosong dengan izin 600 dan
Bro isi nilainya lewat editor — tapi nilai kunci tidak pernah lewat chat.

---

## LANGKAH 5 — Kabari saya bahwa kunci sudah ada

Setelah itu saya uji **koneksi baca saja** dulu (cek saldo, tanpa order). Nol risiko.
Kalau lolos, baru uji order kecil.

---

## LANGKAH 6 — Tunggu gerbang 30 hari

**2026-12-23 21:56 UTC** (~25 hari lagi).

Yang dinilai: bot paper menahan 3 posisi 30 hari tanpa kill switch, tanpa HALT, tanpa
selisih dua kaki. Kalau lulus, saya naikkan `MAX_EXEC_POS` dari 1 ke 3.

---

## LANGKAH 7 — Order nyata pertama

Setelah gerbang lulus **dan** satu siklus buka-tutup terbukti, order pertama dikirim dengan
modal minimum yang Bro siap kehilangan seluruhnya.

**Jujur:** hasil realistis bot ini **+7,5%/tahun**. Di 3.000 USD itu **~19 USD/bulan**. Bukan
cara cepat kaya. Yang membuatnya layak adalah konsistensi dan risiko kecil, bukan angka besar.

---

## Yang TIDAK perlu Bro lakukan

- ❌ Beli VPS — bot sudah jalan di server ini
- ❌ Langganan TradingView — kita tidak pakai webhook
- ❌ Install skill/repo dari internet — sudah diuji dan ditolak
- ❌ Ikut EA grid/martingale XAUUSD — sudah diuji aritmetikanya, gugur

---

## Ringkas: 4 hal, urut

1. Akun + KYC Binance
2. API key izin trade saja, withdraw MATI, IP whitelist `43.157.228.18`
3. Simpan kunci di file `.env` mode 600, bukan di chat
4. Kabari saya — sisanya saya kerjakan

Sambil menunggu, tidak ada yang perlu Bro kerjakan. Bot jalan sendiri.