#!/usr/bin/env python3
"""Batas risiko yang dipaksa di KODE, bukan cuma ditulis di dokumen.

Dipakai `plan_order.py` (batas ukuran posisi) dan `paper_carry.py` (kill switch harian).

Catatan desain penting — untuk carry delta-neutral TIDAK ada stop-loss harga:
posisi ini tidak punya eksposur arah, jadi stop harga cuma mengubah volatilitas
kecil menjadi biaya keluar-masuk berulang. Yang benar-benar mengancam carry:
  1. funding berbalik negatif (sudah dijaga EXIT_APR di paper_carry.py)
  2. basis melebar melawan (BASIS_STOP_PCT di sini)
  3. salah satu kaki tidak terisi -> eksposur arah bocor (DELTA_TOLERANSI_PCT)
  4. posisi terlalu lama menahan modal (MAX_DAYS di paper_carry.py)
Stop berbasis harga hanya masuk akal untuk strategi berarah, dan proyek ini
belum punya strategi berarah yang layak (lihat REVIEW.md).
"""

MAX_NOTIONAL_PCT = 20.0       # maks 20% modal per posisi
MAX_LEVERAGE = 1.0            # carry 1x; leverage >1 mempercepat likuidasi, bukan menambah edge
MAX_POSISI = 3
KILL_SWITCH_HARIAN_PCT = 1.0  # rugi 24 jam >= 1% modal buku -> tutup semua posisi, berhenti sampai direset manual
KILL_SWITCH_MINGGUAN_PCT = 2.0   # rugi 7 hari >= 2%
KILL_SWITCH_BULANAN_PCT = 3.0    # rugi 30 hari >= 3%
# Angka di atas dipilih supaya BISA tercapai: stop per posisi = -1% dari 1000 = $10 = 0,33% dari
# modal buku 3000, jadi batas lama 3% ($90) butuh 9 stop sekaligus dan praktis tak pernah terpicu.
COOLDOWN_RUGI_BERUNTUN = 2    # n posisi tertutup terakhir rugi semua -> berhenti buka posisi baru
COOLDOWN_JAM = 24             # ... selama sekian jam sejak penutupan terakhir
SIMBOL_COOLDOWN_JAM = 24      # simbol yang baru keluar tidak boleh masuk lagi sebelum ini (anti-churn di ambang APR)
MAX_ENTRY_PER_TICK = 2        # rate limiter: maks posisi baru per tick
SNAPSHOT_MAX_JAM = 6.0        # radar.json lebih tua dari ini -> jangan buka posisi baru (fail closed)
DELTA_TOLERANSI_PCT = 5.0     # ketidakseimbangan dua kaki yang masih diterima
BASIS_STOP_PCT = 0.5          # basis bergerak > 0.5% melawan -> keluar (di luar model biaya)
NET_STOP_PCT = 1.0            # backstop: rugi bersih kumulatif >= 1% -> keluar
FUNDING_STOP_PCT = 0.15       # funding kumulatif <= -0.15% -> tesis carry sudah salah


def cek_funding(funding_kum_pct, batas_pct=FUNDING_STOP_PCT):
    """(keluar, alasan). Funding yang TERAKUMULASI membayar, bukan menerima.

    Ini lubang yang tidak tertangkap `cek_basis`: basis hanya melihat selisih
    harga spot vs perp, sedangkan funding adalah aliran kas terpisah. Funding
    negatif -0,03%/hari selama 24 hari = -0,72% tanpa basis bergerak sedikit pun,
    jadi tidak ada pemicu apa pun. Ambang -0,15% setara ~5 hari berturut-turut
    membayar — cukup untuk menyimpulkan tesis carry tidak berlaku lagi.
    """
    if funding_kum_pct <= -batas_pct + 1e-9:
        return True, (f"funding kumulatif {funding_kum_pct:.3f}% (batas -{batas_pct}%) "
                      f"— kita yang membayar, bukan menerima")
    return False, ""


def cek_net(net_pct, batas_pct=NET_STOP_PCT):
    """(keluar, alasan). Backstop rugi kumulatif, BUKAN proksi basis/APR.

    `cek_basis` hanya melihat level basis relatif entry. Funding negatif kecil
    yang konsisten (-0,03%/hari) tidak menggeser basis sama sekali, jadi bisa
    menumpuk berminggu-minggu tanpa pernah memicu apa pun: 24 hari = -0,72%.
    Fungsi ini memeriksa angka yang sebenarnya — PnL bersih setelah biaya.
    """
    if net_pct <= -batas_pct + 1e-9:
        return True, (f"rugi bersih kumulatif {net_pct:.3f}% "
                      f"(batas -{batas_pct}%) — funding berbalik/biaya menumpuk")
    return False, ""


def batas_notional(modal, max_pct=MAX_NOTIONAL_PCT):
    """Plafon notional satu posisi dari modal."""
    return modal * max_pct / 100.0


def cek_kill_switch(equity_awal, equity_sekarang, batas_pct=KILL_SWITCH_HARIAN_PCT):
    """(terpicu, rugi_pct). Terpicu kalau rugi harian >= batas."""
    rugi = (equity_sekarang / equity_awal - 1) * 100 if equity_awal > 0 else 0.0
    return rugi <= -batas_pct, rugi


