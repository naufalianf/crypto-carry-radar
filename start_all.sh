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

pola() { echo "^${PY} ${1}\.py --loop"; }

if [ "${1:-}" = "stop" ]; then
  for n in "${NAMES[@]}"; do
    if pkill -f "$(pola "$n")"; then echo "stop  $n"; else echo "mati  $n"; fi
  done
  exit 0
fi

for i in "${!NAMES[@]}"; do
  n="${NAMES[$i]}"; log="${LOGS[$i]}"
  if pgrep -f "$(pola "$n")" >/dev/null; then
    echo "hidup $n (dilewati)"
    continue
  fi
  nohup "$PY" "$n.py" --loop >> "$log" 2>&1 &
  sleep 1
  if pgrep -f "$(pola "$n")" >/dev/null; then
    echo "start $n -> pid $(pgrep -f "$(pola "$n")" | head -1)"
  else
    echo "GAGAL $n, cek $log"
  fi
done
