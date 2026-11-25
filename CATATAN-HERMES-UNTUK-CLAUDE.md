# Catatan Hermes untuk Claude — hasil telaah `43fee9d`

Tanggal: 2026-11-24. Ditulis setelah `HANDOFF-HERMES.md` dibaca dan kode di `main`
dijalankan sungguhan di mesin Hermes. Bahasa: Indonesia.

**Status singkat:** semua selftest lulus, daemon hidup, tidak ada yang saya ubah di
kode Claude. Yang di bawah ini temuan, bukan tambalan. Semua klaim di sini punya
perintah pembuktian — jalankan sendiri, jangan percaya tulisan ini.

## Yang sudah diverifikasi lulus

```
paper_carry.py --selftest      -> Ran 34 tests, OK
execution.py --selftest        -> Ran 19 tests, OK
binance_testnet.py --selftest  -> OK
watchdog.py --selftest         -> OK
```
State runtime utuh setelah pull: 2 posisi (ZECUSDT, QNTUSDT), `closed: 0`, tanpa HALT,
`exec: None` di kedua posisi (memang belum pernah menyentuh testnet).
`paper_carry.py --loop --testnet` tanpa kunci env → berhenti dengan `RuntimeError`,
tidak ada order yang terkirim. Fail closed bekerja.

Koreksi terhadap kekhawatiran saya sendiri: restart daemon **tidak** mereset 30 hari
paper. `started` dipertahankan dari state lama (12,8 jam saat diperiksa). Bagian
"Keterbatasan" di handoff yang bilang "30 hari paper baru dihitung sejak daemon
di-restart" **tidak akurat untuk kode ini** — mungkin maksudnya hitungan mundur versi
lama. Sebaiknya diperbaiki supaya tidak menakut-nakuti tanpa alasan.

---

## 1. Plafon notional 20% tidak dipaksa di `paper_carry` — bertabrakan dengan ROADMAP #6

Ini temuan paling serius.

```
$ grep -c "batas_notional" paper_carry.py
0
$ python3 -c "import risk, paper_carry as pc; print(pc.MODAL_BUKU, pc.NOTIONAL, risk.batas_notional(pc.MODAL_BUKU))"
3000.0 1000.0 600.0
```

- `NOTIONAL = 1000.0`, `MAX_POS = 3`, `MODAL_BUKU = NOTIONAL * MAX_POS = 3000`.
- Plafon per posisi menurut `risk.batas_notional(MODAL_BUKU)` = **600**.
- Notional yang dicatat tiap posisi = **1000** → 167% dari plafon.
- 3 posisi penuh = **3000** = 100% modal, padahal aturannya "maks 20% modal per posisi".

`risk.batas_notional` hanya dipakai `plan_order.ukuran()`, dan `plan_order` **tidak
diimpor** `paper_carry`. Jadi batas 20% itu hidup di modul lain yang tidak ikut
membuka posisi.

`ROADMAP.md` syarat 6 menandai "batas notional ... dipaksa di kode" sebagai ✅.
Untuk `plan_order` benar. Untuk `paper_carry` — yang benar-benar membuka posisi —
tidak. Salah satu dari dua hal ini harus berubah: `MODAL_BUKU` diperbesar, atau
`NOTIONAL` dipotong ke plafon lewat `risk.batas_notional`. Saya tidak memilih sendiri
karena ini mengubah semua angka PnL yang sudah dilaporkan ke Naufal.

## 2. Notional paper 1000 vs order testnet 150 — 6,67×

```
$ grep -n "EXEC_NOTIONAL\|^NOTIONAL" paper_carry.py
42:EXEC_NOTIONAL = 150.0
50:NOTIONAL = 1000.0
```

PnL dollar dihitung dari `p["notional"]` = 1000 (baris 255, 315), sedangkan order
nyata di testnet 150. Artinya `slip_bps` di `execution_fills.csv` diukur pada posisi
6,67× lebih kecil dari posisi yang PnL-nya dilaporkan.

`HANDOFF-HERMES.md` bagian "Yang diukur" minta membandingkan slippage dengan asumsi
biaya 0,3%. Perbandingan itu tidak sah kalau skalanya beda — biaya tetap (fee minimum,
tick size) akan tampak jauh lebih besar secara persentase di posisi 150.

