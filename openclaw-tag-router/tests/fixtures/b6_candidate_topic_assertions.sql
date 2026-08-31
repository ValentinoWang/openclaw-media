\set ON_ERROR_STOP on

DO $$
DECLARE
    topic_count INTEGER;
    trace_count INTEGER;
    orphan_count INTEGER;
    linked_run_count INTEGER;
    invalid_identity_count INTEGER;
    invalid_sequence_count INTEGER;
    invalid_sequence_constraint BOOLEAN;
    c01_unique_constraint BOOLEAN;
    snapshot_complete BOOLEAN;
BEGIN
    SELECT count(*) INTO topic_count FROM media_product.candidate_topics;
    SELECT count(*) INTO trace_count FROM media_product.decision_traces;
    SELECT count(*) INTO orphan_count
      FROM media_product.decision_traces AS trace
      LEFT JOIN media_product.candidate_topics AS topic
        ON topic.tenant_id = trace.tenant_id
       AND topic.public_id = trace.candidate_topic_public_id
     WHERE topic.id IS NULL;
    SELECT count(*) INTO linked_run_count
      FROM media_product.creation_runs
     WHERE candidate_id IS NOT NULL;

    SELECT count(*) INTO invalid_identity_count
      FROM media_product.candidate_topics AS topic
      JOIN media_product.creation_runs AS run
        ON run.tenant_id = topic.tenant_id
       AND run.candidate_id = topic.candidate_id
     WHERE topic.candidate_id <> 'legacy:' || run.public_id
        OR topic.public_id <> topic.candidate_id;

    SELECT count(*) INTO invalid_sequence_count
      FROM (
          SELECT
              trace.id,
              trace.decision_sequence,
              row_number() OVER (
                  PARTITION BY trace.tenant_id, trace.candidate_id
                  ORDER BY trace.created_at, trace.public_id
              ) AS expected_sequence
            FROM media_product.decision_traces AS trace
      ) AS ordered
     WHERE ordered.decision_sequence <> ordered.expected_sequence;

    SELECT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'decision_traces_candidate_sequence_unique'
           AND conrelid = 'media_product.decision_traces'::regclass
           AND contype = 'u'
    ) INTO invalid_sequence_constraint;

    SELECT EXISTS (
        SELECT 1
          FROM pg_indexes
         WHERE schemaname = 'media_product'
           AND tablename = 'creation_runs'
           AND indexname = 'creation_runs_candidate_id_unique'
           AND indexdef LIKE 'CREATE UNIQUE INDEX%'
           AND indexdef LIKE '%(tenant_id, candidate_id)%'
    ) INTO c01_unique_constraint;

    SELECT EXISTS (
        SELECT 1
          FROM media_product.b6_candidate_topics_rollback_snapshot
         WHERE snapshot_name = 'candidate_topics'
           AND source_decision_hash IS NOT NULL
           AND source_creation_hash IS NOT NULL
           AND target_decision_hash IS NOT NULL
           AND target_creation_hash IS NOT NULL
           AND target_topic_hash IS NOT NULL
    ) INTO snapshot_complete;

    IF topic_count <> 7 OR trace_count <> 61 OR orphan_count <> 0 OR linked_run_count <> 7
       OR invalid_identity_count <> 0 OR invalid_sequence_count <> 0
       OR NOT invalid_sequence_constraint OR NOT c01_unique_constraint
       OR NOT snapshot_complete THEN
        RAISE EXCEPTION 'B6_CARDINALITY_OR_CONTRACT_FAILED topics=% traces=% orphans=% linked_runs=% invalid_identity=% invalid_sequence=% sequence_constraint=% c01_unique=% snapshot=%',
            topic_count, trace_count, orphan_count, linked_run_count,
            invalid_identity_count, invalid_sequence_count,
            invalid_sequence_constraint, c01_unique_constraint, snapshot_complete;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'decision_traces_candidate_topic_fk'
           AND confdeltype = 'r'
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'creation_runs_candidate_topic_fk'
           AND confdeltype = 'r'
    ) THEN
        RAISE EXCEPTION 'B6_RESTRICT_FOREIGN_KEY_MISSING';
    END IF;
END;
$$;

DO $$
BEGIN
    BEGIN
        INSERT INTO media_product.decision_traces (
            tenant_id,
            public_id,
            source_version,
            decision_sequence,
            candidate_id,
            candidate_topic_public_id,
            canonical_data
        ) VALUES (
            '00000000-0000-0000-0000-000000000001',
            'duplicate_sequence_probe',
            'fixture-probe',
            1,
            'legacy:run_01_0001',
            'legacy:run_01_0001',
            jsonb_build_object('创作运行ID', 'run_01_0001')
        );
        RAISE EXCEPTION 'B6_DUPLICATE_DECISION_SEQUENCE_UNEXPECTEDLY_SUCCEEDED';
    EXCEPTION
        WHEN unique_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO media_product.decision_traces (
            tenant_id,
            public_id,
            source_version,
            decision_sequence,
            candidate_id,
            candidate_topic_public_id,
            canonical_data
        ) VALUES (
            '00000000-0000-0000-0000-000000000001',
            'invalid_sequence_probe',
            'fixture-probe',
            0,
            'legacy:run_01_0001',
            'legacy:run_01_0001',
            jsonb_build_object('创作运行ID', 'run_01_0001')
        );
        RAISE EXCEPTION 'B6_NON_POSITIVE_SEQUENCE_UNEXPECTEDLY_SUCCEEDED';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO media_product.creation_runs (
            tenant_id,
            public_id,
            source_version,
            candidate_id,
            candidate_topic_public_id,
            canonical_data
        ) VALUES (
            '00000000-0000-0000-0000-000000000001',
            'duplicate_c01_probe',
            'fixture-probe',
            'legacy:run_01_0001',
            'legacy:run_01_0001',
            jsonb_build_object('创作运行ID', 'duplicate_c01_probe')
        );
        RAISE EXCEPTION 'B6_DUPLICATE_C01_UNEXPECTEDLY_SUCCEEDED';
    EXCEPTION
        WHEN unique_violation THEN
            NULL;
    END;
END;
$$;

DO $$
BEGIN
    BEGIN
        DELETE FROM media_product.candidate_topics
         WHERE tenant_id = '00000000-0000-0000-0000-000000000001'
           AND candidate_id = 'legacy:run_01_0001';
        RAISE EXCEPTION 'B6_RESTRICT_DELETE_UNEXPECTEDLY_SUCCEEDED';
    EXCEPTION
        WHEN foreign_key_violation OR restrict_violation THEN
            NULL;
    END;
END;
$$;
