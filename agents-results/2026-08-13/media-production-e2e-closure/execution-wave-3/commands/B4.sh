#!/usr/bin/env bash
set -euo pipefail

ssh -o BatchMode=yes -o ConnectTimeout=10 ubuntu@106.52.146.37 'bash -s' <<'REMOTE'
set -euo pipefail

source_snapshot=/home/ubuntu/worktrees/openclaw-bot-center-a1-media-cb-preview-20260808
frontend_root=/home/ubuntu/openclaw-bot-center
backend_root=/home/ubuntu/selfmedia-tools/openclaw-tag-router
release_root=/mnt/openclaw-data/openclaw-media-frontend-releases
old_release=20260811T201753CST-media-cb-preview-cp1-r2
new_release=20260813T182852CST-media-e2e-b4-label-guard-v1
expected_backend=openclaw-tag-router-media-tenant-20260811T201753CST-media-cb-preview-cp1-r2

status_digest() {
  git -C "$1" status --porcelain=v1 -uall | LC_ALL=C sort | sha256sum | awk '{print $1}'
}

[[ "$(status_digest "$source_snapshot")" == a13fef62351d368256cee5361d11887a4fc53db800417c0304db73797ec5123d ]]
[[ "$(status_digest "$frontend_root")" == 1e6f7268514e46b1c9ca136e236813e5617bd98b2e9f548317d1acf3182b21f0 ]]
[[ "$(status_digest "$backend_root")" == 02d9e1021e95e14f1ec6d125934ddca402d8543be8c28551647e564e1b2a23c4 ]]

active_release=$(basename "$(readlink -f /var/www/openclaw/media)")
[[ "$active_release" == "$new_release" ]]
[[ -d "$release_root/$old_release" ]]
[[ -d "$release_root/$new_release" ]]

coordinated_backend=$(python3 - "$release_root/$new_release/.release-coordination.json" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["schemaVersion"] == "openclaw-media-release-coordination-v1"
assert payload["frontendRelease"] == "20260813T182852CST-media-e2e-b4-label-guard-v1"
print(payload["backendRelease"])
PY
)
[[ "$coordinated_backend" == "$expected_backend" ]]

(cd "$release_root/$new_release" && sha256sum -c --quiet .manifest.sha256)
for path in "$release_root/$new_release" "$release_root/$old_release"; do
  attrs=$(lsattr -d "$path" | awk '{print $1}')
  [[ "$attrs" == *i* ]]
done

python3 - "$release_root/$new_release" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
text = "\n".join(
    path.read_text(encoding="utf-8", errors="ignore")
    for path in root.rglob("*")
    if path.is_file() and path.suffix in {".css", ".html", ".js", ".json", ".txt"}
)
required = (
    "总览", "账号与赛道", "素材与灵感", "选题与决策", "创作与交付", "发布准备",
    "复盘增长", "Media Agent", "云端归档", "用量与余额", "邀请中心",
    "平台总览", "用户与准入", "租户资源", "计费运营", "上游服务",
)
retired = ("媒体处理", "系统与工具", "设置与偏好", "平台管理", "用量与套餐", "赛道与博主")
for label in required:
    assert label in text, f"missing required label: {label}"
for label in retired:
    patterns = (f'"{label}"', f"'{label}'", f'`{label}`', f'>{label}<')
    assert not any(pattern in text for pattern in patterns), f"retired exact label remains: {label}"
PY

sudo -n /usr/local/sbin/verify-openclaw-media
[[ "$(systemctl show -p Result --value openclaw-media-deployment-guard.service)" == success ]]
[[ "$(systemctl show -p ExecMainStatus --value openclaw-media-deployment-guard.service)" == 0 ]]
[[ "$(systemctl is-active openclaw-media-deployment-guard.timer)" == active ]]
curl -fsS http://127.0.0.1:8787/healthz >/dev/null
curl -fsS http://127.0.0.1:8787/readyz >/dev/null

disk_hash=$(sha256sum "$release_root/$new_release/index.html" | awk '{print $1}')
served_hash=$(curl -fsS http://127.0.0.1/openclaw/media/ | sha256sum | awk '{print $1}')
[[ "$disk_hash" == "$served_hash" ]]

python3 - "$release_root/$new_release/.source-snapshot.json" "$release_root/$new_release/.source-to-artifact.json" <<'PY'
import json
import pathlib
import sys

snapshot = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
mapping = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
assert snapshot["schemaVersion"] == "openclaw-media-source-snapshot-v1"
assert snapshot["baseCommit"] == "db13e39aa4914d2168efcab5e2d9d6c2b26a41d8"
assert mapping["schemaVersion"] == "openclaw-media-source-to-artifact-v1"
assert mapping["frontendRelease"] == "20260813T182852CST-media-e2e-b4-label-guard-v1"
assert mapping["backendRelease"] == "openclaw-tag-router-media-tenant-20260811T201753CST-media-cb-preview-cp1-r2"
assert mapping["build"]["command"] == "npm run build:media"
assert mapping["rollbackPlan"]["required"] is True
assert mapping["rollbackPlan"]["oldFrontendRelease"] == "20260811T201753CST-media-cb-preview-cp1-r2"
PY

if find /tmp -maxdepth 1 -type d -name 'media-e2e-b4.*' -print -quit | grep -q .; then
  echo 'B4 temporary build directory remains' >&2
  exit 1
fi

printf 'B4_VALIDATION_PASS release=%s backend=%s index_sha256=%s\n' "$new_release" "$coordinated_backend" "$disk_hash"
REMOTE
