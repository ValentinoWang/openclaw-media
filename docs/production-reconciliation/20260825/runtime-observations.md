# Production Reconciliation Runtime Observations

- Observation date: 2026-08-25 Asia/Shanghai
- Host: `106.52.146.37`
- Evidence mode: read-only, redacted, status-only
- Service authority: user unit `openclaw-stage2.service`
- State: `active/running`
- Main PID: `1314975`
- Working directory: `/home/ubuntu/releases/openclaw-stage2-production-20260819T`
- Direct port: `8892`

## Direct-port probes

| Probe | Status |
| --- | ---: |
| `GET /healthz` | 200 |
| `GET /readyz` | 200 |
| `GET /stage2/healthz` | 404 |
| `GET /stage2/readyz` | 404 |
| `POST /stage2/personal` without credentials | 401 `authentication_required` |
| `POST /stage2/organization` without credentials | 401 `authentication_required` |

The public Nginx layer rewrites `/stage2/healthz` and `/stage2/readyz` to the
unprefixed direct-port endpoints. A direct-port 404 for the prefixed paths is
therefore not the same observation as a public-route failure.

No authenticated request, database content read, environment value read,
Feishu write, process restart, deployment, traffic switch, or release mutation
was performed. These observations do not prove current GitHub `main`, an
immutable release identity, authenticated business behavior, or formal Stage-2
acceptance.
