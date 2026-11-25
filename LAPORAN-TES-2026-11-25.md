# Laporan uji — smoke test dua kaki Binance demo

**Tanggal:** 2026-11-25 04:38 UTC
**Repo:** `naufalianf/crypto-carry-radar`, commit `53a446a`
**Untuk:** Claude (lanjutan telaah kode)
**Dari:** Hermes

---

## Ringkasan

Smoke test **dua kaki** (spot beli + perp short) **LULUS BERSIH**. Empat selftest lulus.
Nol posisi menggantung. Tiga bug nyata ketemu saat kode akhirnya menyentuh exchange
sungguhan — semuanya tidak akan pernah muncul di selftest maupun mock HTTP.

```
FUT host: https://demo-fapi.binance.com
buka: {'status': 'ok', 'qty': 0.002, 'spot': (0.002, 59050.74), 'perp': (0.002, 59025.9)}
tutup: {'status': 'ok'}
```

Verifikasi independen setelahnya (bukan dari respons order):

```
PERP amt 0.0000            datar
SPOT BTC 1.00000000        utuh
SPOT USDT 9999.78168000
FUT wallet 4999.55857326
```

---

## Bug 9 — kunci "Demo Trading API" bukan kunci testnet lama

```
testnet.binancefuture.com/fapi/v2/account   -> -2015 Invalid API-key
demo-fapi.binance.com/fapi/v2/account       -> OK, canTrade=True, wallet 5000
```

Binance punya **dua** testnet futures: yang lama (`testnet.binancefuture.com`, login
akun Binance asli) dan **Demo Trading API** di dalam akun (`demo-fapi.binance.com`).
Kunci dari menu Demo Trading API hanya berlaku di host demo.

Perbaikan: `FUT` pindah ke `demo-fapi.binance.com`, bisa ditimpa lewat env
`BINANCE_TESTNET_FUT_HOST`.

**Pertanyaan untuk Claude:** apakah `paper_carry.py --testnet` perlu tahu host mana yang
dipakai, atau cukup lewat env? Saat ini lewat env, kode tidak berubah.

---

## Bug 10 — futures tidak mengirim `avgPrice`, dan itu meninggalkan posisi menggantung

Kode lama:

```python
harga = float(js["cummulativeQuoteQty"]) / q if pasar == "spot" else float(js["avgPrice"])
```

Dokumentasi Binance bilang `newOrderRespType=RESULT` mengembalikan `avgPrice` untuk
futures. **Kenyataan di host demo: tidak ada `avgPrice` sama sekali.** Respons hanya
berisi `price` (harga limit), `executedQty`, `cumQty`.

Urutan kejadian, dan ini bagian yang penting:

1. Spot beli → FILLED
2. Perp short → FILLED
3. `_hasil()` baca `js["avgPrice"]` → `KeyError`
4. Fungsi berhenti. Tidak ada `finally`. Tidak ada penutupan kaki.
5. **Posisi short 0,002 BTC menggantung di akun.**

Yang menemukannya **bukan** respons order — melainkan query `/fapi/v2/positionRisk`.
Kalau saya mempercayai `KeyError` sebagai "order gagal", posisi itu akan duduk diam
tanpa terdeteksi. Di akun dengan uang sungguhan itu kerugian terbuka yang tidak
dilaporkan siapa pun.

Perbaikan:

```python
def _avg_harga(pasar, js):
    q = float(js.get("executedQty") or 0)
    if q <= 0:
        return 0.0
    cq = js.get("cummulativeQuoteQty") or js.get("cumQuote")
    if cq:
        return float(cq) / q
    if js.get("avgPrice"):
        return float(js["avgPrice"])
    return float(js.get("price") or 0.0)
```

Selftest baru mengunci empat bentuk respons (cumQuote, avgPrice, price, executedQty 0).

**Aturan yang saya usulkan untuk `execution.py`:** respons order tidak boleh dipakai
sebagai bukti posisi. Setiap jalur yang membuka kaki harus bisa ditutup tanpa
bergantung pada parsing respons — artinya `try/finally` di `buka_carry()`, dan
rekonsiliasi memakai `positionRisk`/`openOrders` sebagai sumber kebenaran.

Saya **belum** menambahkan `try/finally` itu. Mau dengar pendapat Claude dulu apakah
lebih benar ditangani di `buka_carry()` atau di lapisan pemanggil.

---

## Bug 11 — `slip_bps` kaki perp diukur terhadap harga spot

`smoke()` lama:

```python
r = ex.buka_carry(b, sym, qty * ref, ref, ref, tid)   # ref spot dipakai dua kali
```

Hasil di `execution_fills.csv`:

```
perp,sell,ref 59166.67,fill 59137.30,slip +4.96
perp,buy, ref 59166.67,fill 59305.40,slip +23.45
```

Itu **bukan slippage**. Itu basis spot-perp yang tercampur ke kolom slippage. Setelah
referensi perp diambil dari `fapi/v1/ticker/bookTicker`:

```
perp,sell,ref 59085.00,fill 59025.90,slip +10.00
perp,buy, ref 59122.00,fill 59181.20,slip +10.01
```

+10,00 bps = tepat `TOL_BPS = 10.0`. Order limit IOC menyilang sebesar toleransi, jadi
ini angka yang **benar** untuk buku demo. Tetap **bukan** perkiraan biaya pasar asli —
buku demo tipis, spread pasar asli beberapa bps.

---

## Catatan operasional

- IP mesin Hermes sempat kena `-1003 IP banned` di host futures lama karena request
  diagnosis berlebihan (bukan dari kode bot). Endpoint publik tidak terpengaruh.
  Selftest dan smoke tidak terpengaruh.
- Kunci tidak pernah masuk repo. Diverifikasi: grep potongan kunci futures di
  `binance_testnet.py` dan `HANDOFF-HERMES.md` dari raw GitHub = **0 match**. Kunci
  tinggal di `.testnet.env` mode 600, di luar repo.
- Kunci sudah pernah lewat chat, jadi sebaiknya di-revoke + generate ulang setelah
  semua pengujian selesai.

---

## Yang menunggu keputusan Naufal (bukan keputusan saya)

1. **Celah A** — 2 posisi paper lama di notional 1000 vs plafon baru 600. PnL yang
   tampil 40% lebih besar dari aturan baru. Rekomendasi saya opsi (a): biarkan tutup
   sendiri + label di dashboard.
2. **Menyalakan `--testnet`** — order demo nyata 600/posisi, maks 3. Belum dinyalakan.

---

## Pertanyaan langsung untuk Claude

1. `try/finally` untuk penutupan kaki — di `buka_carry()` atau di pemanggil?
2. Apakah `total_pnl()` sebaiknya memakai notional aktual per posisi atau notional
   plafon saat ini? Keduanya memberi angka berbeda untuk posisi lama.
3. `paper_carry_state.json` masih di-track git — satu-satunya temuan dari 7 yang belum
   ditambal. Ada alasan untuk mempertahankannya di git?
