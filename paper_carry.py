#!/usr/bin/env python3
"""Paper carry — simulasi eksekusi carry pakai data LIVE. Tidak ada uang, tidak ada API key.

Aturan (ditetapkan sebelum jalan, bukan hasil tuning):
- Kandidat: koin yang LOLOS gate di radar.json.
- Masuk: APR 7d >= ambang masuk (ENTRY_APR).
- Keluar: APR 7d < ambang keluar (EXIT_APR), umur > MAX_DAYS, basis melawan,
  funding kumulatif negatif, atau rugi bersih kumulatif (lihat risk.py).
- Posisi: long spot + short perp, nominal sama, 1x tanpa leverage. Nominal 1000/buku.
- Funding diakumulasi dari endpoint funding rate (dihitung per fundingTime, tidak dobel).
- Biaya masuk+keluar diambil dari radar (fee + spread kedua kaki).

Penjaga (semuanya di kode, lihat risk.py):
- Kill switch berlapis 1d/7d/30d dari kurva PnL kumulatif -> tutup semua + kunci sampai --reset-halt.
- Cooldown: 2 posisi tertutup terakhir rugi semua -> 24 jam tanpa posisi baru.
- Anti-churn: simbol yang baru keluar tidak boleh masuk lagi 24 jam; maks 2 posisi baru per tick.
- Fail closed: radar.json basi/hilang -> tidak buka posisi baru; state rusak -> berhenti (tidak dibuat ulang).
- Lock per tick: dua proses tidak menulis state bersamaan; simpan state atomik.

  python3 paper_carry.py --selftest      # jalankan test_paper_carry.py
  python3 paper_carry.py --tick
  python3 paper_carry.py --loop          # tiap 4 jam
  python3 paper_carry.py --status
  python3 paper_carry.py --reset-halt
  python3 paper_carry.py --loop --testnet   # order nyata ke Binance TESTNET (lihat HANDOFF-HERMES.md)
"""
import argparse
import calendar
import contextlib
import csv
import json
import os
import sys
import time

from radar import FAPI, get
import execution
import risk

# Eksekusi nyata (opt-in, hanya testnet): None = paper murni. Diisi oleh `--testnet`.
EXCHANGE = None
EXEC_NOTIONAL = 150.0      # nominal order testnet per posisi (minimum order exchange ~100)

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "paper_carry_state.json")
TRADES = os.path.join(HERE, "paper_carry_trades.csv")
LOG = os.path.join(HERE, "paper_carry_log.txt")
RADAR_JSON = os.path.join(HERE, "web", "radar.json")
PAPER_JSON = os.path.join(HERE, "web", "paper.json")   # ringkasan publik untuk dashboard
NOTIONAL = 1000.0
MAX_POS = 3
ENTRY_APR = 4.0      # ambang masuk: hanya level yang benar-benar bisa di-carry (punya pasar spot)
EXIT_APR = 2.0
MAX_DAYS = 60
MODAL_BUKU = NOTIONAL * MAX_POS   # modal terkomit maksimum; dasar ukuran rugi
CACHE = os.path.join(HERE, "data")
LOCK_STALE_S = 600
TRADES_HEADER = ["simbol", "masuk", "keluar", "hari", "apr_masuk_pct", "apr_keluar_pct",
                 "funding_pct", "funding_harapan_pct", "biaya_pct", "basis_geser_pct",
                 "net_pct", "alasan"]


def iso(t):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t))


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _kirim_telegram(teks):
    import radar
    return radar.send(teks)


NOTIF = _kirim_telegram     # diganti di tes; tidak boleh pernah membuat tick gagal


def notif(teks):
    """Kirim kejadian penting ke Telegram. Gagal kirim hanya dicatat, tidak pernah melempar."""
    try:
        hasil = NOTIF("[paper carry] " + teks)
        if hasil and not str(hasil).startswith("terkirim"):
            log(f"notif: {hasil}")
    except Exception as e:
        log(f"notif gagal: {type(e).__name__} {e}")


