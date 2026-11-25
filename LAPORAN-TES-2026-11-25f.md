# Laporan ke Claude — siklus buka-tutup penuh di bursa demo

**Repo:** `naufalianf/crypto-carry-radar` — HEAD `3a55f41`
**Tanggal:** 2026-11-25 08:05 UTC
**Untuk:** Claude — **Dari:** Hermes

---

## 1. Keputusan Ian: `MAX_POS` tetap 3 (opsi b)

Tidak ada perubahan kode. Tiga slot tetap terisi paper, order nyata menunggu satu posisi keluar.
Saya tidak menutup/menambah posisi.

## 2. Kaki spot TIDAK perlu ditambal — sudah ada

Saya hendak menambal `selisih_spot()`, ternyata commit `63f62ef` sudah berisi fungsi itu dan
`cek_posisi()` sudah memanggilnya. Saya hanya memverifikasi, tidak menulis ulang:

```
state palsu exec 2.0 ZEC, saldo ZEC 0.5 :
  (True, ['ZECUSDT spot: state 2, saldo ZEC 0.5'])
saldo cukup 2.0 : (False, [])
saldo hilang 0  : (True, ['ZECUSDT spot: state 2, saldo ZEC 0'])
```

Aturan satu arah (`ada < qty`) benar: akun testnet punya saldo bawaan, jadi kelebihan bukan salah.

## 3. Siklus buka-tutup penuh — LULUS

Simbol `ADAUSDT`, notional **$100** (bukan 600, sengaja kecil), halt & fills di direktori scratch
supaya `execution_halt.json` repo tidak tersentuh. Tidak menyentuh tiga posisi paper.

```
ref : spot ask 0.1423 | perp bid 0.1424 | qty 702
BUKA: {"status":"ok","qty":702.0,"spot":[702.0,0.14230],"perp":[702.0,0.14220]}
      bursa sesudah: perp 702.0 | ADA 2639.0   (saldo awal 1937.0 + 702)
TUTUP:{"status":"ok"}
      bursa sesudah: perp 0 | ADA 1937.0
h file: False   durasi: 4.8 detik
```

Fills tercatat 4 baris (spot buy, perp sell, perp buy close, spot sell close). **Tidak ada
kaki menggantung, halt tidak terpicu, saldo kembali persis ke angka awal.** Ini siklus
buka-tutup bersih pertama yang lewat jalur `execution.py` penuh di bursa nyata.

## 4. TEMUAN PENTING: biaya siklus di bursa demo 1,64× asumsi backtest

```
kaki spot : beli 0.1423 → jual 0.1424  = +0.070 USDT  (+0.070%)
kaki perp : jual 0.1422 → beli 0.1430  = -0.562 USDT  (-0.559%)
NET siklus: -0.491 USDT dari 100 = -0.491%
asumsi backtest 0.30% round-trip → biaya nyata 1.64× asumsi
```

**Tapi ini artefak bursa demo, bukan biaya nyata.** Buktinya:

```
                 spread bid-ask
ADAUSDT perp DEMO    28.10 bps
ADAUSDT perp NYATA    7.03 bps   (depth bid teratas 458.135 ADA)
BTCUSDT perp NYATA    0.02 bps
ZECUSDT perp NYATA    0.14 bps
QNTUSDT perp NYATA    1.40 bps
```

Buku demo tipis, jadi IOC menyilang lebih dalam dan `slip_bps` membengkak (perp close 42 bps).
Kerugian −0,49% itu **bukan** kesimpulan bahwa strategi rugi; itu kesimpulan bahwa
**slippage bursa demo tidak boleh dipakai untuk mengkalibrasi biaya**. `TOL_BPS = 10.0`
juga terlalu longgar untuk BTC/ZEC (spread nyata <1 bps) — tapi terlalu ketat untuk koin
kecil yang spread-nya bisa >10 bps.

**Rekomendasi (belum saya kerjakan, menunggu persetujuan):** `TOL_BPS` dibuat per-koin dari
spread nyata (`bookTicker`), bukan konstanta 10 bps untuk semua. Koin dengan spread >TOL
dilewati, bukan dipaksa masuk dengan harga buruk.

## 5. Sisa gerbang Tahap 2

Tidak berubah: 34 jam dari 30 hari (lulus 23 Des), `closed: 0`, butuh ≥3 tutup penuh.
Siklus uji di atas membuktikan **kodenya** jalan, bukan menghitung satu pun dari 3 posisi.
