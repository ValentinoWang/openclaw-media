DO $$
DECLARE
    snapshot_row media_product.b6_candidate_topics_rollback_snapshot%ROWTYPE;
    current_decision_hash TEXT;
    current_creation_hash TEXT;
    current_topic_hash TEXT;
BEGIN
    SELECT *
      INTO snapshot_row
      FROM media_product.b6_candidate_topics_rollback_snapshot
     WHERE snapshot_name = 'candidate_topics';
    IF NOT FOUND
       OR snapshot_row.target_decision_hash IS NULL
       OR snapshot_row.target_creation_hash IS NULL
       OR snapshot_row.target_topic_hash IS NULL THEN
        RAISE EXCEPTION 'B6_BLOCKED_ROLLBACK_SNAPSHOT_MISSING';
    END IF;

    SELECT md5(COALESCE(
        (SELECT jsonb_agg(row_data ORDER BY id)::text
           FROM (
               SELECT id, to_jsonb(decision_traces) AS row_data
                 FROM media_product.decision_traces
           ) AS rows
        ),
        '[]'
    )) INTO current_decision_hash;
    SELECT md5(COALESCE(
        (SELECT jsonb_agg(row_data ORDER BY id)::text
           FROM (
               SELECT id, to_jsonb(creation_runs) AS row_data
                 FROM media_product.creation_runs
           ) AS rows
        ),
        '[]'
    )) INTO current_creation_hash;
    SELECT md5(COALESCE(
        (SELECT jsonb_agg(row_data ORDER BY id)::text
           FROM (
               SELECT id, to_jsonb(candidate_topics) AS row_data
                 FROM media_product.candidate_topics
           ) AS rows
        ),
        '[]'
    )) INTO current_topic_hash;

    IF current_decision_hash <> snapshot_row.target_decision_hash
       OR current_creation_hash <> snapshot_row.target_creation_hash
       OR current_topic_hash <> snapshot_row.target_topic_hash THEN
        RAISE EXCEPTION 'B6_BLOCKED_ROLLBACK_POST_MIGRATION_WRITE';
    END IF;
END;
$$;

ALTER TABLE media_product.creation_runs
    DROP CONSTRAINT IF EXISTS creation_runs_candidate_topic_fk;
ALTER TABLE media_product.decision_traces
    DROP CONSTRAINT IF EXISTS decision_traces_candidate_topic_fk;

DROP INDEX IF EXISTS media_product.creation_runs_candidate_topic_idx;
DROP INDEX IF EXISTS media_product.decision_traces_candidate_topic_idx;
DROP INDEX IF EXISTS media_product.creation_runs_candidate_id_unique;
DROP INDEX IF EXISTS media_product.candidate_topics_candidate_id_unique;

ALTER TABLE media_product.creation_runs
    DROP COLUMN IF EXISTS candidate_topic_public_id;
ALTER TABLE media_product.creation_runs
    DROP COLUMN IF EXISTS candidate_id;
ALTER TABLE media_product.decision_traces
    DROP COLUMN IF EXISTS candidate_topic_public_id;
ALTER TABLE media_product.decision_traces
    DROP COLUMN IF EXISTS decision_sequence;
ALTER TABLE media_product.decision_traces
    DROP COLUMN IF EXISTS candidate_id;

DROP TABLE IF EXISTS media_product.candidate_topics;

DO $$
DECLARE
    snapshot_row media_product.b6_candidate_topics_rollback_snapshot%ROWTYPE;
    restored_decision_hash TEXT;
    restored_creation_hash TEXT;
BEGIN
    SELECT *
      INTO snapshot_row
      FROM media_product.b6_candidate_topics_rollback_snapshot
     WHERE snapshot_name = 'candidate_topics';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'B6_BLOCKED_ROLLBACK_SNAPSHOT_MISSING';
    END IF;
    SELECT md5(COALESCE(
        (SELECT jsonb_agg(row_data ORDER BY id)::text
           FROM (
               SELECT id, to_jsonb(decision_traces) AS row_data
                 FROM media_product.decision_traces
           ) AS rows
        ),
        '[]'
    )) INTO restored_decision_hash;
    SELECT md5(COALESCE(
        (SELECT jsonb_agg(row_data ORDER BY id)::text
           FROM (
               SELECT id, to_jsonb(creation_runs) AS row_data
                 FROM media_product.creation_runs
           ) AS rows
        ),
        '[]'
    )) INTO restored_creation_hash;
    IF restored_decision_hash <> snapshot_row.source_decision_hash
       OR restored_creation_hash <> snapshot_row.source_creation_hash THEN
        RAISE EXCEPTION 'B6_BLOCKED_ROLLBACK_SOURCE_SNAPSHOT_MISMATCH';
    END IF;
END;
$$;

DROP TABLE media_product.b6_candidate_topics_rollback_snapshot;