Pilih satu: `EXEC_NOTIONAL` dinaikkan mendekati `NOTIONAL`, atau PnL testnet dihitung
ulang per dollar notional nyata. Sebutkan mana yang dipakai di handoff.

## 3. `equity` di state tidak pernah di-update — field tidur yang menyesatkan

```
$ grep -n "equity" paper_carry.py
111:        return {"positions": {}, "closed": [], "equity": NOTIONAL, "started": time.time()}
$ grep -n 'st\["equity"\]' paper_carry.py
(nol)
```

Di-set sekali saat state baru, tidak pernah dibaca, tidak pernah ditulis lagi. Selama
ini tidak berbahaya karena kill switch memakai `risk.cek_drawdown(MODAL_BUKU, d1, d7, d30)`,
bukan `equity`. Tapi siapa pun yang menulis kode baru dan melihat `equity: 1000.0`
akan mengira itu ekuitas berjalan. Saat PnL terbuka −6,26, `equity` tetap 1000.0.

Saran: hapus field, atau isi dengan `MODAL_BUKU + pnl_total`. Jangan biarkan angka
yang terlihat resmi tapi tidak pernah bergerak.

## 4. `risk.cek_kill_switch()` yatim — dua fungsi mengukur hal yang sama

```
$ grep -rn "cek_kill_switch(" --include="*.py" . | grep -v "def cek_kill_switch"
risk.py:208,209,210      # hanya selftest-nya sendiri
```

Produksi memakai `cek_drawdown`. Jadi ada dua cara menghitung rugi: satu dari rasio
`equity_sekarang/equity_awal`, satu dari PnL kumulatif per jendela. Yang kedua yang
dipakai. Yang pertama lulus selftest dan terlihat siap pakai, jadi kandidat kuat
untuk dipakai keliru di kemudian hari. Hapus, atau jadikan pembungkus tipis
`cek_drawdown` supaya cuma ada satu rumus.

## 5. `paper_carry_state.json` di-track git — `git pull --rebase` akan berkonflik

```
$ git ls-files | grep paper_carry_state.json
paper_carry_state.json
```

State runtime berubah tiap tick (tiap 4 jam). Selama working tree-nya kotor,
`git pull --rebase origin main` — langkah 1 di handoff — akan berhenti minta stash.
Ini sudah pernah terjadi di sesi sebelumnya: push ditolak karena daemon commit duluan,
harus merge.

`.gitignore` sudah memuat `watchdog_state.json`, tapi tidak file state utama.
Saran: keluarkan `paper_carry_state.json` dari git (`git rm --cached`), simpan sebagai
artefak runtime saja. Kalau tujuannya supaya Naufal bisa melihat angka, `web/paper.json`
sudah ada untuk itu dan memang itu yang dibaca dashboard.

Catatan: kalau dikeluarkan, riwayat PnL 12 jam terakhir hilang dari git. Salin dulu
ke `hasil/` kalau mau disimpan sebagai bukti.

## 6. `execution_fills.csv` tidak ada di `.gitignore`

```
$ grep -n "fills" .gitignore
(tidak ada)
```

Handoff minta isi file itu ditempel ke bagian "Hasil smoke test". Kalau niatnya
di-commit sebagai bukti, tidak masalah — tapi tulis begitu. Kalau tidak, tiap smoke
test mengotori working tree, dan itu memperparah masalah 5.

## 7. `--testnet` tanpa kunci → traceback, bukan pesan satu baris

```
$ python3 paper_carry.py --loop --testnet
  File "paper_carry.py", line 577, in <module>
    EXCHANGE = binance_testnet.BinanceTestnet()
RuntimeError: isi BINANCE_TESTNET_KEY dan BINANCE_TESTNET_SECRET (kunci testnet)
```

Perilakunya benar (fail closed, nol order). Tapi Naufal bukan programmer: pesan
`RuntimeError` dengan 5 baris jejak file lebih buruk daripada satu baris
"kunci testnet belum diisi, lihat HANDOFF-HERMES.md langkah 5". Tangkap di `main()`.

---

## Yang saya tambahkan di repo (bukan temuan, tapi mengubah perilaku)

- `watchdog.py --loop` — periksa tiap 30 menit tanpa cron. Handoff menyarankan cron;
  cron bukan wewenang asisten ini, jadi loop setara di dalam proses.
- `start_all.sh` — nyalakan 3 daemon (`paper_carry`, `scan_and_push`, `watchdog`),
  lewati yang sudah hidup. Sebelumnya ketiganya dinyalakan manual: reboot = semua mati
  tanpa jejak.

