-- The snapshot is created in the same transaction as the migration. A failed
-- preflight therefore leaves neither migration metadata nor partial columns.
CREATE TABLE IF NOT EXISTS media_product.b6_candidate_topics_rollback_snapshot (
    snapshot_name TEXT PRIMARY KEY,
    source_decision_hash TEXT NOT NULL,
    source_creation_hash TEXT NOT NULL,
    target_decision_hash TEXT,
    target_creation_hash TEXT,
    target_topic_hash TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO media_product.b6_candidate_topics_rollback_snapshot (
    snapshot_name,
    source_decision_hash,
    source_creation_hash
)
SELECT
    'candidate_topics',
    md5(COALESCE(
        (SELECT jsonb_agg(row_data ORDER BY id)::text
           FROM (
               SELECT id, to_jsonb(decision_traces) AS row_data
                 FROM media_product.decision_traces
           ) AS rows
        ),
        '[]'
    )),
    md5(COALESCE(
        (SELECT jsonb_agg(row_data ORDER BY id)::text
           FROM (
               SELECT id, to_jsonb(creation_runs) AS row_data
                 FROM media_product.creation_runs
           ) AS rows
        ),
        '[]'
    ))
WHERE NOT EXISTS (
    SELECT 1
      FROM media_product.b6_candidate_topics_rollback_snapshot
     WHERE snapshot_name = 'candidate_topics'
)
ON CONFLICT (snapshot_name) DO NOTHING;

CREATE TABLE IF NOT EXISTS media_product.candidate_topics (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_id TEXT NOT NULL CHECK (length(btrim(public_id)) > 0),
    candidate_id TEXT,
    source_version TEXT NOT NULL CHECK (length(btrim(source_version)) > 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    canonical_data JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(canonical_data) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_id)
);

ALTER TABLE media_product.candidate_topics
    ADD COLUMN IF NOT EXISTS candidate_id TEXT;

DROP TRIGGER IF EXISTS candidate_topics_touch_updated_at ON media_product.candidate_topics;
CREATE TRIGGER candidate_topics_touch_updated_at
    BEFORE UPDATE ON media_product.candidate_topics
    FOR EACH ROW EXECUTE FUNCTION media_product.touch_updated_at();

ALTER TABLE media_product.decision_traces
    ADD COLUMN IF NOT EXISTS candidate_id TEXT;
ALTER TABLE media_product.decision_traces
    ADD COLUMN IF NOT EXISTS decision_sequence INTEGER;
ALTER TABLE media_product.decision_traces
    ADD COLUMN IF NOT EXISTS candidate_topic_public_id TEXT;

ALTER TABLE media_product.creation_runs
    ADD COLUMN IF NOT EXISTS candidate_id TEXT;
ALTER TABLE media_product.creation_runs
    ADD COLUMN IF NOT EXISTS candidate_topic_public_id TEXT;

-- Identity may only come from the physical run field. The legacy candidate
-- fields are deliberately absent from these expressions.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM media_product.decision_traces AS trace
         WHERE NOT EXISTS (
             SELECT 1
               FROM unnest(ARRAY[
                   NULLIF(btrim(trace.canonical_data->>'creation_run_id'), ''),
                   NULLIF(btrim(trace.canonical_data->>'creationRunId'), ''),
                   NULLIF(btrim(trace.canonical_data->>'创作运行ID'), ''),
                   NULLIF(btrim(trace.canonical_data->'source_field_values'->>'creation_run_id'), ''),
                   NULLIF(btrim(trace.canonical_data->'source_field_values'->>'creationRunId'), ''),
                   NULLIF(btrim(trace.canonical_data->'source_field_values'->>'创作运行ID'), '')
               ]) AS value
              WHERE value IS NOT NULL
         )
    ) THEN
        RAISE EXCEPTION 'B6_BLOCKED_MISSING_CREATION_RUN_ID';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM media_product.creation_runs AS run
         WHERE NOT EXISTS (
             SELECT 1
               FROM unnest(ARRAY[
                   NULLIF(btrim(run.canonical_data->>'creation_run_id'), ''),
                   NULLIF(btrim(run.canonical_data->>'creationRunId'), ''),
                   NULLIF(btrim(run.canonical_data->>'创作运行ID'), ''),
                   NULLIF(btrim(run.canonical_data->'source_field_values'->>'creation_run_id'), ''),
                   NULLIF(btrim(run.canonical_data->'source_field_values'->>'creationRunId'), ''),
                   NULLIF(btrim(run.canonical_data->'source_field_values'->>'创作运行ID'), '')
               ]) AS value
              WHERE value IS NOT NULL
         )
    ) THEN
        RAISE EXCEPTION 'B6_BLOCKED_MISSING_CREATION_RUN_ID';
    END IF;

    IF EXISTS (
        SELECT trace.tenant_id, trace.public_id
          FROM media_product.decision_traces AS trace
         GROUP BY trace.tenant_id, trace.public_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'B6_BLOCKED_DUPLICATE_DECISION_TRACE_ID';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM media_product.decision_traces AS trace
         WHERE EXISTS (
             SELECT 1
               FROM unnest(ARRAY[
                   NULLIF(btrim(trace.canonical_data->>'tenant_id'), ''),
                   NULLIF(btrim(trace.canonical_data->>'tenantId'), ''),
                   NULLIF(btrim(trace.canonical_data->>'租户ID'), ''),
                   NULLIF(btrim(trace.canonical_data->'source_field_values'->>'tenant_id'), ''),
                   NULLIF(btrim(trace.canonical_data->'source_field_values'->>'tenantId'), ''),
                   NULLIF(btrim(trace.canonical_data->'source_field_values'->>'租户ID'), '')
               ]) AS value
              WHERE value IS NOT NULL AND value <> trace.tenant_id::text
         )
    ) OR EXISTS (
        SELECT 1
          FROM media_product.creation_runs AS run
         WHERE EXISTS (
             SELECT 1
               FROM unnest(ARRAY[
                   NULLIF(btrim(run.canonical_data->>'tenant_id'), ''),
                   NULLIF(btrim(run.canonical_data->>'tenantId'), ''),
                   NULLIF(btrim(run.canonical_data->>'租户ID'), ''),
                   NULLIF(btrim(run.canonical_data->'source_field_values'->>'tenant_id'), ''),
                   NULLIF(btrim(run.canonical_data->'source_field_values'->>'tenantId'), ''),
                   NULLIF(btrim(run.canonical_data->'source_field_values'->>'租户ID'), '')
               ]) AS value
              WHERE value IS NOT NULL AND value <> run.tenant_id::text
         )
    ) THEN
        RAISE EXCEPTION 'B6_BLOCKED_TENANT_CONFLICT';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM (
              SELECT trace.tenant_id,
                     COALESCE(
                         NULLIF(btrim(trace.canonical_data->>'creation_run_id'), ''),
                         NULLIF(btrim(trace.canonical_data->>'creationRunId'), ''),
                         NULLIF(btrim(trace.canonical_data->>'创作运行ID'), ''),
                         NULLIF(btrim(trace.canonical_data->'source_field_values'->>'creation_run_id'), ''),
                         NULLIF(btrim(trace.canonical_data->'source_field_values'->>'creationRunId'), ''),
                         NULLIF(btrim(trace.canonical_data->'source_field_values'->>'创作运行ID'), '')
                     ) AS run_id
                FROM media_product.decision_traces AS trace
          ) AS r02
          LEFT JOIN (
              SELECT run.tenant_id,
                     COALESCE(
                         NULLIF(btrim(run.canonical_data->>'creation_run_id'), ''),
                         NULLIF(btrim(run.canonical_data->>'creationRunId'), ''),
                         NULLIF(btrim(run.canonical_data->>'创作运行ID'), ''),
                         NULLIF(btrim(run.canonical_data->'source_field_values'->>'creation_run_id'), ''),
                         NULLIF(btrim(run.canonical_data->'source_field_values'->>'creationRunId'), ''),
                         NULLIF(btrim(run.canonical_data->'source_field_values'->>'创作运行ID'), '')
                     ) AS run_id,
                     count(*) OVER (PARTITION BY run.tenant_id, COALESCE(
                         NULLIF(btrim(run.canonical_data->>'creation_run_id'), ''),
                         NULLIF(btrim(run.canonical_data->>'creationRunId'), ''),
                         NULLIF(btrim(run.canonical_data->>'创作运行ID'), ''),
                         NULLIF(btrim(run.canonical_data->'source_field_values'->>'creation_run_id'), ''),
                         NULLIF(btrim(run.canonical_data->'source_field_values'->>'creationRunId'), ''),
                         NULLIF(btrim(run.canonical_data->'source_field_values'->>'创作运行ID'), '')
                     )) AS c01_count
                FROM media_product.creation_runs AS run
          ) AS c01
            ON c01.tenant_id = r02.tenant_id
           AND c01.run_id = r02.run_id
         WHERE c01.run_id IS NULL
            OR c01.c01_count <> 1
    ) THEN
        RAISE EXCEPTION 'B6_BLOCKED_AMBIGUOUS_C01_LINK';
    END IF;
