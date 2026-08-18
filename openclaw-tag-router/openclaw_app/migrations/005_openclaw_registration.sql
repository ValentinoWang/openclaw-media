CREATE TABLE openclaw_account.registration_policy (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    mode TEXT NOT NULL CHECK (mode IN ('controlled', 'open')),
    updated_by_user_id UUID REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO openclaw_account.registration_policy(singleton, mode) VALUES (TRUE, 'controlled');

CREATE TABLE openclaw_account.admission_batches (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200),
    code_count INTEGER NOT NULL CHECK (code_count > 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    created_by_user_id UUID NOT NULL REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    created_reason TEXT NOT NULL DEFAULT '',
    disabled_by_user_id UUID REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    disabled_reason TEXT,
    disabled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE openclaw_account.admission_codes (
    id UUID PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES openclaw_account.admission_batches(id) ON DELETE RESTRICT,
    code_hmac BYTEA NOT NULL UNIQUE CHECK (octet_length(code_hmac) = 32),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'consumed', 'revoked')),
    consumed_by_user_id UUID REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    consumed_at TIMESTAMPTZ,
    UNIQUE(batch_id, id)
);
CREATE INDEX admission_codes_lookup_idx ON openclaw_account.admission_codes(code_hmac, status);

CREATE TABLE openclaw_account.affiliate_profiles (
    user_id UUID PRIMARY KEY REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    invite_code TEXT NOT NULL UNIQUE,
    signup_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    signup_quota INTEGER NOT NULL DEFAULT 0 CHECK (signup_quota >= 0),
    signup_used INTEGER NOT NULL DEFAULT 0 CHECK (signup_used >= 0 AND signup_used <= signup_quota),
    signup_expires_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX affiliate_profiles_code_idx ON openclaw_account.affiliate_profiles(invite_code, signup_enabled);

CREATE OR REPLACE FUNCTION openclaw_account.reject_affiliate_cycle()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE found_cycle BOOLEAN;
BEGIN
    IF NEW.inviter_user_id = NEW.invitee_user_id THEN RAISE EXCEPTION 'affiliate self invite'; END IF;
    WITH RECURSIVE chain(user_id) AS (
        SELECT NEW.inviter_user_id
        UNION ALL
        SELECT e.inviter_user_id FROM openclaw_account.affiliate_edges e JOIN chain c ON e.invitee_user_id = c.user_id
    ) SELECT EXISTS(SELECT 1 FROM chain WHERE user_id = NEW.invitee_user_id) INTO found_cycle;
    IF found_cycle THEN RAISE EXCEPTION 'affiliate cycle'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER affiliate_edges_cycle_guard BEFORE INSERT OR UPDATE ON openclaw_account.affiliate_edges
FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_affiliate_cycle();

INSERT INTO openclaw_account.schema_migrations(revision) VALUES ('005_openclaw_registration');
