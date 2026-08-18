#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "--" ]; then
  shift
fi
if [ "$#" -eq 0 ]; then
  echo "Usage: $0 -- <browser command> [args...]" >&2
  exit 64
fi

readonly max_slots="${MEDIA_CHROMIUM_MAX_CONCURRENCY:-2}"
case "$max_slots" in
  1|2|3|4) ;;
  *)
    echo "MEDIA_CHROMIUM_MAX_CONCURRENCY must be an integer from 1 to 4" >&2
    exit 64
    ;;
esac

readonly lock_root="${MEDIA_CHROMIUM_LOCK_ROOT:-/tmp/openclaw-media-chromium-slots}"
readonly poll_seconds="${MEDIA_CHROMIUM_SLOT_POLL_SECONDS:-1}"
readonly wait_seconds="${MEDIA_CHROMIUM_SLOT_WAIT_SECONDS:-900}"
case "$poll_seconds" in
  ''|*[!0-9]*)
    echo "MEDIA_CHROMIUM_SLOT_POLL_SECONDS must be a positive integer" >&2
    exit 64
    ;;
esac
case "$wait_seconds" in
  ''|*[!0-9]*)
    echo "MEDIA_CHROMIUM_SLOT_WAIT_SECONDS must be a positive integer" >&2
    exit 64
    ;;
esac
if [ "$poll_seconds" -lt 1 ] || [ "$wait_seconds" -lt 1 ]; then
  echo "Chromium slot poll and wait values must both be at least 1 second" >&2
  exit 64
fi
mkdir -p "$lock_root"
readonly started_at="$SECONDS"

lock_backend=""
if command -v flock >/dev/null 2>&1; then
  lock_backend="flock"
elif command -v lockf >/dev/null 2>&1; then
  lock_backend="lockf"
else
  echo "Chromium slot QA requires flock or lockf" >&2
  exit 69
fi

while true; do
  for ((slot = 1; slot <= max_slots; slot += 1)); do
    lock_path="${lock_root}/slot-${slot}.lock"
    if [ "$lock_backend" = "flock" ]; then
      # macOS ships Bash 3.2, which does not support Bash 4's dynamic fd syntax.
      exec 9>"$lock_path"
      if flock -n 9; then
        echo "Chromium slot ${slot}/${max_slots} acquired for: $*" >&2
        status=0
        "$@" || status=$?
        flock -u 9
        exec 9>&-
        exit "$status"
      fi
      exec 9>&-
    else
      lockf -k -t 0 "$lock_path" "$@"
      status=$?
      if [ "$status" -ne 75 ]; then
        echo "Chromium slot ${slot}/${max_slots} acquired for: $*" >&2
        exit "$status"
      fi
    fi
  done
  if (( SECONDS - started_at >= wait_seconds )); then
    echo "Timed out after ${wait_seconds}s waiting for a Chromium slot (${max_slots} configured)" >&2
    exit 75
  fi
  sleep "$poll_seconds"
done