END;
$$;

WITH runs AS (
    SELECT
        run.id,
        run.tenant_id,
        COALESCE(
            NULLIF(btrim(run.canonical_data->>'creation_run_id'), ''),
            NULLIF(btrim(run.canonical_data->>'creationRunId'), ''),
            NULLIF(btrim(run.canonical_data->>'创作运行ID'), ''),
            NULLIF(btrim(run.canonical_data->'source_field_values'->>'creation_run_id'), ''),
            NULLIF(btrim(run.canonical_data->'source_field_values'->>'creationRunId'), ''),
            NULLIF(btrim(run.canonical_data->'source_field_values'->>'创作运行ID'), '')
        ) AS creation_run_id
      FROM media_product.creation_runs AS run
), r02_keys AS (
    SELECT DISTINCT
        trace.tenant_id,
        COALESCE(
            NULLIF(btrim(trace.canonical_data->>'creation_run_id'), ''),
            NULLIF(btrim(trace.canonical_data->>'creationRunId'), ''),
            NULLIF(btrim(trace.canonical_data->>'创作运行ID'), ''),
            NULLIF(btrim(trace.canonical_data->'source_field_values'->>'creation_run_id'), ''),
            NULLIF(btrim(trace.canonical_data->'source_field_values'->>'creationRunId'), ''),
            NULLIF(btrim(trace.canonical_data->'source_field_values'->>'创作运行ID'), '')
        ) AS creation_run_id
      FROM media_product.decision_traces AS trace
)
UPDATE media_product.creation_runs AS run
   SET candidate_id = 'legacy:' || runs.creation_run_id,
       candidate_topic_public_id = CASE
           WHEN r02_keys.creation_run_id IS NOT NULL THEN 'legacy:' || runs.creation_run_id
           ELSE NULL
       END
  FROM runs
  LEFT JOIN r02_keys
    ON r02_keys.tenant_id = runs.tenant_id
   AND r02_keys.creation_run_id = runs.creation_run_id
 WHERE run.id = runs.id;

