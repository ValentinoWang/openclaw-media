BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM openclaw_account.product_mappings) THEN
        RAISE EXCEPTION 'product mappings must be empty before 009 cutover';
    END IF;
    IF EXISTS (
        SELECT 1 FROM openclaw_account.ledger_entries
        WHERE entry_type = 'admin_adjustment'
    ) THEN
        RAISE EXCEPTION 'admin_adjustment ledger entries must be absent before 009 cutover';
    END IF;
END;
$$;

ALTER TABLE openclaw_account.ledger_entries
    DROP CONSTRAINT ledger_entries_entry_type_check;

ALTER TABLE openclaw_account.ledger_entries
    ADD CONSTRAINT ledger_entries_entry_type_check
    CHECK (entry_type IN ('credit', 'reserve', 'release', 'settle', 'refund', 'affiliate', 'admin_grant'));

ALTER TABLE openclaw_account.product_mappings
    ADD COLUMN purchase_url TEXT NOT NULL,
    ADD COLUMN idempotency_key TEXT NOT NULL UNIQUE,
    ADD COLUMN created_by_user_id UUID NOT NULL REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    ADD CONSTRAINT product_mappings_purchase_url_check CHECK (
        length(purchase_url) BETWEEN 20 AND 2048
        AND purchase_url ~ '^https://([a-z0-9-]+\.)*ldxp\.cn(/[^[:space:]#]*)?$'
    ),
    ADD CONSTRAINT product_mappings_idempotency_key_check
        CHECK (length(idempotency_key) BETWEEN 1 AND 128);

CREATE OR REPLACE FUNCTION openclaw_account.enforce_product_mapping_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'product mappings are append-only' USING ERRCODE = '55000';
    END IF;
    IF OLD.status = 'active'
       AND NEW.status = 'retired'
       AND ROW(
            NEW.id, NEW.external_provider, NEW.external_product_id, NEW.plan_id,
            NEW.purchase_url, NEW.idempotency_key, NEW.created_by_user_id, NEW.created_at
       ) IS NOT DISTINCT FROM ROW(
            OLD.id, OLD.external_provider, OLD.external_product_id, OLD.plan_id,
            OLD.purchase_url, OLD.idempotency_key, OLD.created_by_user_id, OLD.created_at
       )
       AND NEW.retired_at IS NOT NULL THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'product mapping immutable fields changed' USING ERRCODE = '55000';
END;
$$;

INSERT INTO openclaw_account.schema_migrations(revision)
VALUES ('009_openclaw_retail_admin');

COMMIT;
