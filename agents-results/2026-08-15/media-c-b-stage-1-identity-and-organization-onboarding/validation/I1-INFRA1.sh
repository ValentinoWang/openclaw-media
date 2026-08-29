#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i1/frontend"
cd "$root"
npm run qa:chromium-slot-contract
exec bash "/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/validation/I1.sh"