WITH traces AS (
    SELECT
        trace.id,
        trace.tenant_id,
        'legacy:' || COALESCE(
            NULLIF(btrim(trace.canonical_data->>'creation_run_id'), ''),
            NULLIF(btrim(trace.canonical_data->>'creationRunId'), ''),
            NULLIF(btrim(trace.canonical_data->>'创作运行ID'), ''),
            NULLIF(btrim(trace.canonical_data->'source_field_values'->>'creation_run_id'), ''),
            NULLIF(btrim(trace.canonical_data->'source_field_values'->>'creationRunId'), ''),
            NULLIF(btrim(trace.canonical_data->'source_field_values'->>'创作运行ID'), '')
        ) AS candidate_id
      FROM media_product.decision_traces AS trace
)
UPDATE media_product.decision_traces AS trace
   SET candidate_id = traces.candidate_id,
       candidate_topic_public_id = traces.candidate_id
  FROM traces
 WHERE trace.id = traces.id;

WITH ranked AS (
    SELECT
        trace.id,
        row_number() OVER (
            PARTITION BY trace.tenant_id, trace.candidate_id
            ORDER BY trace.created_at, trace.public_id, trace.id
        )::INTEGER AS decision_sequence
      FROM media_product.decision_traces AS trace
)
UPDATE media_product.decision_traces AS trace
   SET decision_sequence = ranked.decision_sequence
  FROM ranked
 WHERE trace.id = ranked.id;