def notif_sekali(st, kunci, teks, pulih=None):
    """Kirim hanya saat kondisi `kunci` BERUBAH (teks=None berarti kondisi normal).
    Mencegah spam tiap 4 jam selama kondisi buruk bertahan."""
    kini = st.setdefault("notif_state", {})
    if teks and kini.get(kunci) != teks:
        kini[kunci] = teks
        notif(teks)
    elif not teks and kunci in kini:
        del kini[kunci]
        if pulih:
            notif(pulih)


def load():
    """State hilang = mulai baru. State ADA tapi rusak = berhenti (fail closed).

    Membuat state kosong saat file rusak akan menghapus posisi terbuka, riwayat rugi,
    dan status HALT tanpa jejak — persis kondisi yang paling tidak boleh terjadi."""
    if not os.path.exists(STATE):
        return {"positions": {}, "closed": [], "equity": NOTIONAL, "started": time.time()}
    try:
        with open(STATE) as f:
            st = json.load(f)
        st.setdefault("positions", {})
        st.setdefault("closed", [])
        return st
    except (ValueError, OSError) as e:
        raise RuntimeError(f"state paper carry tidak terbaca ({e}); berhenti, periksa {STATE} manual")


def save(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=2)
    os.replace(tmp, STATE)           # atomik: crash di tengah tulis tidak merusak state


@contextlib.contextmanager
def tick_lock(stale_s=LOCK_STALE_S):
    """Satu tick pada satu waktu. Lock basi (proses mati) diambil alih setelah stale_s detik."""
    path = STATE + ".lock"
    fd = None
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > stale_s:
                    os.remove(path)
                    continue
            except OSError:
                pass
            break
    if fd is None:
        yield False
        return
    try:
        os.write(fd, str(os.getpid()).encode())
        yield True
    finally:
        os.close(fd)
        try:
            os.remove(path)
        except OSError:
            pass


def radar_load(now=None):
    """(rows, umur_jam). umur_jam None = file hilang/rusak/tanpa generated_at."""
    try:
        with open(RADAR_JSON) as f:
            d = json.load(f)
        gen = calendar.timegm(time.strptime(d["generated_at"], "%Y-%m-%d %H:%M UTC"))
        return d.get("rows", []), ((now or time.time()) - gen) / 3600
    except (OSError, ValueError, KeyError, TypeError):
        return [], None


def perp_info(sym):
    return get(f"{FAPI}/fapi/v1/premiumIndex?symbol={sym}", None, ttl=30)


def spot_price(sym):
    return float(get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}", None, ttl=30)["price"])


def new_funding(sym, since_ms):
    rows = get(f"{FAPI}/fapi/v1/fundingRate?symbol={sym}&startTime={since_ms + 1}&limit=1000",
               f"frp_{sym}_{since_ms}.json", ttl=300)
    return [(int(r["fundingTime"]), float(r["fundingRate"])) for r in rows]


def mark(p):
    """PnL berjalan posisi delta-neutral: funding + pergerakan basis."""
    sp, pp = spot_price(p["symbol"]), float(perp_info(p["symbol"])["markPrice"])
    s_leg = sp / p["spot_entry"] - 1
    p_leg = pp / p["perp_entry"] - 1
    gross = s_leg - p_leg + p["funding"]
    p["spot_now"], p["perp_now"] = sp, pp
    p["basis_pct"] = (pp / sp - 1) * 100          # basis sekarang, % dari spot
    p["gross"] = gross
    p["net"] = gross - p["cost"]
    return p


def ts_tutup(c):
    if c.get("closed"):
        return c["closed"]
    try:
        return calendar.timegm(time.strptime(c["closed_iso"], "%Y-%m-%d %H:%M"))
    except (KeyError, ValueError):
        return None


