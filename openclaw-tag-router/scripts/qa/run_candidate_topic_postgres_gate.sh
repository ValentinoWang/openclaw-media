#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 postgresql://.../b6_candidate_topic_test_*" >&2
  exit 2
fi

database_url=$1
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/tests/fixtures/b6_candidate_topic_seed.sql"
psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/tests/fixtures/b6_candidate_topic_missing_id.sql"
psql -X -v ON_ERROR_STOP=1 "$database_url" -c "UPDATE media_product.decision_traces SET canonical_data = canonical_data - '创作运行ID' WHERE public_id = 'trace_01_001'"
if psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/openclaw_app/migrations/canonical/038_candidate_topics.sql"; then
  echo "missing candidate identity did not block the migration" >&2
  exit 1
fi
rolled_back=$(psql -X -At "$database_url" -c "SELECT to_regclass('media_product.candidate_topics') IS NULL")
if [[ "$rolled_back" != "t" ]]; then
  echo "failed migration did not roll back atomically" >&2
  exit 1
fi
snapshot_absent=$(psql -X -At "$database_url" -c "SELECT to_regclass('media_product.b6_candidate_topics_rollback_snapshot') IS NULL")
if [[ "$snapshot_absent" != "t" ]]; then
  echo "failed migration left a rollback snapshot behind" >&2
  exit 1
fi

psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/tests/fixtures/b6_candidate_topic_seed.sql"
before_trace_hash=$(psql -X -At "$database_url" -c "SELECT md5(COALESCE(jsonb_agg(row_data ORDER BY id)::text, '[]')) FROM (SELECT id, to_jsonb(decision_traces) AS row_data FROM media_product.decision_traces) AS source")
before_run_hash=$(psql -X -At "$database_url" -c "SELECT md5(COALESCE(jsonb_agg(row_data ORDER BY id)::text, '[]')) FROM (SELECT id, to_jsonb(creation_runs) AS row_data FROM media_product.creation_runs) AS source")
psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/openclaw_app/migrations/canonical/038_candidate_topics.sql"
before_rerun_topic_hash=$(psql -X -At "$database_url" -c "SELECT md5(COALESCE(jsonb_agg(row_data ORDER BY id)::text, '[]')) FROM (SELECT id, to_jsonb(candidate_topics) AS row_data FROM media_product.candidate_topics) AS source")
psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/openclaw_app/migrations/canonical/038_candidate_topics.sql"
after_rerun_topic_hash=$(psql -X -At "$database_url" -c "SELECT md5(COALESCE(jsonb_agg(row_data ORDER BY id)::text, '[]')) FROM (SELECT id, to_jsonb(candidate_topics) AS row_data FROM media_product.candidate_topics) AS source")
if [[ "$before_rerun_topic_hash" != "$after_rerun_topic_hash" ]]; then
  echo "rerunning the migration changed candidate topic rows" >&2
  exit 1
fi
psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/tests/fixtures/b6_candidate_topic_assertions.sql"

psql -X -v ON_ERROR_STOP=1 "$database_url" -c "INSERT INTO media_product.creation_runs (tenant_id, public_id, source_version, canonical_data) VALUES ('00000000-0000-0000-0000-000000000001', 'post_migration_insert', 'fixture-probe', '{}'::jsonb)"
if psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/openclaw_app/migrations/rollback/038_candidate_topics.rollback.sql"; then
  echo "rollback accepted a post-migration insert" >&2
  exit 1
fi

psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/tests/fixtures/b6_candidate_topic_seed.sql"
psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/openclaw_app/migrations/canonical/038_candidate_topics.sql"
psql -X -v ON_ERROR_STOP=1 "$database_url" -c "UPDATE media_product.decision_traces SET revision = revision + 1 WHERE public_id = 'trace_01_001'"
if psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/openclaw_app/migrations/rollback/038_candidate_topics.rollback.sql"; then
  echo "rollback accepted a post-migration update" >&2
  exit 1
fi

psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/tests/fixtures/b6_candidate_topic_seed.sql"
before_trace_hash=$(psql -X -At "$database_url" -c "SELECT md5(COALESCE(jsonb_agg(row_data ORDER BY id)::text, '[]')) FROM (SELECT id, to_jsonb(decision_traces) AS row_data FROM media_product.decision_traces) AS source")
before_run_hash=$(psql -X -At "$database_url" -c "SELECT md5(COALESCE(jsonb_agg(row_data ORDER BY id)::text, '[]')) FROM (SELECT id, to_jsonb(creation_runs) AS row_data FROM media_product.creation_runs) AS source")
psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/openclaw_app/migrations/canonical/038_candidate_topics.sql"
psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/openclaw_app/migrations/rollback/038_candidate_topics.rollback.sql"

after_trace_hash=$(psql -X -At "$database_url" -c "SELECT md5(COALESCE(jsonb_agg(row_data ORDER BY id)::text, '[]')) FROM (SELECT id, to_jsonb(decision_traces) AS row_data FROM media_product.decision_traces) AS source")
after_run_hash=$(psql -X -At "$database_url" -c "SELECT md5(COALESCE(jsonb_agg(row_data ORDER BY id)::text, '[]')) FROM (SELECT id, to_jsonb(creation_runs) AS row_data FROM media_product.creation_runs) AS source")
if [[ "$before_trace_hash" != "$after_trace_hash" || "$before_run_hash" != "$after_run_hash" ]]; then
  echo "rollback did not restore exact source snapshots" >&2
  exit 1
fi
remaining=$(psql -X -At "$database_url" -c "SELECT count(*) FROM media_product.decision_traces")
if [[ "$remaining" != "61" ]]; then
  echo "rollback changed decision trace count: $remaining" >&2
  exit 1
fi
columns_absent=$(psql -X -At "$database_url" -c "SELECT NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'media_product' AND table_name = 'decision_traces' AND column_name IN ('candidate_id', 'candidate_topic_public_id', 'decision_sequence')) AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'media_product' AND table_name = 'creation_runs' AND column_name IN ('candidate_id', 'candidate_topic_public_id'))")
if [[ "$columns_absent" != "t" ]]; then
  echo "rollback left B6 columns behind" >&2
  exit 1
fi

psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/openclaw_app/migrations/canonical/038_candidate_topics.sql"
psql -X -v ON_ERROR_STOP=1 "$database_url" -f "$repo_root/tests/fixtures/b6_candidate_topic_assertions.sql"
echo "B6 candidate topic PostgreSQL gate: pass"
