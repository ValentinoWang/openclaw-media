#!/usr/bin/env bash
set -euo pipefail

ssh -o BatchMode=yes -o ConnectTimeout=10 ubuntu@106.52.146.37 'bash -s' <<'REMOTE'
set -euo pipefail

base=/home/ubuntu/worktrees/openclaw-bot-center-a1-media-cb-preview-20260808
release_root=/mnt/openclaw-data/openclaw-media-frontend-releases
old_release=20260811T201753CST-media-cb-preview-cp1-r2
new_release=20260813T184753CST-media-e2e-b4-label-guard-r2
backend_id=openclaw-tag-router-media-tenant-20260811T201753CST-media-cb-preview-cp1-r2
backend_link=/home/ubuntu/.openclaw/releases/$backend_id
backend_real=/mnt/openclaw-data/openclaw-media-release-stage/$backend_id

status_digest() {
  git -C "$1" status --porcelain=v1 -uall | LC_ALL=C sort | sha256sum | awk '{print $1}'
}

source_input_digest() {
  (
    cd "$base"
    printf '%s\0' \
      src/media/mediaRoleIa.ts \
      src/media/i18n/resourceLabels.ts \
      src/media/displayLabels.ts \
      src/media/ui/displayLabels.ts \
      src/media/pages/ordinary/TracksPage.tsx \
      scripts/qa/checkMediaRoleIa.ts \
      scripts/qa/checkMediaLanguageCatalog.ts \
      scripts/qa/checkMediaReleaseLabels.ts \
      package.json package-lock.json vite.media.config.ts \
      | xargs -0 sha256sum
  ) | sha256sum | awk '{print $1}'
}

backend_tree_digest() {
  (cd "$backend_real" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum) \
    | sha256sum | awk '{print $1}'
}

[[ "$(git -C "$base" rev-parse HEAD)" == db13e39aa4914d2168efcab5e2d9d6c2b26a41d8 ]]
[[ "$(status_digest "$base")" == a13fef62351d368256cee5361d11887a4fc53db800417c0304db73797ec5123d ]]
[[ "$(source_input_digest)" == 2c90c87838d89e1e90570174ffdd1b852d8752a0fd1262d383f458651967f0eb ]]
[[ "$(readlink -f "$backend_link")" == "$backend_real" ]]
[[ "$(backend_tree_digest)" == d4f036a093cc3714d6f295b1e44db34dc3c10f0e684d7b8c64fcfdedba9b6c1b ]]
[[ "$(sudo -n sha256sum /usr/local/sbin/deploy-openclaw-media-locked | awk '{print $1}')" == 007ce7ed6d2f3444cf94f9a08b6936f2ff5547163c4abadefd5338917c3358b0 ]]
[[ "$(sudo -n sha256sum /usr/local/sbin/verify-openclaw-media | awk '{print $1}')" == e7c4e3d31be27a64c551b2bfde6b08c88922d6bb207408b78d73aec64204428e ]]

active_release=$(basename "$(readlink -f /var/www/openclaw/media)")
[[ "$active_release" == "$new_release" ]]
[[ -d "$release_root/$old_release" ]]
[[ -d "$release_root/$new_release" ]]
[[ "$(sha256sum "$release_root/$old_release/index.html" | awk '{print $1}')" == af38cc8fa89a45de2f3ddcbd1f3fe9f27bd9c8b431695483dc7b71b2450e5d2c ]]
[[ "$(sha256sum "$release_root/$old_release/.manifest.sha256" | awk '{print $1}')" == 8bba584e84fc338f7892ff2158d6715d922eb18afbffed2d6b254ad0e73b2a9c ]]

coordinated_backend=$(python3 - "$release_root/$new_release/.release-coordination.json" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["schemaVersion"] == "openclaw-media-release-coordination-v1"
assert payload["frontendRelease"] == "20260813T184753CST-media-e2e-b4-label-guard-r2"
print(payload["backendRelease"])
PY
)
[[ "$coordinated_backend" == "$backend_id" ]]

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

python3 - "$release_root/$new_release/.source-snapshot.json" "$release_root/$new_release/.source-to-artifact.json" <<'PY'
import json
import pathlib
import sys

snapshot_path = pathlib.Path(sys.argv[1])
mapping_path = pathlib.Path(sys.argv[2])
snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
assert snapshot["schemaVersion"] == "openclaw-media-source-snapshot-v1"
assert snapshot["baseCommit"] == "db13e39aa4914d2168efcab5e2d9d6c2b26a41d8"
assert snapshot["baseStatusDigest"] == "a13fef62351d368256cee5361d11887a4fc53db800417c0304db73797ec5123d"
assert snapshot["baseSourceFileListSha256"] == "2c90c87838d89e1e90570174ffdd1b852d8752a0fd1262d383f458651967f0eb"
assert snapshot["buildCommand"] == "npm run build:media"
assert snapshot["frontendRelease"] == "20260813T184753CST-media-e2e-b4-label-guard-r2"
assert snapshot["backendRelease"] == "openclaw-tag-router-media-tenant-20260811T201753CST-media-cb-preview-cp1-r2"
assert len(snapshot["patchedSourceFiles"]) == 8
assert mapping["schemaVersion"] == "openclaw-media-source-to-artifact-v1"
assert mapping["frontendRelease"] == "20260813T184753CST-media-e2e-b4-label-guard-r2"
assert mapping["backendRelease"] == "openclaw-tag-router-media-tenant-20260811T201753CST-media-cb-preview-cp1-r2"
assert mapping["build"]["command"] == "npm run build:media"
assert mapping["rollbackPlan"]["required"] is True
assert mapping["rollbackPlan"]["oldFrontendRelease"] == "20260811T201753CST-media-cb-preview-cp1-r2"
PY

pid=$(ss -H -ltnp 'sport = :8787' | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
[[ "$pid" =~ ^[0-9]+$ ]]
python3 - "$pid" "$backend_link" <<'PY'
from pathlib import Path
import sys

pid, backend = sys.argv[1:]
argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
argv = [part.decode() for part in argv if part]
assert argv[0] == "/usr/bin/python3"
def pair(flag, value):
    return any(argv[i] == flag and argv[i + 1] == value for i in range(len(argv) - 1))
assert pair("-m", "openclaw_app.server_cli")
assert pair("--settings", backend + "/config/settings.yaml")
assert pair("--port", "8787")
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
while read -r expected_hash relative_path; do
  relative_path=${relative_path#\*}
  relative_path=${relative_path#./}
  actual_hash=$(curl -fsS "http://127.0.0.1/openclaw/media/$relative_path" | sha256sum | awk '{print $1}')
  [[ "$expected_hash" == "$actual_hash" ]]
done < "$release_root/$new_release/.manifest.sha256"

if find /tmp -maxdepth 1 -type d -name 'media-e2e-b4.*' -print -quit | grep -q .; then
  echo 'B4 temporary build directory remains' >&2
  exit 1
fi

printf 'B4_R2_VALIDATION_PASS release=%s backend=%s index_sha256=%s\n' "$new_release" "$coordinated_backend" "$disk_hash"
REMOTE
