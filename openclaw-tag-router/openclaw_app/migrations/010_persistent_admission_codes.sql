BEGIN;

ALTER TABLE openclaw_account.admission_codes
    ADD COLUMN code_ciphertext BYTEA;

UPDATE openclaw_account.admission_batches
SET status = 'disabled',
    disabled_by_user_id = created_by_user_id,
    disabled_reason = '010 persistent admission code migration',
    disabled_at = now()
WHERE status = 'active';

CREATE OR REPLACE FUNCTION openclaw_account.enforce_persistent_admission_code()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.code_ciphertext IS NULL THEN
        RAISE EXCEPTION 'admission code ciphertext is required' USING ERRCODE = '23502';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.code_ciphertext IS DISTINCT FROM OLD.code_ciphertext THEN
        RAISE EXCEPTION 'admission code ciphertext is immutable' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER admission_code_persistent_ciphertext
    BEFORE INSERT OR UPDATE ON openclaw_account.admission_codes
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.enforce_persistent_admission_code();

INSERT INTO openclaw_account.schema_migrations(revision)
VALUES ('010_persistent_admission_codes');

COMMIT;
