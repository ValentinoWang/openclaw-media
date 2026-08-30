#!/usr/bin/env bash
set -euo pipefail
repo='/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/production-reconciliation-20260825'
test "$(git -C "$repo" rev-parse HEAD)" = '5f06780569568ccc3197f0ab16aad74bdf9d1c6f'
test -z "$(git -C "$repo" status --porcelain=v1)"
test "$(ssh -o BatchMode=yes ubuntu@106.52.146.37 "systemctl --user show openclaw-stage2.service -p MainPID --value")" = '1314975'
test "$(ssh -o BatchMode=yes ubuntu@106.52.146.37 "readlink -f /proc/1314975/cwd")" = '/home/ubuntu/releases/openclaw-stage2-production-20260819T'
