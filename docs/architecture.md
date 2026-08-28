# SelfMedia Tools Architecture

This document is the directory-responsibility reference for this repository.
`README.md` is only an entry page. Bot-local `AGENTS.md` files may point here, but must not redefine these boundaries.

## Core Rule

Every selfmedia capability has exactly one code owner, one runtime entrypoint, and one artifact root.

```text
OpenClaw media Bot
  -> runtime/cli/selfmedia.py
  -> selfmedia/*
  -> media_model / media_vault / integrations
```

The following paths are different roles, not competing implementations:

```text
media_vault/
  role: code package
  owns: MediaVault API, media:// URI, manifest validation, artifact write helpers
  may contain: Python source and tests
  must not contain: run artifacts, downloaded media, CreationRun payloads

data/media_vault/
  role: canonical artifact storage root
  owns: CreationRun, deconstruction, creator profile, business, review, style_polish artifacts
  may contain: JSON, Markdown, screenshots, media files, manifests
  must not contain: Python business logic or alternative writers

openclaw-tag-router/
  role: source SSOT for the OpenClaw tag-router adapter
  owns: tag routing code, capability definitions, adapter tests
  must be edited before deployment

.openclaw/extensions/openclaw-tag-router/
  role: deployed runtime copy
  owns: the files loaded by OpenClaw at runtime
  must match: the repository `openclaw-tag-router/` source after deployment
  must not be used as the source edit location

.openclaw/workspace/openclaw-tag-router/
  role: runtime workspace data
  owns: inbox, outbox, archive, logs, tmp, content_flow runtime files
  must not contain: source authority for tag-router behavior

openclaw-bot-center/public/data/openclaw-bot-center.generated.json
  role: generated frontend projection
  owns: capability detail data generated from the active tag-router registry
  must match: active tag-router capability registry after generate:data

openclaw-bot-center/dist/
  role: built frontend artifact
  owns: static files produced by npm run build
  must match: public generated data

/var/www/openclaw/bots/
  role: published frontend artifact
  owns: served static Bot Center files
  must match: openclaw-bot-center/dist/

日记 / 周记 timer
  role: systemd scheduling authority
  owns: daily 22:00 journal prompt and Sunday 23:59 weekly self-model trigger
  must match: openclaw-tag-router/deploy/systemd/user/*

OpenClaw cron
  role: unrelated OpenClaw scheduled jobs
  must not contain: competing Daily journal or weekly self-model jobs

openclaw-agents/media/
  role: media Bot local workspace
  owns: Bot instructions, thin selfmedia entrypoint, generated files, attachment manifests, tmp analysis
  must not contain: independent selfmedia business workflows
```

## Canonical Directory Tree

```text
repository root/
|-- README.md                         # entry page; points to this document
|-- docs/
|   `-- architecture.md               # directory-responsibility SSOT
|
|-- common/                           # cross-workflow helpers
|-- config/
|   |-- openclaw_bots.json            # Bot/model/profile config SSOT
|   `-- platform_mechanisms/          # platform mechanism configs
|
|-- selfmedia/                        # public selfmedia business layer
|   |-- ingest/
|   |   |-- content_flow/
|   |   |-- music_resource/
|   |   `-- diagnostics/
|   |-- deconstruct/
|   |   `-- viral_content/
|   |-- creation/
|   |-- review/
|   |-- context/
|   |-- creator_profiles/
|   |-- business/
|   `-- style/
|
|-- media_model/                      # Media Model contract and writer ports
|-- media_vault/                      # artifact/evidence storage API
|-- integrations/
|   |-- feishu/                       # concrete Feishu writer implementation
|   `-- platform_auth/
|
|-- runtime/
|   |-- cli/                          # public CLI entrypoint
|   |-- evidence/
|   `-- maintenance/
|       |-- backfills/
|       |-- deploy/
|       `-- sync/
|
|-- openclaw-tag-router/              # tag-router source SSOT
|-- data/
|   |-- media_memory/tenants/<tenant_id>/ # tenant account profile and review memory
|   `-- media_vault/tenants/<tenant_id>/  # canonical tenant artifact storage root
|-- tests/
|-- downloads/                        # local download cache
`-- outputs/                          # local temporary output and backups
```