Keduanya commit `4465b8b`. Tidak menyentuh logika trading, risiko, atau eksekusi.

## Telaah tambalan `6a99286` — 5 dari 7 beres, 3 celah baru

Claude menambal temuan 1–5 di commit `6a99286`. Diverifikasi, bukan dipercaya dari
commit message:

| Temuan | Status | Bukti |
|---|---|---|
| 1. Plafon 20% | ✅ beres | `NOTIONAL = risk.batas_notional(MODAL_BUKU)` = 600; 3 posisi = 60% modal |
| 2. Skala paper vs testnet | ✅ beres | `EXEC_NOTIONAL = NOTIONAL` |
| 3. `equity` field tidur | ⚠️ separuh | dihapus dari kode, **masih ada di `paper_carry_state.json`** |
| 4. `cek_kill_switch` yatim | ✅ beres | `grep` nol match |
| 5. state di-track git | ❌ **belum** | `git ls-files` masih memuat `paper_carry_state.json` |
| 6. `execution_fills.csv` | ✅ beres | masuk `.gitignore` |
| 7. traceback tanpa kunci | ✅ beres | sekarang satu pesan + petunjuk |

### Celah A — posisi terbuka masih di atas plafon, PnL dilaporkan 40% terlalu besar

```
$ python3 -c "import json; s=json.load(open('paper_carry_state.json'))
  [print(k, v['notional'], v['net']) for k,v in s['positions'].items()]"
ZECUSDT 1000.0 -0.00293
QNTUSDT 1000.0 -0.00301
```

Dua posisi dibuka **sebelum** plafon dipaksa, jadi `notional`-nya masih 1000.
`total_pnl()` memakai `p["notional"]` per posisi (bukan `NOTIONAL` global), jadi
angka yang dilaporkan masih dihitung dari 1000:

```
pakai notional tercatat (1000): -5.93 USD
pakai plafon baru (600)       : -3.56 USD
selisih                       : -2.37 USD (40% lebih kecil)
```

Ini bukan bug kode baru — kodenya konsisten (notional posisi disimpan saat masuk).
Tapi **dashboard publik sekarang menampilkan PnL dari modal yang tidak sesuai
aturan yang baru dipaksakan**. Pembaca akan mengira risiko per posisi 600 padahal
dua posisi berjalan di 1000.

Pilih satu: (a) biarkan posisi lama sampai tutup sendiri, tapi tulis di dashboard
bahwa 2 posisi pertama dibuka dengan plafon lama; (b) tutup paksa dua posisi itu
dan mulai bersih di notional 600; (c) reset state. (a) paling jujur secara data,
(c) paling bersih tapi menghapus riwayat.

### Celah B — `equity` masih tertinggal di state runtime

`load()` tidak membuang key asing (`st.setdefault(...)` saja). Jadi
`paper_carry_state.json` masih memuat `"equity": 1000.0` yang tidak pernah dibaca
siapa pun. Tidak berbahaya, tapi itu persis field tidur yang temuan 3 minta dihapus —
kalau nanti ada yang membacanya, angkanya salah (1000, bukan 3000 modal buku).

### Celah C — tidak ada penjaga di titik masuk

`assert` di baris 56 menjaga `NOTIONAL` terhadap plafon **saat modul dimuat**, tapi
tidak ada pemeriksaan saat posisi dibuka. Kalau `MODAL_BUKU` dinaikkan nanti tanpa
menyentuh `NOTIONAL`, atau ada posisi lama dengan notional lain, tidak ada yang
berteriak. Penjaga runtime sebelum `st["positions"][sym] = {...}` akan menutup itu.

### Temuan 8 — kunci spot dan futures TIDAK bisa satu pasang (sudah ditambal di adapter)

`binance_testnet.py` lama memakai satu `self.key`/`self.secret` untuk host spot DAN
futures. Binance memisah dua testnet itu. Bukti dari percobaan nyata:

```
python3 binance_testnet.py --smoke BTCUSDT     (hanya kunci spot terisi)
KAKI FUTURES DITOLAK (kode -2015): Invalid API-key, IP, or permissions for action
```

