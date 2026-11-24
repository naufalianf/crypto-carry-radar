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
KILL_SWITCH_HARIAN_PCT = 3.0  # rugi harian >= 3% -> tutup semua posisi, berhenti sampai direset manual
DELTA_TOLERANSI_PCT = 5.0     # ketidakseimbangan dua kaki yang masih diterima
BASIS_STOP_PCT = 0.5          # basis bergerak > 0.5% melawan -> keluar (di luar model biaya)


def batas_notional(modal, max_pct=MAX_NOTIONAL_PCT):
    """Plafon notional satu posisi dari modal."""
    return modal * max_pct / 100.0


def cek_kill_switch(equity_awal, equity_sekarang, batas_pct=KILL_SWITCH_HARIAN_PCT):
    """(terpicu, rugi_pct). Terpicu kalau rugi harian >= batas."""
    rugi = (equity_sekarang / equity_awal - 1) * 100 if equity_awal > 0 else 0.0
    return rugi <= -batas_pct, rugi


def cek_delta(notional_spot, notional_perp, toleransi_pct=DELTA_TOLERANSI_PCT):
    """(bocor, selisih_pct). Bocor kalau dua kaki tidak seimbang di luar toleransi."""
    if notional_spot <= 0:
        return True, 100.0
    selisih = abs(notional_spot - notional_perp) / notional_spot * 100
    return selisih > toleransi_pct, selisih


def cek_basis(basis_pct, batas_pct=BASIS_STOP_PCT):
    """(keluar, alasan). Basis = perp/spot - 1, dalam persen.
    Basis positif besar = perp mahal (menguntungkan short perp).
    Basis negatif besar = perp murah -> short perp rugi harga tanpa kompensasi funding."""
    if basis_pct <= -batas_pct:
        return True, f"basis {basis_pct:.3f}% melawan (batas -{batas_pct}%)"
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
    assert cek_kill_switch(1000, 970)[0] is True, "rugi 3% harus memicu"
    assert cek_kill_switch(1000, 971)[0] is False, "rugi 2.9% tidak boleh memicu"
    assert abs(cek_kill_switch(1000, 970)[1] + 3.0) < 1e-9, "hitung rugi salah"
    assert cek_delta(1000, 1030)[0] is False, "selisih 3% masih diterima"
    assert cek_delta(1000, 1060)[0] is True, "selisih 6% harus bocor"
    assert cek_basis(-0.6)[0] is True, "basis -0.6% harus keluar"
    assert cek_basis(+1.0)[0] is False, "basis positif menguntungkan, jangan keluar"
    # risiko 1% modal, stop 2% -> 500 diminta, dipotong plafon 200
    assert abs(sizing_dari_risiko(1000, 1.0, 2.0) - 200.0) < 1e-9, "potong plafon gagal"
    # risiko 1% modal, stop 10% -> 100 diminta, di bawah plafon
    assert abs(sizing_dari_risiko(1000, 1.0, 10.0) - 100.0) < 1e-9, "sizing dasar salah"
    print(f"selfcheck OK (plafon {MAX_NOTIONAL_PCT:.0f}%, kill switch {KILL_SWITCH_HARIAN_PCT:.0f}%, "
          f"delta {DELTA_TOLERANSI_PCT:.0f}%, basis stop {BASIS_STOP_PCT}%)")


if __name__ == "__main__":
    selfcheck()