def keluar(st, sym, p, reason, now=None, apr_exit=None):
    """Tutup posisi: catat ke CSV + tahan di riwayat. Satu jalur kode untuk semua alasan keluar."""
    now = now or time.time()
    if p.get("exec"):
        if not _tutup_exec(sym, p):
            return False             # kaki nyata belum tertutup: posisi TETAP tercatat terbuka
    hari = (now - p["opened"]) / 86400
    p.update(exit_reason=reason, closed=now, closed_iso=iso(now), age_days=hari, apr_exit=apr_exit)
    st["closed"].append(p)
    baru = not os.path.exists(TRADES) or os.path.getsize(TRADES) == 0
    harapan = p.get("apr_entry", 0.0) * hari / 365          # funding yang "dijanjikan" APR masuk, dalam %
    with open(TRADES, "a", newline="") as f:
        w = csv.writer(f)
        if baru:
            w.writerow(TRADES_HEADER)
        w.writerow([sym, p["opened_iso"], p["closed_iso"], f"{hari:.2f}",
                    p.get("apr_entry", ""), "" if apr_exit is None else apr_exit,
                    f"{p['funding']*100:.3f}", f"{harapan:.3f}", f"{p['cost']*100:.3f}",
                    f"{p.get('basis_pct', 0.0) - p.get('basis_entry_pct', 0.0):.3f}",
                    f"{p['net']*100:.3f}", reason])
    log(f"KELUAR {sym}: net {p['net']*100:.3f}% (funding {p['funding']*100:.3f}%, "
        f"dijanjikan APR masuk {harapan:.3f}%) — {reason}")
    notif(f"KELUAR {sym}: net {p['net']*100:.3f}% setelah {hari:.1f} hari. Alasan: {reason}")
    del st["positions"][sym]
    return True


def _tutup_exec(sym, p):
    """Tutup kaki nyata. True kalau tertutup bersih. Gagal -> False + alert (posisi tetap terbuka)."""
    e = p["exec"]
    if EXCHANGE is None:
        notif(f"EXEC {sym}: posisi nyata terbuka tapi daemon jalan tanpa --testnet; TIDAK ditutup "
              f"di paper. Jalankan ulang dengan --testnet atau tutup manual.")
        return False
    e["close_try"] = e.get("close_try", 0) + 1       # cid baru tiap percobaan (IOC kedaluwarsa memakan cid)
    hasil = execution.tutup_carry(EXCHANGE, sym, e["qty"], p.get("spot_now", p["spot_entry"]),
                                  p.get("perp_now", p["perp_entry"]),
                                  f"{e['trade_id']}x{e['close_try']}")
    if hasil["status"] != "ok":
        log(f"EXEC GAGAL TUTUP {sym}: {hasil.get('alasan')}")
        notif(f"EXEC HALT {sym}: gagal menutup ({hasil.get('alasan')}). Posisi nyata masih terbuka; "
              f"periksa manual lalu: python3 paper_carry.py --reset-exec-halt")
        return False
    return True


def total_pnl(st):
    """PnL kumulatif (mata uang): posisi terbuka + semua yang sudah ditutup."""
    return (sum(p.get("net", 0.0) * p["notional"] for p in st["positions"].values())
            + sum(c.get("net", 0.0) * c["notional"] for c in st["closed"]))


def perubahan_pnl(st, now, total):
    """Perubahan PnL kumulatif pada jendela 1d/7d/30d, dari kurva snapshot per tick.

    Kalau riwayat belum menutupi satu jendela, angkanya = seluruh perubahan sejak
    mulai. Itu tetap benar secara hitungan (rugi 7 hari dari sistem berumur 5 hari
    memang seluruh ruginya), tapi berlabel menyesatkan. Dashboard yang menandai
    jendela mana yang belum penuh, bukan fungsi ini yang memalsukan angka.
    """
    hist, base = st.get("pnl_hist", []), st.get("base_pnl", 0.0)

    def sejak(detik):
        b = base
        for h in hist:
            if h["t"] <= now - detik:
                b = h["pnl"]
            else:
                break
        return total - b
    return sejak(86400), sejak(7 * 86400), sejak(30 * 86400)