WITH classified AS (
    SELECT
        trace.tenant_id,
        trace.candidate_id,
        trace.public_id AS decision_trace_id,
        trace.source_version,
        trace.revision,
        trace.canonical_data,
        trace.created_at,
        trace.updated_at,
        row_number() OVER (
            PARTITION BY trace.tenant_id, trace.candidate_id
            ORDER BY trace.updated_at DESC, trace.created_at DESC, trace.public_id DESC, trace.id DESC
        ) AS latest_rank
      FROM media_product.decision_traces AS trace
), grouped AS (
    SELECT
        classified.tenant_id,
        classified.candidate_id,
        max(classified.source_version) AS source_version,
        greatest(max(classified.revision), 1) AS revision,
        min(classified.created_at) AS created_at,
        max(classified.updated_at) AS updated_at,
        max(COALESCE(
            classified.canonical_data->>'candidate_title',
            classified.canonical_data->>'candidateTitle',
            classified.canonical_data->>'候选标题',
            classified.canonical_data->>'标题',
            ''
        )) AS candidate_title,
        max(COALESCE(
            classified.canonical_data->>'candidate_type',
            classified.canonical_data->>'candidateType',
            classified.canonical_data->>'候选类型',
            ''
        )) AS candidate_type,
        jsonb_agg(classified.decision_trace_id ORDER BY classified.created_at, classified.decision_trace_id) AS decision_trace_ids,
        count(*)::INTEGER AS decision_trace_count
      FROM classified
     GROUP BY classified.tenant_id, classified.candidate_id
), latest AS (
    SELECT tenant_id, candidate_id, canonical_data
      FROM classified
     WHERE latest_rank = 1
), c01 AS (
    SELECT
        run.tenant_id,
        run.candidate_id,
        run.public_id AS c01_record_id,
        COALESCE(
            NULLIF(btrim(run.canonical_data->>'creation_run_id'), ''),
            NULLIF(btrim(run.canonical_data->>'creationRunId'), ''),
            NULLIF(btrim(run.canonical_data->>'创作运行ID'), ''),
            NULLIF(btrim(run.canonical_data->'source_field_values'->>'creation_run_id'), ''),
            NULLIF(btrim(run.canonical_data->'source_field_values'->>'creationRunId'), ''),
            NULLIF(btrim(run.canonical_data->'source_field_values'->>'创作运行ID'), '')
        ) AS creation_run_id
      FROM media_product.creation_runs AS run
), c01_one AS (
    SELECT tenant_id, candidate_id, max(c01_record_id) AS c01_record_id, max(creation_run_id) AS creation_run_id
      FROM c01
     GROUP BY tenant_id, candidate_id
)
INSERT INTO media_product.candidate_topics (
    tenant_id,
    public_id,
    candidate_id,
    source_version,
    revision,
    canonical_data,
    created_at,
    updated_at
)
SELECT
    grouped.tenant_id,
    grouped.candidate_id,
    grouped.candidate_id,
    'd01-r02-split-v2',
    grouped.revision,
    latest.canonical_data || jsonb_build_object(
        'candidate_id', grouped.candidate_id,
        'creation_run_id', c01_one.creation_run_id,
        'candidate_title', grouped.candidate_title,
        'candidate_type', grouped.candidate_type,
        'decision_trace_ids', grouped.decision_trace_ids,
        'decision_trace_count', grouped.decision_trace_count,
        'c01_record_ids', jsonb_build_array(c01_one.c01_record_id),
        'c01_link_count', 1,
        'c01_exact_match_field', '创作运行ID',
        'migration_source_version', grouped.source_version
    ),
    grouped.created_at,
    grouped.updated_at
  FROM grouped
  JOIN latest USING (tenant_id, candidate_id)
  JOIN c01_one USING (tenant_id, candidate_id)
ON CONFLICT (tenant_id, public_id) DO UPDATE
SET candidate_id = EXCLUDED.candidate_id,
    source_version = EXCLUDED.source_version,
    revision = GREATEST(media_product.candidate_topics.revision, EXCLUDED.revision),
    canonical_data = EXCLUDED.canonical_data,
    created_at = LEAST(media_product.candidate_topics.created_at, EXCLUDED.created_at),
    updated_at = GREATEST(media_product.candidate_topics.updated_at, EXCLUDED.updated_at)
 WHERE media_product.candidate_topics.candidate_id IS DISTINCT FROM EXCLUDED.candidate_id
    OR media_product.candidate_topics.source_version IS DISTINCT FROM EXCLUDED.source_version
    OR media_product.candidate_topics.revision IS DISTINCT FROM GREATEST(media_product.candidate_topics.revision, EXCLUDED.revision)
    OR media_product.candidate_topics.canonical_data IS DISTINCT FROM EXCLUDED.canonical_data
    OR media_product.candidate_topics.created_at IS DISTINCT FROM LEAST(media_product.candidate_topics.created_at, EXCLUDED.created_at)
    OR media_product.candidate_topics.updated_at IS DISTINCT FROM GREATEST(media_product.candidate_topics.updated_at, EXCLUDED.updated_at);

ALTER TABLE media_product.candidate_topics
    ALTER COLUMN candidate_id SET NOT NULL;
ALTER TABLE media_product.decision_traces
    ALTER COLUMN candidate_id SET NOT NULL;
