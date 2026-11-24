# Panduan Sistem Crypto — Versi Bahasa Bayi

**Untuk:** Bro Ian
**Tanggal:** 24 November 2026
**Status sistem:** masih tahap uji. **Belum ada satu order nyata pun.**

---

## Bagian 1 — Kita ini sedang bikin apa, sih?

Bayangkan **toko penukaran uang** di mall.

Toko itu tidak menebak arah harga. Dia cuma mengambil untung dari **selisih harga
antara dua meja** yang menjual barang yang sama. Kalau meja A jual lebih murah
daripada meja B, dia beli di A, jual di B, kantong selisihnya. Harga naik atau
turun tidak peduli — yang penting selisihnya tetap ada.

Nah, di crypto ada dua "meja" untuk koin yang sama:

- **Meja spot** — tempat beli koin beneran. Barang masuk ke tangan.
- **Meja perpetual** — tempat bertaruh harga naik/turun, tanpa barang. Cuma
  kontrak. Ini yang disebut "futures".

Di meja perpetual ada biaya unik namanya **funding**. Setiap 8 jam, orang yang
bertaruh harga naik membayar orang yang bertaruh harga turun (atau sebaliknya,
tergantung pasar).

Jadi triknya:

1. Beli 1 koin di meja spot (uang keluar).
2. Bertaruh "harga turun" di meja perpetual untuk 1 koin yang sama (uang masuk).
3. Harga naik? Spot untung, taruhan rugi. Harga turun? Spot rugi, taruhan untung.
   **Saling menutup.** Itu sebabnya disebut **delta-netral** — arah harga jadi
   tidak berpengaruh.
4. Yang kita kumpulkan tinggal **funding** tiap 8 jam itu.

Ibaratnya: kita jadi **pemilik warung parkir**, bukan penebak arah mobil. Mobil
mau ke utara atau selatan, kita tetap dapat koin parkir.

**Ini yang kita bangun.** Bukan mesin penebak harga. Mesin penagih sewa.

---

## Bagian 2 — Sekarang sistemnya bisa apa?

Ada 8 bagian. Anggap ini 8 orang pegawai warung.

### 1. `bot.py` — Tukang hitung di belakang
Menghitung ulang ribuan kemungkinan strategi pakai data harga lama. Gunanya
untuk **membuktikan atau membantah** ide sebelum uang dipakai.

**Hasilnya justru mengecewakan** — dan itu bagus, karena lebih murah kecewa di
hitung-hitungan daripada kecewa di dompet. (Cerita lengkapnya di Bagian 3.)

### 2. `runner.py` — Pegawai latihan (paper spot)
Menjalankan strategi beli-jual pakai **uang bohongan** $1.000 per buku. Tidak
menyentuh uang asli. Sekarang ada 4 buku jalan, hasilnya campur: tiga rugi
kecil, satu untung 6,3%.

### 3. `radar.py` — Petugas ronda
Setiap 4 jam dia keliling ke **701 pasar perpetual** di Binance, lalu mencatat:

- berapa funding-nya sekarang,
- kalau di-setahunkan jadi berapa persen (APR),
- umur koin (koin baru sering liar),
- lebar spread (makin lebar makin mahal masuk-keluar),
- volume dagang (cukup ramai atau tidak).

Dia juga mengecek **satu hal yang paling sering dilupakan orang: apakah koin itu
punya pasar spot?** Kalau tidak ada spot, strategi kita mustahil dijalankan.
Titik. Tidak ada barang untuk dibeli.

### 4. Gate — Satpam
Dari 701 koin, satpam menyaring pakai 5 aturan. Koin baru boleh masuk daftar
"layak" kalau **semua** aturan lolos:

| Aturan | Batas | Kenapa |
|---|---|---|
| Punya pasar spot | wajib | tanpa ini mustahil |
| Umur listing | ≥ 30 hari | koin baru = funding liar |
| Spread | ≤ 15 bps | mahal masuk-keluar |
| Volume 24 jam | ≥ $50 juta | kalau mau keluar, harus ada pembeli |
| Balik modal | > 3 hari | APR tidak masuk akal |

### 5. `carry.py` — Tukang audit masa lalu
Menghitung: kalau strategi ini sudah dijalankan 3 tahun terakhir, hasilnya
berapa? Ini yang memberi angka APR realistis, bukan angka brosur.

### 6. `paper_carry.py` — Pegawai latihan (paper carry)
Menjalankan strategi carry pakai **uang bohongan** $1.000 per posisi. Mencatat
funding yang benar-benar masuk tiap 8 jam. Ini **bukti akuntansi** — kalau nanti
pakai uang asli, angkanya harus cocok dengan catatan ini.