def catat_pnl(st, now, total):
    hist = st.setdefault("pnl_hist", [])
    hist.append({"t": now, "pnl": total})
    while len(hist) > 1 and hist[1]["t"] <= now - 31 * 86400:   # buang yang tak lagi dibutuhkan jendela 30d
        st["base_pnl"] = hist[0]["pnl"]
        hist.pop(0)


def halt_aktif(st):
    h = st.get("halt")
    if h:
        return h
    if (st.get("day") or {}).get("halted"):     # kompatibel dengan state versi lama
        return {"level": "harian (versi lama)", "rugi": 0.0, "batas": 0.0}
    return None


def tick(now=None):
    now = now or time.time()
    with tick_lock() as ok:
        if not ok:
            log("tick dilewati: tick lain sedang berjalan (lock aktif)")
            return None
        st = _tick(now)
        try:
            export_web(st, now)
        except Exception as e:                       # panel web tidak boleh mengganggu simulasi
            log(f"GAGAL tulis paper.json: {type(e).__name__} {e}")
        return st


def export_web(st, now):
    """Ringkasan kecil untuk dashboard (tanpa harga mentah / detail internal)."""
    d1, d7, d30 = perubahan_pnl(st, now, total_pnl(st))
    h = halt_aktif(st)
    terbuka = sum(p.get("net", 0.0) * p["notional"] for p in st["positions"].values())
    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now)),
        "started_ms": int(st.get("started", now) * 1000),
        "modal_buku": MODAL_BUKU,
        "limits": {"harian": risk.KILL_SWITCH_HARIAN_PCT, "mingguan": risk.KILL_SWITCH_MINGGUAN_PCT,
                   "bulanan": risk.KILL_SWITCH_BULANAN_PCT},
        "halt": ({"level": h["level"], "sejak": h.get("sejak", "")} if h else None),
        "pnl": {"terbuka": round(terbuka, 2), "total": round(total_pnl(st), 2),
                "d1": round(d1, 2), "d7": round(d7, 2), "d30": round(d30, 2)},
        "positions": [{"symbol": p["symbol"], "hari": round((now - p["opened"]) / 86400, 2),
                       "apr_entry": p.get("apr_entry"), "funding_pct": round(p["funding"] * 100, 3),
                       "basis_geser_pct": round(p.get("basis_pct", 0.0) - p.get("basis_entry_pct", 0.0), 3),
                       "net_pct": round(p.get("net", 0.0) * 100, 3)} for p in st["positions"].values()],
        "closed": [{"symbol": c["symbol"], "hari": round(c.get("age_days", 0.0), 2),
                    "funding_pct": round(c["funding"] * 100, 3), "net_pct": round(c["net"] * 100, 3),
                    "alasan": c.get("exit_reason", ""), "keluar": c.get("closed_iso", "")}
                   for c in st["closed"][-8:][::-1]],
        "n_closed": len(st["closed"]),
    }
    tmp = PAPER_JSON + ".tmp"
    os.makedirs(os.path.dirname(PAPER_JSON), exist_ok=True)
    with open(tmp, "w") as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, PAPER_JSON)


