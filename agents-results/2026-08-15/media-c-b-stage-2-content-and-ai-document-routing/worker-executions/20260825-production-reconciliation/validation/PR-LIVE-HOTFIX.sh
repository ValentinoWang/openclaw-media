#!/usr/bin/env bash
set -euo pipefail
repo='/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/production-reconciliation-20260825'
release='/home/ubuntu/releases/openclaw-stage2-production-20260819T'
test "$(git -C "$repo" rev-parse HEAD)" = '5f06780569568ccc3197f0ab16aad74bdf9d1c6f'
test -z "$(git -C "$repo" status --porcelain=v1)"
actual="$(ssh -o BatchMode=yes ubuntu@106.52.146.37 "sha256sum '$release/openclaw_app/contracts/stage2_writer_contract.json' '$release/openclaw_app/services/stage2_production_factory.py'")"
printf '%s\n' "$actual" | grep -q '^f877a8bd4660b9e66130023f568e2405360da3b921e917cba6fe72bb42347869 '
printf '%s\n' "$actual" | grep -q '^d87a158cfa417ca2124585c310bc30f68349993e423afc9cb78ecdc8b75a411c '