ALTER TABLE media_product.decision_traces
    ALTER COLUMN decision_sequence SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'candidate_topics_candidate_id_check'
           AND conrelid = 'media_product.candidate_topics'::regclass
    ) THEN
        ALTER TABLE media_product.candidate_topics
            ADD CONSTRAINT candidate_topics_candidate_id_check
            CHECK (candidate_id = public_id AND candidate_id LIKE 'legacy:%');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'decision_traces_candidate_id_check'
           AND conrelid = 'media_product.decision_traces'::regclass
    ) THEN
        ALTER TABLE media_product.decision_traces
            ADD CONSTRAINT decision_traces_candidate_id_check
            CHECK (candidate_id LIKE 'legacy:%');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'decision_traces_decision_sequence_check'
           AND conrelid = 'media_product.decision_traces'::regclass
    ) THEN
        ALTER TABLE media_product.decision_traces
            ADD CONSTRAINT decision_traces_decision_sequence_check
            CHECK (decision_sequence > 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'decision_traces_candidate_sequence_unique'
           AND conrelid = 'media_product.decision_traces'::regclass
    ) THEN
        ALTER TABLE media_product.decision_traces
            ADD CONSTRAINT decision_traces_candidate_sequence_unique
            UNIQUE (tenant_id, candidate_id, decision_sequence);
    END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS candidate_topics_candidate_id_unique
    ON media_product.candidate_topics (tenant_id, candidate_id);
CREATE UNIQUE INDEX IF NOT EXISTS creation_runs_candidate_id_unique
    ON media_product.creation_runs (tenant_id, candidate_id)
    WHERE candidate_id IS NOT NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM media_product.decision_traces AS trace
          LEFT JOIN media_product.candidate_topics AS topic
            ON topic.tenant_id = trace.tenant_id
           AND topic.public_id = trace.candidate_topic_public_id
         WHERE topic.id IS NULL
    ) THEN
        RAISE EXCEPTION 'B6_BLOCKED_ORPHAN_DECISION_TRACE';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM media_product.creation_runs AS run
          LEFT JOIN media_product.candidate_topics AS topic
            ON topic.tenant_id = run.tenant_id
           AND topic.public_id = run.candidate_topic_public_id
         WHERE run.candidate_topic_public_id IS NOT NULL
           AND topic.id IS NULL
    ) THEN
        RAISE EXCEPTION 'B6_BLOCKED_ORPHAN_CREATION_RUN';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM media_product.creation_runs
         WHERE candidate_id IS NOT NULL
           AND candidate_topic_public_id <> candidate_id
    ) OR EXISTS (
        SELECT 1
          FROM media_product.decision_traces
         WHERE candidate_topic_public_id <> candidate_id
    ) THEN
        RAISE EXCEPTION 'B6_BLOCKED_IDENTITY_LINK_CONFLICT';
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'decision_traces_candidate_topic_fk'
           AND conrelid = 'media_product.decision_traces'::regclass
    ) THEN
        ALTER TABLE media_product.decision_traces
            ADD CONSTRAINT decision_traces_candidate_topic_fk
            FOREIGN KEY (tenant_id, candidate_topic_public_id)
            REFERENCES media_product.candidate_topics(tenant_id, public_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'creation_runs_candidate_topic_fk'
           AND conrelid = 'media_product.creation_runs'::regclass
    ) THEN
        ALTER TABLE media_product.creation_runs
            ADD CONSTRAINT creation_runs_candidate_topic_fk
            FOREIGN KEY (tenant_id, candidate_topic_public_id)
            REFERENCES media_product.candidate_topics(tenant_id, public_id)
            ON DELETE RESTRICT;
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS decision_traces_candidate_topic_idx
    ON media_product.decision_traces (tenant_id, candidate_topic_public_id, decision_sequence, public_id);
CREATE INDEX IF NOT EXISTS creation_runs_candidate_topic_idx
    ON media_product.creation_runs (tenant_id, candidate_topic_public_id, updated_at DESC, public_id)
    WHERE candidate_topic_public_id IS NOT NULL;

UPDATE media_product.b6_candidate_topics_rollback_snapshot
   SET target_decision_hash = md5(COALESCE(
           (SELECT jsonb_agg(row_data ORDER BY id)::text
              FROM (
                  SELECT id, to_jsonb(decision_traces) AS row_data
                    FROM media_product.decision_traces
              ) AS rows
           ),
           '[]'
       )),
       target_creation_hash = md5(COALESCE(
           (SELECT jsonb_agg(row_data ORDER BY id)::text
              FROM (
                  SELECT id, to_jsonb(creation_runs) AS row_data
                    FROM media_product.creation_runs
              ) AS rows
           ),
           '[]'
       )),
       target_topic_hash = md5(COALESCE(
           (SELECT jsonb_agg(row_data ORDER BY id)::text
              FROM (
                  SELECT id, to_jsonb(candidate_topics) AS row_data
                    FROM media_product.candidate_topics
              ) AS rows
           ),
           '[]'
       ))
 WHERE snapshot_name = 'candidate_topics';