def _tick(now):
    st = load()
    snap_rows, umur = radar_load(now)
    snap_ok, snap_alasan = risk.cek_snapshot(umur)
    rows = {r["symbol"]: r for r in snap_rows} if snap_ok else {}
    log(f"tick: {len(snap_rows)} koin di radar"
        f"{'' if umur is None else f' (umur {umur:.1f} jam)'}, {len(st['positions'])} posisi terbuka")
    if not snap_ok:
        log(f"PERINGATAN snapshot tidak layak: {snap_alasan} — APR tak dinilai, tak ada posisi baru")

    # 1. kelola posisi terbuka
    for sym in list(st["positions"]):
        p = st["positions"][sym]
        # posisi lama (sebelum basis stop ada) belum punya basis entry — hitung dari harga entry
        p.setdefault("basis_entry_pct", (p["perp_entry"] / p["spot_entry"] - 1) * 100)
        try:
            for ts, rate in new_funding(sym, p["last_funding_ms"]):
                p["funding"] += rate
                p["last_funding_ms"] = ts
            mark(p)
        except Exception as e:
            log(f"GAGAL NILAI {sym}: {type(e).__name__} {e} — posisi ditahan dengan angka terakhir")
            continue
        p["ticks"] = p["events"] = p.get("ticks", p.get("events", 0)) + 1
        lvl, jarak, liq = risk.cek_margin(p["perp_entry"], p.get("perp_now", p["perp_entry"]))
        notif_sekali(st, f"margin_{sym}",
                     None if lvl is None else
                     f"MARGIN {lvl.upper()} {sym}: harga perp tinggal {jarak:.0f}% lagi ke likuidasi "
                     f"(~{liq:.4g}). Tambah margin di akun futures atau kurangi posisi.",
                     pulih=f"Margin {sym} kembali aman.")
        age = (now - p["opened"]) / 86400
        # Tidak ada data = tidak bisa dinilai, dan itu dicatat (bukan jatuh ke angka konstan).
        apr = rows[sym].get("apr_7d") if sym in rows else None
        reason = None
        keluar_basis, _alasan_basis = risk.cek_basis(p.get("basis_pct", 0.0),
                                                     p.get("basis_entry_pct", 0.0))
        keluar_net, _alasan_net = risk.cek_net(p["net"] * 100)
        keluar_fund, _alasan_fund = risk.cek_funding(p["funding"] * 100)
        if lvl == "darurat":
            reason = f"jarak likuidasi darurat ({jarak:.0f}%)"
        elif keluar_fund:
            reason = _alasan_fund
        elif keluar_net:
            reason = _alasan_net
        elif apr is not None and apr < EXIT_APR:
            reason = f"APR turun ke {apr}%"
        elif keluar_basis:
            reason = _alasan_basis
        elif age >= MAX_DAYS:
            reason = f"umur {age:.0f} hari"
        if reason:
            keluar(st, sym, p, reason, now, apr)
        elif apr is None:
            log(f"TAHAN  {sym}: APR tak bisa dinilai (tidak ada di snapshot / snapshot basi) — "
                f"backstop net {risk.NET_STOP_PCT}% yang menjaga (net {p['net']*100:.3f}%)")
        else:
            log(f"TAHAN  {sym}: net {p['net']*100:.3f}% (funding {p['funding']*100:.3f}%) "
                f"basis {p.get('basis_pct', 0.0):.3f}% apr7d {apr}%")

    # 1b. Kill switch berlapis. Dihitung dari kurva PnL kumulatif (terbuka + tertutup),
    # jadi rugi yang direalisasikan pagi tidak hilang dari hitungan saat posisi baru dibuka sore.
    total = total_pnl(st)
    d1, d7, d30 = perubahan_pnl(st, now, total)
    level, rugi, batas = risk.cek_drawdown(MODAL_BUKU, d1, d7, d30)
    halt = halt_aktif(st)
    if level and not halt:
        halt = st["halt"] = {"level": level, "rugi": rugi, "batas": batas, "sejak": iso(now)}
        log(f"KILL SWITCH {level}: rugi {rugi:.2f}% >= batas {batas}% -> tutup semua posisi, "
            f"berhenti sampai direset manual")
        notif(f"KILL SWITCH {level}: rugi {rugi:.2f}% >= batas {batas}%. Semua posisi ditutup, "
              f"bot berhenti. Reset manual: python3 paper_carry.py --reset-halt")
        for sym in list(st["positions"]):
            keluar(st, sym, st["positions"][sym], f"kill switch {level} ({rugi:.2f}%)", now)
    catat_pnl(st, now, total_pnl(st))
    if halt:
        log(f"HENTI SEMENTARA ({halt['level']}): tidak buka posisi baru. "
            f"Reset dengan: python3 paper_carry.py --reset-halt")
        save(st)
        return st

    # 2. buka posisi baru — hanya kalau semua penjaga lolos.
    notif_sekali(st, "radar", None if snap_ok else f"TIDAK BUKA POSISI: {snap_alasan}",
                 pulih="Radar kembali normal, bot boleh membuka posisi lagi.")
    if not snap_ok:
        log(f"TIDAK BUKA POSISI BARU: {snap_alasan}")
        save(st)
        return st
    blok, alasan = risk.cek_cooldown([c.get("net", 0.0) for c in st["closed"]],
                                     ts_tutup(st["closed"][-1]) if st["closed"] else None, now)
    if blok:
        log(f"TIDAK BUKA POSISI BARU: {alasan}")
        save(st)
        return st

    # Kandidat memakai aturan kualitas yang sama seperti gate radar, TAPI ambang APR sendiri,
    # supaya jejak eksekusi terkumpul pada koin yang benar-benar bisa di-carry (punya pasar spot).
    def layak(r):
        return (r.get("has_spot") and r["bond_days"] >= 30 and r["apr_7d"] >= ENTRY_APR
                and (r["spread_bps"] or 99) <= 15.0 and r["volume_musd"] >= 50.0)

    kandidat = sorted((r for r in rows.values() if layak(r)), key=lambda r: -r["apr_7d"])
    terakhir_tutup = {}
    for c in st["closed"]:
        terakhir_tutup[c["symbol"]] = ts_tutup(c)
    dibuka = 0
    for r in kandidat:
        if len(st["positions"]) >= MAX_POS or dibuka >= risk.MAX_ENTRY_PER_TICK:
            break
        sym = r["symbol"]
        if sym in st["positions"]:
            continue
        tahan, sisa = risk.cek_cooldown_simbol(terakhir_tutup.get(sym), now)
        if tahan:
            log(f"LEWATI {sym}: baru keluar, jeda {sisa:.1f} jam lagi (anti-churn)")
            continue
        try:
            pp = perp_info(sym)["markPrice"]
            sp = spot_price(sym)
            hist = new_funding(sym, int(now * 1000) - 8 * 3600 * 1000)
        except Exception as e:
            log(f"gagal ambil harga {sym}: {type(e).__name__} {e}")
            continue
        info = None
        if EXCHANGE is not None:
            if execution.halt_aktif():
                notif_sekali(st, "exec_halt", "EXEC HALT aktif: tidak ada order baru. "
                             "Periksa manual lalu: python3 paper_carry.py --reset-exec-halt",
                             pulih="EXEC HALT sudah direset.")
                break
            notif_sekali(st, "exec_halt", None, pulih="EXEC HALT sudah direset.")
            tid = f"{sym}-{int(now)}"
            try:
                if hasattr(EXCHANGE, "setup"):
                    EXCHANGE.setup(sym)
                hasil = execution.buka_carry(EXCHANGE, sym, EXEC_NOTIONAL, sp, float(pp), tid)
            except (execution.Rejected, execution.Unknown) as e:
                log(f"EXEC LEWATI {sym}: setup/qty gagal sebelum order ({e})")
                continue
            if hasil["status"] == "halt":
                log(f"EXEC HALT {sym}: {hasil.get('alasan')}")
                notif(f"EXEC HALT {sym}: {hasil.get('alasan')}. Bot berhenti membuka posisi; periksa manual.")
                break
            if hasil["status"] != "ok":
                log(f"EXEC GAGAL BERSIH {sym}: {hasil.get('alasan')}")
                continue
            info = {"trade_id": tid, "qty": hasil["qty"]}
            sp, pp = hasil["spot"][1], hasil["perp"][1]     # harga isi nyata, bukan harga referensi
        st["positions"][sym] = {
            "symbol": sym, "opened": now, "opened_iso": iso(now),
            "spot_entry": sp, "perp_entry": float(pp),
            "basis_entry_pct": (float(pp) / sp - 1) * 100,
            "cost": r["carry_cost_pct"] / 100, "funding": 0.0,
            "last_funding_ms": hist[-1][0] if hist else int(now * 1000),
            "apr_entry": r["apr_7d"], "notional": NOTIONAL, "ticks": 0}
        if info:
            st["positions"][sym]["exec"] = info
        dibuka += 1
        log(f"MASUK  {sym}: APR {r['apr_7d']}% biaya {r['carry_cost_pct']}% "
            f"kapasitas ${r.get('depth_usd') or 0:,}")
        notif(f"MASUK {sym}: APR {r['apr_7d']}%, biaya {r['carry_cost_pct']}%, notional ${NOTIONAL:,.0f}")
    save(st)
    return st