### 7. `plan_order.py` — Notaris
Kalau ada peluang, dia menyusun **rencana order tertulis**: beli berapa, di
harga berapa, biayanya berapa, kapan balik modal, kapan harus keluar. Ukuran
posisinya dihitung dari **kedalaman orderbook nyata**, bukan ditebak.

Dia **tidak mengirim order.** Dia cuma menulis di kertas.

### 8. Dashboard — Papan pengumuman
Halaman web yang bisa dibuka dari HP. Isinya tabel semua koin yang dipantau,
lengkap dengan status "lolos gate" atau "gagal karena apa". Sekarang sudah
online di Vercel.

---

## Bagian 3 — Apa yang SUDAH tercapai

Ini yang benar-benar sudah jadi dan sudah diuji, bukan rencana.

### ✅ Tiga ide besar sudah diuji, dan dua di antaranya gugur

Ini bagian terpenting. Kita **tidak** langsung percaya ide bagus. Kita uji dulu.

**Ide 1 — Ikut tren pakai indikator (SMA / mean-reversion).**
Diuji 80 variasi strategi, diuji ulang di 23 periode berbeda.

Hasil: **gugur.** Dari 80 strategi, cuma 5 yang untung. Dan yang untung di
periode lama, belum tentu untung di periode berikutnya — parameternya berganti
**13 kali**. Artinya: itu bukan ilmu, itu kebetulan.

**Ide 2 — Ikut tren jangka panjang (TSMOM), 10 koin.**
Awalnya terlihat hebat: +287%. Lalu saya temukan **bug**: strategi itu diam-diam
"mengintip" harga yang belum terjadi. Sesuatu yang mustahil di dunia nyata.

Setelah bug diperbaiki: **+182%** dalam 5 tahun. Sementara cuma **beli BTC lalu
diam** hasilnya **+268%**.

Jadi: lebih ribet, lebih banyak biaya, hasilnya lebih kecil. **Gugur** sebagai
mesin profit. Yang tersisa cuma gunanya sebagai penahan rugi saat pasar jatuh.

> Ini contoh kenapa saya tidak mau menjanjikan apa-apa. Angka +287% itu terlihat
> seperti jackpot. Ternyata bohong, dan bohongnya ketemu karena diuji ulang.

**Ide 3 — Carry funding (yang sekarang kita pakai).**
Diuji 3 tahun data: **+24% total, setara 7,44% per tahun.** Risiko jatuh sangat
kecil (maks -0,43%).

Tapi ada catatan jujur: **makin lama makin kecil.** Tahun pertama 7,44%, tahun
terakhir tinggal **3,18%**. Pasar makin ramai, sewa parkir makin murah.

### ✅ Radar sudah jalan dan memindai pasar nyata

60 koin teratas dipindai dalam **2 detik**. Bisa juga 701 koin.

Dan hasil pemindaiannya menemukan sesuatu yang **tidak terlihat dari luar**:

> 10 koin dengan APR tertinggi — BULLAUSDT 63%, EVAAUSDT 30%, ELSAUSDT 25% —
> **semuanya tidak punya pasar spot.**

Artinya: angka 63% itu umpan. Tidak ada barang untuk dibeli. Orang yang tergiur
angka itu akan masuk lewat jalur yang salah dan rugi.

Yang punya spot dan APR masuk akal cuma: **ZEC 5,45%** dan **QNT 4,72%**.

### ✅ Sistem sudah bisa menyusun rencana order yang bisa diperiksa

Kalau ada peluang, sistem mengeluarkan kertas berisi: beli berapa koin, di harga
berapa, biaya berapa, balik modal berapa hari, kapan keluar. Semua angka bisa
Bro cek sendiri. Tidak ada yang disembunyikan.

### ✅ Batas risiko dipaksa di dalam kode, bukan cuma ditulis di dokumen

Ini bedanya "janji" dan "pagar beton":

- Maksimal **20% modal** per posisi
- Maksimal **3 posisi** terbuka
- Leverage maksimal **1x** (tidak ada utang)
- Rugi harian **3%** → sistem berhenti sendiri hari itu
- Basis bergeser **0,5%** → posisi ditutup otomatis

Kalau Bro menulis "jangan lebih dari 20%" di dokumen, tidak ada yang menjamin.
Kalau ditulis di kode, sistemnya **menolak** perintah yang melanggar.

### ✅ Dashboard online dan tidak bisa mati

Sudah di Vercel. Tidak butuh server sendiri, tidak butuh tunnel, tidak bisa kena
blokir ISP. Datanya dari mesin sini, dikirim ke GitHub, dibaca dashboard.

