# Laporan: saklar mode bursa (testnet/live) — 2026-11-28

**Untuk:** Claude · **Commit:** lihat `git log -1` · **Repo:** `naufalianf/crypto-carry-radar`

## 0. Ringkas

Jalur uang asli sebelumnya diblokir satu baris: `SPOT` ditulis mati ke
`https://testnet.binance.vision`, tanpa cara menimpanya dari luar. Sekarang host dipilih
lewat saklar `BINANCE_MODE`, dengan pagar berlapis. **Nol order nyata terkirim, nol perubahan
pada strategi.** Default tetap testnet.

## 1. Desain: saklar mode, bukan variabel host

Alternatif yang **ditolak**: satu variabel `BINANCE_SPOT_HOST` berisi URL. Alasannya bukan
gaya — variabel host tunggal bisa terisi tanpa sadar (dari `.env` lama, dari skrip lain,
dari sisa eksperimen) dan langsung mengarahkan order ke bursa dengan uang asli. Saklar mode
punya properti yang tidak dimiliki variabel host:

- default `testnet` — tidak adanya konfigurasi berarti aman;
- nilai tak dikenal = `RuntimeError` saat import, bukan diam-diam jalan;
- kunci live **wajib nama sendiri**, jadi kunci testnet tidak bisa terpakai di bursa nyata
  dan sebaliknya (salah pasang = ditolak `-2015`, bukan jalan diam-diam).

```python
MODE = os.environ.get("BINANCE_MODE", "testnet").strip().lower()
if MODE == "live":
    SPOT = os.environ.get("BINANCE_LIVE_SPOT_HOST", "https://api.binance.com")
    FUT  = os.environ.get("BINANCE_LIVE_FUT_HOST",  "https://fapi.binance.com")
elif MODE == "testnet":
    FUT  = os.environ.get("BINANCE_TESTNET_FUT_HOST", "https://demo-fapi.binance.com")
else:
    raise RuntimeError(f"BINANCE_MODE tidak dikenal: {MODE!r}")
```

Nama kunci mengikuti mode: `BINANCE_LIVE_KEY/SECRET` vs `BINANCE_TESTNET_KEY/SECRET`.

## 2. Pagar kedua di titik nyala

`binance_testnet.py` hanya soal ke mana order diarahkan. Yang menyalakan bot adalah
`start_all.sh`, jadi pagar dipasang di situ:

```bash
case "$BINANCE_MODE" in
  testnet) ;;
  live)
    [ "${KUNCI_LIVE_DISETUJUI:-0}" = "1" ] || { echo "butuh KUNCI_LIVE_DISETUJUI=1" >&2; exit 1; }
    echo "!!! MODE LIVE ... Ctrl-C dalam 10 detik untuk batal."; sleep 10 ;;
  *) echo "BINANCE_MODE tidak dikenal: $BINANCE_MODE" >&2; exit 1 ;;
esac
```

Dua syarat harus benar bersamaan, dan satu di antaranya (`KUNCI_LIVE_DISETUJUI`) adalah
tindakan manusia, bukan sisa environment. Jeda 10 detik memberi jendela batal.

Blok ini diletakkan **setelah** cabang `stop`, jadi `bash start_all.sh stop` tidak pernah
meminta konfirmasi. Menghentikan bot harus selalu lebih mudah daripada menyalakannya.

## 3. Verifikasi yang dijalankan

Selftest `binance_testnet.py` ditambah empat kasus lewat `subprocess` (MODE dibaca saat
import, jadi harus proses baru):

```
default                      -> testnet, host testnet, kunci BINANCE_TESTNET_KEY
BINANCE_MODE=live            -> api.binance.com + fapi, kunci BINANCE_LIVE_KEY
BINANCE_MODE=liv (salah ketik) -> exit != 0, "BINANCE_MODE tidak dikenal"
BINANCE_MODE=live tanpa kunci  -> exit != 0, "kunci live belum diisi"
```

Satu kegagalan saat menulis tes ini **bukan bug kode**: argumen `key` memang menang atas env,
jadi tes awalnya memakai `BinanceTestnet("k","s")` yang menutupi pembacaan env. Tes diperbaiki
memakai `None,None`.

Uji `start_all.sh` nyata:

```
BINANCE_MODE=live bash start_all.sh     -> exit 1, proses paper_carry 2 -> 2 (nol proses baru)
BINANCE_MODE=prod bash start_all.sh     -> exit 1
BINANCE_MODE=live bash start_all.sh stop -> keempat daemon berhenti, tanpa konfirmasi
TESTNET=1 bash start_all.sh             -> keempat daemon hidup lagi
```

Suite penuh:

```
execution              OK
paper_carry            selfcheck OK
watchdog               OK
supervisor             OK
binance_testnet        OK
unittest discover      57 tests OK
```

Setelah restart, tick berjalan normal, ketiga posisi `TAHAN`, tidak ada `execution_halt.json`.

## 4. Apa yang belum

1. **Kunci live belum ada.** Nama sudah disiapkan, nilainya belum. Ian yang membuat
   (izin trade saja, withdraw mati, IP whitelist).
2. **Siklus buka-tutup dari daemon belum terbukti.** Fungsi `keluar()` lulus manual (ADA)
   tapi daemon masih `closed: 0` — seluruh slot terisi sampai `MAX_DAYS 60` (≈ 2027-01-22).
3. **Host live belum pernah disentuh.** `api.binance.com` diblokir Internet Positif dari
   jaringan Ian; dari server ini DNS-nya perlu diuji terpisah sebelum hari H.
4. **Nilai `MODE` tidak dicatat ke log startup.** Disengaja: log bisa terkirim ke Telegram.
   Kalau ingin jejak, cetak `MODE` saja (bukan host, bukan kunci) saat `__main__`.

## 5. Dampak ke jadwal MVP

Saklar sudah ada, jadi MVP uang asli tidak lagi menunggu pekerjaan kode di sisi ini.
Sisanya dua hal yang tidak bisa dipercepat: 30 hari paper (gerbang **2026-12-23 21:56 UTC**)
dan siklus buka-tutup pertama.

Kalau siklus pertama harus dibuktikan lewat `keluar()` di state terpisah, itu pekerjaan
berikutnya dan **tidak** mengubah strategi — hanya memakai fungsi yang sudah ada.