def status():
    st = load()
    tot = 0.0
    h = halt_aktif(st)
    if h:
        print(f"*** HALT ({h['level']}) — posisi baru dikunci sampai --reset-halt ***\n")
    print(f"{'simbol':<14}{'umur':>6}{'funding':>10}{'basis':>9}{'net':>9}{'APR masuk':>10}")
    for sym, p in st["positions"].items():
        try:
            mark(p)
        except Exception as e:
            print(f"{sym:<14}harga tak terjangkau ({type(e).__name__}); pakai angka terakhir")
        age_h = (time.time() - p["opened"]) / 3600
        tot += p["net"]
        print(f"{sym:<14}{age_h:>5.1f}h{p['funding']*100:>9.3f}%"
              f"{(p['gross']-p['funding'])*100:>8.3f}%{p['net']*100:>8.3f}%{p['apr_entry']:>9.1f}%")
    if st["closed"]:
        print(f"\nsudah ditutup ({len(st['closed'])}):")
        for p in st["closed"]:
            print(f"  {p['symbol']:<14} net {p['net']*100:>7.3f}%  "
                  f"funding {p['funding']*100:>7.3f}%  {p['exit_reason']}")
    print(f"\nPnL berjalan terbuka: {tot*NOTIONAL:+.2f} (nominal {NOTIONAL:.0f}/buku)")
    return st