## Capability Owners

| Capability | Code owner | Runtime entrypoint | Artifact owner |
|---|---|---|---|
| Content ingest and media analysis | `selfmedia/ingest/content_flow/` | `runtime/cli/selfmedia.py run ingest` | `data/media_vault/tenants/<tenant_id>/source_assets/` or tenant-scoped local download cache |
| Music resource extraction | `selfmedia/ingest/music_resource/` | module or package script under that directory | caller-selected tenant output or `data/media_vault/tenants/<tenant_id>/source_assets/` |
| Field health diagnostics | `selfmedia/ingest/diagnostics/field_health.py` | direct module call | `data/media_vault/tenants/<tenant_id>/field_health_runs/` |
| Viral deconstruction | `selfmedia/deconstruct/viral_content/` | `runtime/cli/selfmedia.py run deconstruct` | `data/media_vault/tenants/<tenant_id>/deconstructions/` |
| Creation workflows | `selfmedia/creation/` | `runtime/cli/selfmedia.py` creation commands | `data/media_vault/tenants/<tenant_id>/creation_runs/` |
| Account daily polling | `runtime/cli/selfmedia.py` | `runtime/cli/selfmedia.py daily-poll --tenant-id <tenant_id>` | `data/media_vault/tenants/<tenant_id>/account_daily_runs/` |
| Data review | `selfmedia/review/` | `runtime/cli/selfmedia.py data-review` | `data/media_vault/tenants/<tenant_id>/data_review_runs/` |
| Creator profiles | `selfmedia/creator_profiles/` | tag-router adapter or public service call | `data/media_vault/tenants/<tenant_id>/creator_profiles/` |
| Business ID and quotes | `selfmedia/business/` | `python3 -m selfmedia.business.id_business` | `data/media_vault/tenants/<tenant_id>/business/` |
| Style polish | `selfmedia/style/` | `openclaw_app/router/style_polish.py` or public service call | `data/media_vault/tenants/<tenant_id>/style_polish_runs/` |
| Image generation | `selfmedia/creation/image_generation.py` | `python3 -m selfmedia.creation.image_generation` | `openclaw-agents/media/generated/gpt-image-2/` |

## Dependency Direction

Allowed:

```text
openclaw-tag-router -> selfmedia -> media_model
openclaw-tag-router -> selfmedia -> media_vault
openclaw-tag-router -> selfmedia -> integrations
runtime             -> selfmedia / media_model / media_vault / integrations
tests               -> all project layers
```

Blocked:

```text
selfmedia -> openclaw-tag-router
media_model -> selfmedia
media_model -> integrations.feishu
media_vault -> openclaw-tag-router
integrations -> selfmedia workflow orchestration
business layers -> runtime
data/downloads/outputs -> imported Python source
openclaw-agents/media -> independent selfmedia business workflows
```

## OpenClaw Runtime Copies

`openclaw-tag-router` appears in more than one location because OpenClaw separates source, deployment, and runtime data.

Only this path is editable source:

```text
openclaw-tag-router/
```

The configured OpenClaw extension directory is a deployed copy and must match the source after deployment:

```text
<openclaw-extension-root>/openclaw-tag-router/
```

The configured OpenClaw workspace directory stores runtime data:

```text
<openclaw-workspace-root>/openclaw-tag-router/
```

The single-source guard must compare source and deployed copy. Runtime workspace data is not compared to source because it stores messages, archives, logs, and temporary runtime state.

The canonical deployment command is:

```bash
python3 runtime/maintenance/deploy/deploy_openclaw_runtime.py
```