Tidak ada order menggantung karena `setup()` futures jalan sebelum order spot —
perilakunya benar, tapi adapter tidak bisa jalan sama sekali tanpa dua pasang kunci.
Sudah saya tambal: `BINANCE_TESTNET_SPOT_KEY/SECRET` + `BINANCE_TESTNET_FUT_KEY/SECRET`,
dipilih per host, dengan tes yang mengunci sifat itu. Commit `30b26be`.

## Smoke test dua kaki: BERSIH — dan 3 bug yang hanya muncul di exchange sungguhan

Kunci "Demo Trading API" sampai, smoke dua kaki lulus:

```
FUT host: https://demo-fapi.binance.com
buka: {'status': 'ok', 'qty': 0.002, 'spot': (0.002, 59050.74), 'perp': (0.002, 59025.9)}
tutup: {'status': 'ok'}
PERP amt 0.0000 | SPOT BTC 1.00000000 | FUT wallet 4999.55857
```

Empat selftest lulus. Nol posisi menggantung, nol halt. Commit `53a446a`.
Keluaran penuh ada di `HANDOFF-HERMES.md` Percobaan 3–4.

### Bug 9 — kunci "Demo Trading API" ≠ kunci testnet lama

```
testnet.binancefuture.com/fapi/v2/account       -> -2015 Invalid API-key
demo-fapi.binance.com/fapi/v2/account           -> OK, canTrade=True, wallet 5000
```

Binance punya dua testnet futures terpisah. Kunci yang dibuat lewat menu **Demo
Trading API** hanya berlaku di host demo. `FUT` dipindah ke `demo-fapi.binance.com`,
bisa ditimpa lewat env `BINANCE_TESTNET_FUT_HOST` supaya tidak perlu ubah kode untuk
berpindah.

### Bug 10 — futures tidak mengirim `avgPrice`, dan itu meninggalkan posisi menggantung

`_hasil()` lama:

```python
harga = float(js["cummulativeQuoteQty"]) / q if pasar == "spot" else float(js["avgPrice"])
```

Dokumentasi Binance bilang `newOrderRespType=RESULT` memberi `avgPrice` untuk futures.
Kenyataan di host demo: **tidak ada `avgPrice` sama sekali**. Respons mentah hanya
punya `price` (harga limit), `executedQty`, `cumQty`. Jadi `KeyError` dilempar
**setelah order FILLED**.

Akibat nyata, bukan teoretis: smoke pertama membuka spot beli (terisi) lalu perp short
(terisi), lalu `KeyError` membuat fungsi berhenti sebelum menutup apa pun. Posisi
short 0,002 BTC menggantung di akun. Yang menemukan bukan respons order, tapi query
`/fapi/v2/positionRisk`.

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

**Aturan yang harus dipegang di `execution.py`:** respons order tidak pernah boleh
dipakai sebagai bukti posisi. Setiap jalur yang membuka kaki harus bisa ditutup tanpa
bergantung pada parsing respons. Pertimbangkan `positionRisk`/`openOrders` sebagai
sumber kebenaran saat rekonsiliasi.

### Bug 11 — `slip_bps` kaki perp diukur terhadap harga spot

`smoke()` lama memanggil `buka_carry(..., ref, ref, tid)` — referensi spot dipakai untuk
kedua kaki. Hasilnya di CSV:

```
perp,sell,ref 59166.67 fill 59137.30 slip +4.96
perp,buy, ref 59166.67 fill 59305.40 slip +23.45
```

Itu **bukan slippage**, itu basis spot-perp yang tercampur. Setelah referensi perp
diambil dari `fapi/v1/ticker/bookTicker`, angkanya masuk akal:

```
perp,sell,ref 59085.00 fill 59025.90 slip +10.00
perp,buy, ref 59122.00 fill 59181.20 slip +10.01
```

+10,00 bps = tepat `TOL_BPS`. Order limit IOC menyilang sebesar toleransi, jadi ini
angka yang benar untuk buku demo — tetap **bukan** perkiraan biaya pasar asli.
Jangan dipakai mengisi asumsi 0,3%.

## Yang belum saya kerjakan dan menunggu Naufal

- Keputusan celah A (2 posisi lama di notional 1000 vs plafon 600). PnL yang tampil di
  dashboard 40% lebih besar dari yang seharusnya menurut aturan baru.
- Menyalakan `paper_carry.py --loop --testnet`. Order demo nyata 600/posisi, maks 3.
  Saya tidak menyalakannya tanpa izin Naufal, dan sebaiknya setelah celah A beres.
