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

## Yang belum saya kerjakan dan menunggu Naufal

- Kunci testnet (`BINANCE_TESTNET_KEY`/`SECRET`). Belum ada. Tanpa itu smoke test
  mustahil, dan bagian "Hasil smoke test" sengaja saya biarkan kosong.
- Keputusan soal temuan 1 dan 2 (skala notional). Itu mengubah angka yang sudah
  dilaporkan, jadi bukan keputusan saya.
