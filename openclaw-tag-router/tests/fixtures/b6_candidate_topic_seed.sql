\set ON_ERROR_STOP on

DO $$
BEGIN
    IF current_database() !~ '^b6_candidate_topic_test_' THEN
        RAISE EXCEPTION 'fixture requires an isolated b6_candidate_topic_test_* database';
    END IF;
END;
$$;

DROP SCHEMA IF EXISTS media_product CASCADE;
DROP SCHEMA IF EXISTS openclaw_account CASCADE;
CREATE SCHEMA openclaw_account;
CREATE SCHEMA media_product;

CREATE TABLE openclaw_account.tenants (
    id UUID PRIMARY KEY
);

INSERT INTO openclaw_account.tenants (id)
VALUES ('00000000-0000-0000-0000-000000000001');

CREATE OR REPLACE FUNCTION media_product.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TABLE media_product.decision_traces (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    canonical_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_id)
);

CREATE TABLE media_product.creation_runs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    canonical_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_id)
);

WITH topic_sizes(candidate_no, event_count) AS (
    VALUES (1, 9), (2, 9), (3, 9), (4, 9), (5, 9), (6, 8), (7, 8)
), events AS (
    SELECT candidate_no, generate_series(1, event_count) AS event_no
      FROM topic_sizes
)
INSERT INTO media_product.decision_traces (
    tenant_id, public_id, source_version, canonical_data, created_at, updated_at
)
SELECT
    '00000000-0000-0000-0000-000000000001',
    format('trace_%s_%s', lpad(candidate_no::text, 2, '0'), lpad(event_no::text, 3, '0')),
    'fixture-v1',
    jsonb_build_object(
        'candidate_id', format('legacy_wrong_%s', lpad(candidate_no::text, 2, '0')),
        '创作运行ID', format('run_%s_0001', lpad(candidate_no::text, 2, '0')),
        'candidate_title', CASE WHEN candidate_no IN (1, 2) THEN '同名选题' ELSE format('候选 %s', candidate_no) END,
        'candidate_type', CASE WHEN candidate_no % 2 = 0 THEN 'research' ELSE 'activity' END,
        'event_no', event_no
    ),
    TIMESTAMPTZ '2026-08-09 00:00:00+00' + (candidate_no * 100 + event_no) * INTERVAL '1 second',
    TIMESTAMPTZ '2026-08-09 00:00:00+00' + (candidate_no * 100 + event_no) * INTERVAL '1 second'
  FROM events;

INSERT INTO media_product.creation_runs (
    tenant_id, public_id, source_version, canonical_data
)
SELECT
    '00000000-0000-0000-0000-000000000001',
    format('run_%s_0001', lpad(candidate_no::text, 2, '0')),
    'fixture-v1',
    jsonb_build_object(
        'candidate_id', format('legacy_wrong_%s', lpad(candidate_no::text, 2, '0')),
        '创作运行ID', format('run_%s_0001', lpad(candidate_no::text, 2, '0'))
    )
  FROM generate_series(1, 7) AS candidate_no;