def loop():
    log("paper carry mulai: mode loop tiap 4 jam")
    while True:
        try:
            tick()
        except Exception as e:
            log(f"ERROR tick: {e}")
            notif(f"ERROR tick: {type(e).__name__} {e}")
        time.sleep(4 * 3600)


def reset_halt():
    st = load()
    st.pop("halt", None)
    st.pop("day", None)
    st["base_pnl"] = total_pnl(st)     # jendela rugi mulai dari nol; tanpa ini kill switch langsung terpicu lagi
    st["pnl_hist"] = []
    save(st)
    print("status henti direset; jendela rugi dimulai ulang; tick berikutnya boleh buka posisi baru")


def selfcheck():
    """Jalankan test sungguhan (test_paper_carry.py): memanggil tick()/keluar()/mark() asli
    dengan jaringan ditiru. Menggantikan selfcheck lama yang cuma menguji aritmatika sendiri."""
    import unittest
    import test_paper_carry
    hasil = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_paper_carry))
    if not hasil.wasSuccessful():
        raise AssertionError("test_paper_carry gagal")
    print("selfcheck OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--reset-halt", action="store_true")
    ap.add_argument("--reset-exec-halt", action="store_true")
    ap.add_argument("--testnet", action="store_true",
                    help="kirim order sungguhan ke Binance TESTNET (kunci dari env BINANCE_TESTNET_*)")
    a = ap.parse_args()
    if a.testnet:
        import binance_testnet
        EXCHANGE = binance_testnet.BinanceTestnet()
        log("MODE TESTNET: order nyata ke Binance testnet, nominal "
            f"{EXEC_NOTIONAL:.0f} per posisi")
    if a.reset_exec_halt:
        execution.reset_halt()
        print("exec halt direset")
    elif a.selftest:
        selfcheck()
    elif a.reset_halt:
        reset_halt()
    elif a.status:
        status()
    elif a.loop:
        loop()
    elif a.tick:
        if tick() is not None:
            status()
    else:
        ap.print_help()
    sys.exit(0)
