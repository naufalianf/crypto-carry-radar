# Audit: pengaman `day-trader-skill` vs pengaman kita

**Tanggal:** 2026-11-27 · **Repo:** `naufalianf/crypto-carry-radar` · **Untuk:** Claude

## 0. Apa dokumen ini

Ian mengirim `PANDUAN-SKILL-TRADING-CLAUDE.pdf` (5 halaman, oleh @hary.belajarai). Isinya
**panduan install** untuk repo `Jakeschincariol/day-trader-skill` — repo yang sudah ditelaah
kodenya di sesi sebelumnya dan ditolak (domain saham US, bukan bot carry).

Nilai dokumen ini bukan pada isinya, tapi pada **daftar pengaman** yang mereka pakai. Itu
memberi kesempatan audit setara. Hasil audit di bawah.

## 1. Konfigurasi pengaman mereka

```json
{
  "paper": true,
  "budget": 5000,
  "max_loss_per_trade_usd": 50,
  "max_daily_loss_usd": 150,
  "max_trades_per_day": 3,
  "no_entries_before": "09:45", "flat_by": "15:55",
  "pdt_guard": false
}
```

## 2. Audit setara: apa yang kita punya

Diambil langsung dari `risk.py` (grep konstanta, bukan asumsi):

```
MAX_NOTIONAL_PCT        = 20.0    maks 20% modal per posisi        ~ max_loss_per_trade_usd
MAX_LEVERAGE            = 1.0     leverage dikunci 1x              (mereka tak punya)
MAX_POSISI              = 3       maks 3 posisi bersamaan          (mereka tak punya)
KILL_SWITCH_HARIAN_PCT  = 1.0     rugi 24 jam >= 1% -> tutup semua ~ max_daily_loss_usd
KILL_SWITCH_MINGGUAN_PCT= 2.0     rugi 7 hari >= 2% -> berhenti    (mereka tak punya)
KILL_SWITCH_BULANAN_PCT = 3.0     rugi 30 hari >= 3% -> berhenti   (mereka tak punya)
COOLDOWN_RUGI_BERUNTUN  = 2       n rugi beruntun -> jeda 24 jam   (mereka tak punya)
SIMBOL_COOLDOWN_JAM     = 24      simbol keluar tak boleh masuk 24 jam
MAX_ENTRY_PER_TICK      = 2       rate limiter per siklus          ~ max_trades_per_day
SNAPSHOT_MAX_JAM        = 6.0     radar basi -> fail closed        (mereka tak punya)
DELTA_TOLERANSI_PCT     = 5.0     dua kaki tak seimbang > 5%        (mereka tak punya)
BASIS_STOP_PCT          = 0.5     basis lawan 0.5% -> keluar
NET_STOP_PCT            = 1.0     rugi bersih >= 1% -> keluar
FUNDING_STOP_PCT        = 0.15    funding <= -0.15% -> tesis gugur
MMR_ASUMSI_PCT          = 0.5     maintenance margin diasumsikan
LIKUIDASI_WASPADA_BAHAYA_DARURAT  40% / 20% / 10% jarak ke likuidasi
```

Kesimpulan audit: **kita lebih ketat di 9 dari 10 sumbu**. Satu-satunya yang mereka punya dan
kita tidak sebut namanya adalah `max_trades_per_day`. Tapi kita punya `MAX_ENTRY_PER_TICK = 2`
plus `SIMBOL_COOLDOWN_JAM = 24` — untuk strategi carry yang membuka 3 posisi sekali lalu
menahan 60 hari, frekuensi transaksi bukan vektor risiko. Menambah batas trade/hari di sini
adalah menambah kode untuk masalah yang tidak ada.

`no_entries_before` / `flat_by` / `pdt_guard` **tidak berlaku**: itu aturan jam bursa saham
NYSE (09:30–16:00 ET) dan aturan pattern-day-trader FINRA untuk akun < $25.000. Crypto 24/7,
tanpa jam tutup, tanpa PDT.

## 3. Dua catatan tentang dokumen itu sendiri

1. **Kontradiksi kecil**: halaman 1 memasarkan "TANPA API KEY", tapi halaman 4 mewajibkan
   `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` untuk broker, dan `sec_user_agent` (nama + email)
   untuk tool berita. Yang benar: **tanpa API key untuk data harga**, perlu kunci untuk order.
2. **Provenance**: repo Jake berlisensi MIT, jadi redistribusi oleh pihak ketiga sah. Tapi
   panduannya bukan sumber primer — kode aslinya sudah dibaca langsung di sesi sebelumnya,
   dan kesimpulan dari kode tetap sama: tidak ada yang perlu diambil.

## 4. Satu poin yang mereka tulis dan kita patuhi

Halaman 5: *"Stop bisa kena jauh dari harganya pas pasar gerak cepat atau harga loncat (gap)."*

Ini benar dan berlaku untuk kita juga. Mitigasi kita bukan stop order di bursa, tapi
`NET_STOP_PCT` + tier likuidasi (40/20/10%) + `_jaga()` yang menutup semua pada error apa pun.
Tidak perlu perubahan.

## 5. Keputusan

**Tidak ada kode yang diambil. Tidak ada fitur yang ditambah.** Audit ini menghasilkan nol
perubahan sistem, dan itu hasil yang benar — bukan kegagalan. Nilainya: kalau Claude atau
sumber lain nanti mengusulkan "kita butuh max_trades_per_day" atau "kita butuh guard jam
pasar", dokumen ini menjawab sekali dan tidak perlu diperdebatkan ulang.

Yang perlu ditanyakan ke depan saat ada skill/repo baru masuk: **sumbu risiko mana yang belum
kita kunci?** Kalau jawabannya kosong, tolak.