CREATE TABLE openclaw_account.registration_policy (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    mode TEXT NOT NULL CHECK (mode IN ('controlled', 'open')),
    updated_by_user_id UUID REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    reason TEXT CHECK (reason IS NULL OR length(btrim(reason)) BETWEEN 1 AND 500),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO openclaw_account.registration_policy(singleton, mode)
VALUES (TRUE, 'controlled');

CREATE TABLE openclaw_account.admission_batches (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    code_count INTEGER NOT NULL CHECK (code_count BETWEEN 1 AND 1000),
    created_by_user_id UUID NOT NULL REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    disabled_by_user_id UUID REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    created_reason TEXT NOT NULL CHECK (length(btrim(created_reason)) BETWEEN 1 AND 500),
    disabled_reason TEXT CHECK (disabled_reason IS NULL OR length(btrim(disabled_reason)) BETWEEN 1 AND 500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at TIMESTAMPTZ,
    CHECK ((status = 'disabled') = (disabled_at IS NOT NULL)),
    CHECK ((status = 'disabled') = (disabled_by_user_id IS NOT NULL)),
    CHECK ((status = 'disabled') = (disabled_reason IS NOT NULL))
);

CREATE INDEX admission_batches_created_idx
    ON openclaw_account.admission_batches(created_at DESC);

CREATE TABLE openclaw_account.admission_codes (
    id UUID PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES openclaw_account.admission_batches(id) ON DELETE RESTRICT,
    code_hmac BYTEA NOT NULL UNIQUE CHECK (octet_length(code_hmac) = 32),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'consumed')),
    consumed_by_user_id UUID UNIQUE REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((status = 'consumed') = (consumed_at IS NOT NULL)),
    CHECK ((status = 'consumed') = (consumed_by_user_id IS NOT NULL))
);

CREATE INDEX admission_codes_batch_status_idx
    ON openclaw_account.admission_codes(batch_id, status);

CREATE TABLE openclaw_account.affiliate_profiles (
    user_id UUID PRIMARY KEY REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    invite_code TEXT NOT NULL UNIQUE CHECK (invite_code ~ '^[A-F0-9]{20}$'),
    signup_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    signup_quota INTEGER NOT NULL DEFAULT 0 CHECK (signup_quota BETWEEN 0 AND 1000000),
    signup_used INTEGER NOT NULL DEFAULT 0 CHECK (signup_used >= 0 AND signup_used <= signup_quota),
    signup_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO openclaw_account.affiliate_profiles(user_id, invite_code)
SELECT users.id, upper(substr(md5(gen_random_uuid()::text || users.id::text), 1, 20))
FROM openclaw_account.users AS users;

CREATE OR REPLACE FUNCTION openclaw_account.reject_affiliate_profile_identity_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.user_id <> OLD.user_id OR NEW.invite_code <> OLD.invite_code THEN
        RAISE EXCEPTION 'affiliate profile identity is immutable' USING ERRCODE = '55000';
    END IF;
    IF NEW.signup_used < OLD.signup_used THEN
        RAISE EXCEPTION 'affiliate signup usage cannot decrease' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER affiliate_profile_identity_immutable
    BEFORE UPDATE ON openclaw_account.affiliate_profiles
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_affiliate_profile_identity_mutation();

CREATE OR REPLACE FUNCTION openclaw_account.reject_affiliate_cycle()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.inviter_user_id = NEW.invitee_user_id THEN
        RAISE EXCEPTION 'affiliate self-invite is prohibited' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        WITH RECURSIVE descendants(user_id) AS (
            SELECT edge.invitee_user_id
            FROM openclaw_account.affiliate_edges AS edge
            WHERE edge.inviter_user_id = NEW.invitee_user_id
            UNION
            SELECT edge.invitee_user_id
            FROM openclaw_account.affiliate_edges AS edge
            JOIN descendants ON edge.inviter_user_id = descendants.user_id
        )
        SELECT 1 FROM descendants WHERE user_id = NEW.inviter_user_id
    ) THEN
        RAISE EXCEPTION 'affiliate cycle is prohibited' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER affiliate_edges_no_cycle
    BEFORE INSERT ON openclaw_account.affiliate_edges
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_affiliate_cycle();

INSERT INTO openclaw_account.schema_migrations (revision)
VALUES ('005_openclaw_registration_affiliate');
