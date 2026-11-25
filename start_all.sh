#!/usr/bin/env bash
# Nyalakan semua daemon crypto-bot. Aman dijalankan berulang: yang sudah hidup dilewati.
# Pakai: bash start_all.sh          (hentikan semua: bash start_all.sh stop)
#
# Pola proses di-anchor ke path python (^...) supaya pkill tidak ikut membunuh
# shell pemanggil yang command line-nya memuat teks yang sama.
set -u
cd "$(dirname "$0")" || exit 1
PY=/tmp/vlog/bin/python
NAMES=(paper_carry scan_and_push watchdog)
LOGS=(paper_carry_daemon.log radar_cron.log watchdog_daemon.log)
# TESTNET=1 menyalakan paper_carry dengan --testnet: order demo nyata 600/posisi, maks 3.
# Default mati supaya tidak ada order terkirim tanpa sengaja.
EXTRA_paper_carry=""
[ "${TESTNET:-0}" = "1" ] && EXTRA_paper_carry="--testnet"
# MAX_EXEC_POS = berapa posisi yang benar-benar dikirim ke bursa (sisanya paper).
# Naikkan ke 3 hanya setelah satu siklus buka-tutup nyata bersih.
export MAX_EXEC_POS="${MAX_EXEC_POS:-1}"

pola() { echo "^${PY} ${1}\.py --loop"; }

if [ "${1:-}" = "stop" ]; then
  for n in "${NAMES[@]}"; do
    if pkill -f "$(pola "$n")"; then echo "stop  $n"; else echo "mati  $n"; fi
  done
  exit 0
fi

for i in "${!NAMES[@]}"; do
  n="${NAMES[$i]}"; log="${LOGS[$i]}"
  extra_var="EXTRA_${n}"; extra="${!extra_var:-}"
  if pgrep -f "$(pola "$n")" >/dev/null; then
    echo "hidup $n (dilewati)"
    continue
  fi
  # shellcheck disable=SC2086
  nohup "$PY" "$n.py" --loop $extra >> "$log" 2>&1 &
  sleep 1
  if pgrep -f "$(pola "$n")" >/dev/null; then
    echo "start $n ${extra:+(--testnet)} -> pid $(pgrep -f "$(pola "$n")" | head -1)"
  else
    echo "GAGAL $n, cek $log"
  fi
done
