# SelfMedia Tools Architecture

This document is the directory-responsibility SSOT for `/home/ubuntu/selfmedia-tools`.
`README.md` is only an entry page. Bot-local `AGENTS.md` files may point here, but must not redefine these boundaries.

## Core Rule

Every selfmedia capability has exactly one code owner, one runtime entrypoint, and one artifact root.

```text
OpenClaw media Bot
  -> openclaw-agents/media/scripts/selfmedia.py
  -> selfmedia-tools/runtime/cli/selfmedia.py
  -> selfmedia/*
  -> media_model / media_vault / integrations
```

The following paths are different roles, not competing implementations:

```text
selfmedia-tools/media_vault/
  role: code package
  owns: MediaVault API, media:// URI, manifest validation, artifact write helpers
  may contain: Python source and tests
  must not contain: run artifacts, downloaded media, CreationRun payloads

selfmedia-tools/data/media_vault/
  role: canonical artifact storage root
  owns: CreationRun, deconstruction, creator profile, business, review, style_polish artifacts
  may contain: JSON, Markdown, screenshots, media files, manifests
  must not contain: Python business logic or alternative writers

selfmedia-tools/openclaw-tag-router/
  role: source SSOT for the OpenClaw tag-router adapter
  owns: tag routing code, capability definitions, adapter tests
  must be edited before deployment

.openclaw/extensions/openclaw-tag-router/
  role: deployed runtime copy
  owns: the files loaded by OpenClaw at runtime
  must match: selfmedia-tools/openclaw-tag-router/
  must not be used as the source edit location

.openclaw/workspace/openclaw-tag-router/
  role: runtime workspace data
  owns: inbox, outbox, archive, logs, tmp, content_flow runtime files
  must not contain: source authority for tag-router behavior

openclaw-agents/media/
  role: media Bot local workspace
  owns: Bot instructions, thin selfmedia entrypoint, generated files, attachment manifests, tmp analysis
  must not contain: independent selfmedia business workflows
```

## Canonical Directory Tree

```text
selfmedia-tools/
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
|   |-- media_memory/                 # account profile and review memory
|   `-- media_vault/                  # canonical artifact storage root
|-- tests/
|-- downloads/                        # local download cache
`-- outputs/                          # local temporary output and backups
```

## Capability Owners

| Capability | Code owner | Runtime entrypoint | Artifact owner |
|---|---|---|---|
| Content ingest and media analysis | `selfmedia/ingest/content_flow/` | `runtime/cli/selfmedia.py run ingest` | `data/media_vault/source_assets/` or local download cache |
| Music resource extraction | `selfmedia/ingest/music_resource/` | module or package script under that directory | caller-selected output or `data/media_vault/source_assets/` |
| Field health diagnostics | `selfmedia/ingest/diagnostics/field_health.py` | direct module call | `data/media_vault/field_health_runs/` |
| Viral deconstruction | `selfmedia/deconstruct/viral_content/` | `runtime/cli/selfmedia.py run deconstruct` | `data/media_vault/deconstructions/` |
| Creation workflows | `selfmedia/creation/` | `runtime/cli/selfmedia.py` creation commands | `data/media_vault/creation_runs/` |
| Data review | `selfmedia/review/` | `runtime/cli/selfmedia.py data-review` | `data/media_vault/data_review_runs/` |
| Creator profiles | `selfmedia/creator_profiles/` | tag-router adapter or public service call | `data/media_vault/creator_profiles/` |
| Business ID and quotes | `selfmedia/business/` | `python3 -m selfmedia.business.id_business` | `data/media_vault/business/` |
| Style polish | `selfmedia/style/` | `openclaw_app/router/style_polish.py` or public service call | `data/media_vault/style_polish_runs/` |
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
/home/ubuntu/selfmedia-tools/openclaw-tag-router/
```

This path is a deployed copy and must match the source after deployment:

```text
/home/ubuntu/.openclaw/extensions/openclaw-tag-router/
```

This path is runtime workspace data:

```text
/home/ubuntu/.openclaw/workspace/openclaw-tag-router/
```

The single-source guard must compare source and deployed copy. Runtime workspace data is not compared to source because it stores messages, archives, logs, and temporary runtime state.

## OpenClaw Media Agent Boundary

`/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py` is the only selfmedia script entrypoint inside `openclaw-agents/media/scripts/`.
It must remain a thin subprocess wrapper around:

```text
/home/ubuntu/selfmedia-tools/runtime/cli/selfmedia.py
```

Other media-specific commands must live in `selfmedia-tools` as package modules or runtime commands. `openclaw-agents/media/generated/`, `tmp/`, `tmp_analysis/`, `analysis_frames/`, and `attachment_manifests/` are runtime product directories.

## Media Vault Naming

The repeated `media_vault` name is intentional and only legal in these two roles:

```text
selfmedia-tools/media_vault/       # code package
selfmedia-tools/data/media_vault/  # artifact storage root
```

Any new `media_vault` path outside those roles needs a documented owner and a guard update before it is introduced.

## Runtime Artifact Rules

- Long JSON, evidence bundles, screenshots, and generated variants go under `data/media_vault/` through `MediaVault` where practical.
- Feishu visible fields receive summaries, stable IDs, links, and status fields.
- `data/`, `downloads/`, `outputs/`, `.openclaw/workspace/*`, and `openclaw-agents/media/tmp*` are not code ownership locations.
- Imported numbered-Part artifacts may remain under `data/media_vault/numbered_part_archive/`, but no runtime command may call those directories.

## Required Guards

`scripts/quality/check_openclaw_single_source_contract.py` must enforce:

- this document exists and declares `docs/architecture.md` as the directory-responsibility SSOT;
- README points to this document instead of redefining source/deployment/workspace roles;
- `openclaw-agents/media/scripts/` contains only the thin `selfmedia.py` entrypoint;
- `openclaw-agents/media/scripts/selfmedia.py` points to `selfmedia-tools/runtime/cli/selfmedia.py`;
- tag-router source and deployed copy are byte-identical except ignored cache files;
- media Bot AGENTS does not document removed selfmedia script paths or numbered workflow framing;
- `media_vault/` and `data/media_vault/` are treated as code package and data root respectively.

`scripts/qa/openclaw_single_source_runtime_smoke.py` must call the static guard before runtime checks.