It performs the full source-to-runtime projection:

```text
openclaw-tag-router/
  -> rsync --delete
  -> configured OpenClaw extension directory
  -> install deploy/systemd/user units
  -> generate:data / validate:data / npm run build
  -> configured published Bot Center directory
  -> guard source/active drift, Bot Center parity, and cron/systemd scheduler authority
```

Do not use the configured extension directory as a long-lived edit location. If an emergency hotfix is applied there, immediately backport it to `openclaw-tag-router/` and run the deployment command so the guard can prove the copies converged again.

## OpenClaw Frontend Projection

Bot Center is a frontend projection of the active tag-router capability registry, not a second capability registry.

```text
active tag-router capability registry
  -> openclaw-bot-center/scripts/generateDashboardData.py
  -> openclaw-bot-center/public/data/openclaw-bot-center.generated.json
  -> npm run build
  -> openclaw-bot-center/dist/
  -> configured published Bot Center directory
```

The published JSON must match both local `public/` and `dist/`; otherwise users may see a stale ability page even when the runtime route has changed.

## OpenClaw Scheduler Authority

Daily journal and weekly self-model scheduling are owned by systemd user timers:

```text
openclaw-daily-journal-template.timer     -> daily 22:00
openclaw-weekly-self-model-summary.timer  -> Sunday 23:59
```

OpenClaw cron may continue to own unrelated scheduled jobs, but it must not retain competing Daily journal or weekly self-model jobs. The runtime smoke must read both systemd and `openclaw cron list --json`.

Media account polling is installed as a systemd user timer by `runtime/cli/selfmedia.py install-cron`. Its service directly invokes `daily-poll` with the configured tenant and Feishu report target; it does not route the collection through an OpenClaw agent session.

## OpenClaw Media Agent Boundary

The repository-owned selfmedia entrypoint is:

```text
runtime/cli/selfmedia.py
```

Deployment-specific wrappers may call this entrypoint, but they are not a second source of business behavior. Generated media-agent directories are runtime product directories, not source authority.

## Media Vault Naming

The repeated `media_vault` name is intentional and only legal in these two roles:

```text
media_vault/       # code package
data/media_vault/  # artifact storage root
```

Any new `media_vault` path outside those roles needs a documented owner and a guard update before it is introduced.

## Runtime Artifact Rules

- Long JSON, evidence bundles, screenshots, and generated variants go under `data/media_vault/` through `MediaVault` where practical.
- Feishu visible fields receive summaries, stable IDs, links, and status fields.
- `data/`, `downloads/`, `outputs/`, configured OpenClaw workspace data, and media-agent temporary files are not code ownership locations.
- Imported numbered-Part artifacts may remain under `data/media_vault/numbered_part_archive/`, but no runtime command may call those directories.

## Required Guards

`scripts/quality/check_openclaw_single_source_contract.py` must enforce:

- this document exists and declares `docs/architecture.md` as the directory-responsibility SSOT;
- README points to this document instead of redefining source/deployment/workspace roles;
- repository-owned calls use `runtime/cli/selfmedia.py` as the selfmedia entrypoint;
- tag-router source and deployed copy are byte-identical except ignored cache files;
- tag-router source, active copy, and installed journal systemd units are identical for the Daily journal timers;
- Bot Center `public/`, `dist/`, and `/var/www/openclaw/bots/` generated JSON are identical;
- the deployment script performs source-to-active sync, systemd unit install, Bot Center generation/build/publish, published-data parity check, and OpenClaw cron double-scheduling check;
- media Bot AGENTS does not document removed selfmedia script paths or numbered workflow framing;
- `media_vault/` and `data/media_vault/` are treated as code package and data root respectively.

`scripts/qa/openclaw_single_source_runtime_smoke.py` must call the static guard before runtime checks, then verify user services, journal timers, OpenClaw cron scheduler authority, gateway status, runtime config, and the media selfmedia thin entrypoint.