### ✅ Belum pernah menyentuh uang asli

Tidak ada API key terpasang. Tidak ada akses saldo. Semua angka di sistem ini
**uang bohongan**.

---

## Bagian 4 — Apa yang BELUM tercapai

Saya tulis apa adanya, karena ini yang Bro bayar mahal kalau disembunyikan.

### ❌ 1. Bot tidak menghasilkan uang. Belum pernah. Nol.

Belum ada satu rupiah pun masuk. Yang ada: catatan bahwa strategi ini **layak
diuji lebih lanjut**, bukan bahwa strategi ini menguntungkan.

### ❌ 2. Gate-nya sekarang menyaring terlalu ketat — hasilnya nol

Hari ini, dari 60 koin: **0 yang lolos.**

Bukan karena sistem rusak. Memang **tidak ada yang layak** hari ini. Tapi artinya
juga: kalau Bro menunggu bot ini "kasih sinyal beli", Bro akan menunggu lama.

### ❌ 3. Paper carry baru jalan 7 jam, syaratnya 30 hari

Target: 30 hari penuh tanpa celah, dengan minimal 3 posisi ditutup lengkap.

Sekarang: **7 jam**, 2 posisi masih terbuka, hasil sementara **-0,29%** (itu
biaya masuk, belum sempat dapat funding).

Dari **9 syarat** untuk naik ke tahap berikutnya, **nol** yang lulus penuh.

### ❌ 4. Belum ada tombol "setujui" di Telegram

Rencananya: bot menyiapkan order, Bro tekan satu tombol, order dikirim. Sekarang
yang ada baru rencana tertulis di layar. Tombolnya belum dibuat.

### ❌ 5. Satu lubang yang baru ditemukan, belum ditambal

Sistem memantau **selisih harga** antara spot dan perpetual — kalau selisihnya
melebar, posisi ditutup.

Tapi ada yang tidak dipantau: **kalau funding berbalik negatif terus-menerus.**
Kita jadi yang **membayar**, bukan yang dibayar. Simulasi menunjukkan: funding
negatif -0,03% per hari selama 24 hari = rugi -0,72%, dan **sistem tidak akan
menutup posisi** karena selisih harga tidak berubah.

Ini bukan kebocoran fatal (masih ada batas 60 hari), tapi harus ditambal
sebelum uang asli masuk.

### ❌ 6. Binance belum berizin OJK

Binance global bukan pedagang aset kripto berlisensi OJK. Yang berizin ada 28,
salah satunya Tokocrypto.

Ini **keputusan risiko milik Bro**, bukan sesuatu yang bisa saya putuskan atau
sembunyikan. Saya pakai data harga publik Binance karena datanya terbuka, tapi
kalau nanti taruh uang, ini harus Bro timbang sendiri.

---

## Bagian 5 — Kenapa bot belum boleh kirim order sendiri

Karena ada 9 syarat, dan semuanya harus lulus. Bukan 8 dari 9. Bukan "hampir".

| # | Syarat | Status |
|---|---|---|
| 1 | Paper carry jalan ≥ 30 hari tanpa celah | ❌ baru 7 jam |
| 2 | Selisih catatan vs teori < 0,20% | ❌ belum bisa diuji |
| 3 | Minimal 3 posisi ditutup lengkap | ❌ nol |
| 4 | Slippage nyata ≤ 0,3% | ❌ belum ada order nyata |
| 5 | Paper spot cocok dengan backtest < 5% | ⚠️ sebagian |
| 6 | Dry-run, kill switch, batas rugi di kode | ✅ **lulus** |
| 7 | Rekonsiliasi dua kaki otomatis | ❌ belum ada |
| 8 | API key tanpa izin withdraw | ✅ siap (belum dipasang) |
| 9 | Limit order saja | ✅ aturan sudah ada |

**3 lulus, 1 separuh, 5 belum.** Jadi: tetap di tahap uji.

Kalau saya paksa buka sekarang, yang terjadi bukan "cepat kaya" — tapi
"cepat rugi tanpa tahu kenapa".

---

## Bagian 6 — Kamus istilah

Biar Bro tidak perlu tanya ulang tiap kali.

**Spot** — beli koin beneran. Barang masuk tangan.

**Perpetual (perp)** — kontrak bertaruh harga, tanpa barang. Bisa pakai utang
(leverage). Ini yang berbahaya.

**Funding** — biaya tiap 8 jam di perpetual. Kadang kita terima, kadang kita
bayar.

**APR** — kalau hasilnya diulang setahun penuh, jadi berapa persen. APR 7,44%
artinya: kalau konsisten setahun, untung 7,44%.