def cek_drawdown(modal, pnl_1d, pnl_7d, pnl_30d):
    """(level, rugi_pct, batas_pct). level None = aman; selain itu 'harian'/'mingguan'/'bulanan'.

    Input = perubahan PnL kumulatif (dalam mata uang, bukan persen) pada tiap jendela.
    Modal tidak valid -> terpicu (fail closed): tidak ada dasar untuk mengukur rugi.
    """
    if not modal or modal <= 0:
        return "modal tidak valid", 0.0, 0.0
    terburuk = 0.0
    for nama, pnl, batas in (("harian", pnl_1d, KILL_SWITCH_HARIAN_PCT),
                             ("mingguan", pnl_7d, KILL_SWITCH_MINGGUAN_PCT),
                             ("bulanan", pnl_30d, KILL_SWITCH_BULANAN_PCT)):
        if pnl is None:
            continue          # riwayat belum menutupi jendela ini — bukan berarti rugi 0
        rugi = pnl / modal * 100
        terburuk = min(terburuk, rugi)
        if rugi <= -batas + 1e-9:
            return nama, rugi, batas
    return None, terburuk, 0.0


def cek_cooldown(closed_net, ts_tutup_terakhir, sekarang,
                 n=COOLDOWN_RUGI_BERUNTUN, jam=COOLDOWN_JAM):
    """(blokir, alasan). closed_net = net posisi tertutup, urut kronologis (lama -> baru)."""
    if len(closed_net) < n or ts_tutup_terakhir is None:
        return False, ""
    if all(x < 0 for x in closed_net[-n:]) and sekarang - ts_tutup_terakhir < jam * 3600:
        sisa = jam - (sekarang - ts_tutup_terakhir) / 3600
        return True, f"{n} posisi tertutup terakhir rugi semua — jeda {sisa:.1f} jam lagi"
    return False, ""


def cek_cooldown_simbol(ts_tutup_simbol, sekarang, jam=SIMBOL_COOLDOWN_JAM):
    """(blokir, sisa_jam). ts_tutup_simbol None = belum pernah keluar."""
    if ts_tutup_simbol is None:
        return False, 0.0
    sisa = jam - (sekarang - ts_tutup_simbol) / 3600
    return sisa > 0, max(sisa, 0.0)


def cek_snapshot(umur_jam, maks_jam=SNAPSHOT_MAX_JAM):
    """(layak, alasan). umur_jam None = tidak terbaca -> tidak layak (fail closed)."""
    if umur_jam is None:
        return False, "radar.json tidak ada / tidak terbaca / tanpa generated_at"
    if umur_jam > maks_jam:
        return False, f"radar.json berumur {umur_jam:.1f} jam (batas {maks_jam:.0f} jam)"
    return True, ""


def cek_delta(notional_spot, notional_perp, toleransi_pct=DELTA_TOLERANSI_PCT):
    """(bocor, selisih_pct). Bocor kalau dua kaki tidak seimbang di luar toleransi."""
    if notional_spot <= 0:
        return True, 100.0
    selisih = abs(notional_spot - notional_perp) / notional_spot * 100
    return selisih > toleransi_pct, selisih


def cek_basis(basis_now_pct, basis_entry_pct, batas_pct=BASIS_STOP_PCT):
    """(keluar, alasan). Basis = perp/spot - 1, dalam persen.

    Posisi carry = long spot + short perp. PnL dari basis kira-kira MINUS
    perubahan basis: basis NAIK berarti perp jadi relatif lebih mahal,
    short perp rugi harga lebih besar daripada untung di spot.
    Jadi yang dipantau adalah PERUBAHAN basis dari basis entry, bukan
    apakah basis sekarang negatif. Basis negatif yang stabil tidak merugikan.
    """
    geser = basis_now_pct - basis_entry_pct
    # toleransi 1e-9: tanpa ini, geser tepat di ambang (0.5%) lolos karena
    # pembulatan float (0.5-0.4999999...), padahal PnL dua kaki sudah rugi penuh.
    if geser >= batas_pct - 1e-9:
        return True, (f"basis melebar {geser:+.3f}% melawan "
                      f"({basis_entry_pct:.3f}% -> {basis_now_pct:.3f}%, batas {batas_pct}%)")
    return False, ""


def sizing_dari_risiko(modal, risiko_pct, jarak_stop_pct, max_pct=MAX_NOTIONAL_PCT):
    """Ukuran posisi dari batas risiko, bukan dari 'mau beli berapa'.
    notional = (modal x risiko%) / jarak_stop% ; lalu dipotong plafon notional."""
    if jarak_stop_pct <= 0:
        raise ValueError("jarak stop harus > 0")
    n = modal * (risiko_pct / 100.0) / (jarak_stop_pct / 100.0)
    return min(n, batas_notional(modal, max_pct))


def selfcheck():
    assert batas_notional(1000) == 200.0, "plafon notional salah"
    assert cek_kill_switch(1000, 970, 3.0)[0] is True, "rugi 3% harus memicu"
    assert cek_kill_switch(1000, 971, 3.0)[0] is False, "rugi 2.9% tidak boleh memicu"
    assert abs(cek_kill_switch(1000, 970, 3.0)[1] + 3.0) < 1e-9, "hitung rugi salah"
    # kill switch berlapis (modal 3000): harian 1% = $30, mingguan 2% = $60, bulanan 3% = $90
    assert cek_drawdown(3000, -30, -30, -30)[0] == "harian"
    assert cek_drawdown(3000, -29, -29, -29)[0] is None
    assert cek_drawdown(3000, -10, -60, -60)[0] == "mingguan"
    assert cek_drawdown(3000, -10, -20, -90)[0] == "bulanan"
    assert cek_drawdown(3000, +50, +50, +50)[0] is None, "untung tidak boleh memicu"
    assert cek_drawdown(0, 0, 0, 0)[0] is not None, "modal 0 harus fail closed"
    # cooldown: dua rugi beruntun -> blokir 24 jam, lalu lepas
    assert cek_cooldown([+0.1, -0.2, -0.3], 1000, 1000 + 3600)[0] is True
    assert cek_cooldown([-0.2, +0.3], 1000, 1000 + 3600)[0] is False, "rugi tidak beruntun"
    assert cek_cooldown([-0.2, -0.3], 1000, 1000 + 25 * 3600)[0] is False, "jeda sudah lewat"
    assert cek_cooldown([-0.2], 1000, 1001)[0] is False, "baru satu rugi"
    assert cek_cooldown_simbol(1000, 1000 + 3600)[0] is True
    assert cek_cooldown_simbol(1000, 1000 + 25 * 3600)[0] is False
    assert cek_cooldown_simbol(None, 1000)[0] is False
    assert cek_snapshot(1.0)[0] is True and cek_snapshot(7.0)[0] is False
    assert cek_snapshot(None)[0] is False, "snapshot tak terbaca harus fail closed"
    assert cek_delta(1000, 1030)[0] is False, "selisih 3% masih diterima"
    assert cek_delta(1000, 1060)[0] is True, "selisih 6% harus bocor"
    assert cek_basis(-0.6, -0.1)[0] is False, "basis negatif stabil tidak boleh keluar"
    assert cek_basis(+0.2, +0.1)[0] is False, "geser 0.1% masih di dalam batas"
    assert cek_basis(+0.7, +0.1)[0] is True, "basis naik 0.6% harus keluar"
    # tepi: geser tepat di ambang harus memicu (bug float 0.5-0.4999...)
    assert cek_basis(+0.40, -0.10)[0] is True, "geser tepat 0.50% harus memicu"
    # arah tanda: basis turun menguntungkan short perp -> jangan keluar
    assert cek_basis(-0.9, -0.1)[0] is False, "basis turun menguntungkan, jangan keluar"
    # backstop rugi kumulatif (Temuan A): funding negatif menumpuk tanpa geser basis
    assert cek_net(-0.5)[0] is False, "rugi 0.5% masih di dalam batas"
    assert cek_net(-1.0)[0] is True, "rugi 1.0% harus keluar"
    assert cek_net(-1.5)[0] is True, "rugi 1.5% harus keluar"
    assert cek_net(+0.2)[0] is False, "posisi untung tidak boleh ditutup"
    # simulasi Temuan A: 24 hari funding -0.03%/hari, basis tidak bergerak
    basis_entry, basis_now = -0.10, -0.10
    net = -0.03 * 24
    assert cek_basis(basis_now, basis_entry)[0] is False, "basis statis tidak memicu apa pun"
    # -0.72% belum sampai backstop net 1%, jadi yang menangkap harus cek_funding
    assert cek_net(net)[0] is False, "net -0.72% masih di bawah backstop 1%"
    assert cek_funding(net)[0] is True, "funding -0.72% harus ditangkap cek_funding"
    assert cek_funding(-0.1)[0] is False, "funding -0.1% masih di dalam batas"
    assert cek_funding(-0.15)[0] is True, "funding tepat -0.15% harus keluar"
    assert cek_funding(+0.5)[0] is False, "funding positif tidak boleh memicu"
    # risiko 1% modal, stop 2% -> 500 diminta, dipotong plafon 200
    assert abs(sizing_dari_risiko(1000, 1.0, 2.0) - 200.0) < 1e-9, "potong plafon gagal"
    # risiko 1% modal, stop 10% -> 100 diminta, di bawah plafon
    assert abs(sizing_dari_risiko(1000, 1.0, 10.0) - 100.0) < 1e-9, "sizing dasar salah"
    print(f"selfcheck OK (plafon {MAX_NOTIONAL_PCT:.0f}%, kill switch {KILL_SWITCH_HARIAN_PCT:.0f}%, "
          f"delta {DELTA_TOLERANSI_PCT:.0f}%, basis stop {BASIS_STOP_PCT}%, "
          f"funding stop -{FUNDING_STOP_PCT}%, net stop -{NET_STOP_PCT}%)")


if __name__ == "__main__":
    selfcheck()