**Delta-netral** — dua posisi berlawanan yang saling menutup, jadi arah harga
tidak berpengaruh.

**Spread** — selisih harga beli dan harga jual. Makin lebar makin mahal.

**bps** — satuan kecil. 100 bps = 1%. 15 bps = 0,15%.

**Gate** — satpam penyaring. Koin harus lolos 5 aturan.

**Kapasitas** — berapa banyak uang yang bisa masuk tanpa menggeser harga.

**Slippage** — harga yang akhirnya didapat beda dari yang direncanakan.

**Paper trading** — latihan pakai uang bohongan.

**Max drawdown (MDD)** — rugi terdalam dari puncak ke lembah. -0,43% artinya
pernah turun paling parah 0,43%.

**Look-ahead bug** — kesalahan di mana program diam-diam memakai informasi masa
depan. Bikin hasil backtest terlihat bagus padahal mustahil.

---

## Bagian 7 — Jadi, apa keputusan yang ada di tangan Bro?

Ini bagian yang saya butuh Bro komentar. Pilih saja, tidak perlu teknis.

### Pertanyaan 1 — Kita lanjut atau berhenti?

Fakta yang perlu Bro tahu sebelum jawab:

- Carry funding **positif tapi kecil**, dan **menyusut** tiap tahun (7,44% → 3,18%).
- Untuk modal kecil, 3% setahun **kalah** dari deposito, dan ada risiko exchange.
- Tidak ada strategi lain yang lolos uji.

Pilihannya:

**(a)** Lanjut uji paper carry 30 hari. **Rp0 risiko**, tapi butuh sabar dan
hasilnya kemungkinan cuma "layak, tapi kecil".

**(b)** Berhenti di sini. Simpan ilmunya, jangan taruh uang. Ini pilihan yang
jujur dan tidak memalukan.

**(c)** Ganti arah: cari peluang lain yang lebih besar (bukan carry). Butuh
riset baru dari nol, hasil belum tentu ada.

### Pertanyaan 2 — Kalau lanjut, target hasilnya berapa?

Kalau Bro bilang "harus 20% setahun", saya harus bilang **tidak bisa dijanjikan**
dengan data yang ada. Yang realistis dari carry: **3-7% setahun**, dengan risiko
exchange.

### Pertanyaan 3 — Sumber data boleh tetap Binance?

Data harga publik Binance dipakai karena terbuka dan lengkap. Yang jadi
pertimbangan: Binance global tidak berizin OJK. Kalau Bro mau lebih aman secara
regulasi, kita bisa pindah ke data Tokocrypto — tapi pilihannya lebih sedikit
dan strateginya mungkin tidak bisa jalan.

### Pertanyaan 4 — Mau saya tambal lubang funding negatif dulu?

Ini pekerjaan kecil: tambah satu pemeriksaan "kalau total funding sudah minus
sekian persen, tutup posisi". Sekitar 15 menit. Sebaiknya dilakukan sebelum
lanjut, karena ini lubang nyata.

---

## Bagian 8 — Satu halaman ringkas

Kalau Bro cuma mau baca satu bagian, baca ini.

**Yang sudah jadi:**
- Radar pemindai 701 pasar, jalan tiap 4 jam
- Satpam 5 aturan yang menyaring koin sampah
- Hitungan APR realistis, bukan angka brosur
- Rencana order tertulis yang bisa diperiksa
- Pagar risiko di dalam kode (20% modal, 3 posisi, 1x, stop 3%/hari)
- Latihan carry pakai uang bohongan
- Dashboard online, tidak bisa mati

**Yang belum jadi:**
- Belum ada untung. Nol rupiah.
- Hari ini 0 dari 60 koin lolos gate
- Paper carry baru 7 jam dari 30 hari
- Belum ada tombol setujui di Telegram
- Ada lubang funding negatif yang belum ditambal
- Binance belum berizin OJK

**Kesimpulan jujur:**

Sistem ini sudah bisa **menjawab pertanyaan** dengan baik: "koin mana yang
peluangnya nyata, dan berapa untungnya setelah semua biaya?" Itu sudah terbukti —
dia berhasil membongkar bahwa 10 dari 10 APR tertinggi itu palsu.

Yang **belum** bisa: menghasilkan uang. Dan tidak ada jalan pintas untuk itu.
Yang bisa dilakukan cuma menguji dengan sabar, atau berhenti dengan jujur.

Dua-duanya pilihan yang benar. Yang salah cuma satu: taruh uang karena sudah
gemes.

---

*Dokumen ini ditulis 24 November 2026. Semua angka di dalamnya berasal dari hasil
pengujian yang tersimpan di folder `hasil/`, bisa diperiksa ulang kapan saja.*
