ALTER TABLE openclaw_account.model_operations
    ADD COLUMN actor_user_id UUID;

ALTER TABLE openclaw_account.usage_events
    ADD COLUMN actor_user_id UUID;

ALTER TABLE openclaw_account.model_operations
    ADD CONSTRAINT model_operations_actor_tenant_member_fkey
    FOREIGN KEY (tenant_id, actor_user_id)
    REFERENCES openclaw_account.tenant_members(tenant_id, user_id)
    ON DELETE RESTRICT;

ALTER TABLE openclaw_account.usage_events
    ADD CONSTRAINT usage_events_actor_tenant_member_fkey
    FOREIGN KEY (tenant_id, actor_user_id)
    REFERENCES openclaw_account.tenant_members(tenant_id, user_id)
    ON DELETE RESTRICT;

CREATE INDEX model_operations_tenant_actor_created_idx
    ON openclaw_account.model_operations (tenant_id, actor_user_id, created_at DESC)
    WHERE actor_user_id IS NOT NULL;

CREATE INDEX usage_events_tenant_actor_created_idx
    ON openclaw_account.usage_events (tenant_id, actor_user_id, created_at DESC)
    WHERE actor_user_id IS NOT NULL;

CREATE OR REPLACE FUNCTION openclaw_account.enforce_actual_actor_membership()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    membership_status TEXT;
BEGIN
    IF NEW.actor_user_id IS NULL THEN
        IF TG_OP = 'INSERT' THEN
            RAISE EXCEPTION '% requires actor_user_id for new rows', TG_TABLE_NAME
                USING ERRCODE = '23514';
        END IF;

        IF OLD.actor_user_id IS NOT NULL THEN
            RAISE EXCEPTION '% cannot clear actor_user_id', TG_TABLE_NAME
                USING ERRCODE = '23514';
        END IF;

        -- Rows created before this migration retain their explicitly unknown actor.
        RETURN NEW;
    END IF;

    SELECT member.status
      INTO membership_status
      FROM openclaw_account.tenant_members AS member
     WHERE member.tenant_id = NEW.tenant_id
       AND member.user_id = NEW.actor_user_id
     FOR SHARE;

    IF NOT FOUND OR membership_status <> 'active' THEN
        RAISE EXCEPTION '% actor_user_id must be an active member of the row tenant', TG_TABLE_NAME
            USING ERRCODE = '23503';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER model_operations_actual_actor_membership
    BEFORE INSERT OR UPDATE OF tenant_id, actor_user_id
    ON openclaw_account.model_operations
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.enforce_actual_actor_membership();

CREATE TRIGGER usage_events_actual_actor_membership
    BEFORE INSERT OR UPDATE OF tenant_id, actor_user_id
    ON openclaw_account.usage_events
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.enforce_actual_actor_membership();

ALTER TABLE openclaw_account.plans
    ADD COLUMN audience TEXT,
    ADD COLUMN product_kind TEXT;

DO $$
DECLARE
    fixed_credit_codes CONSTANT TEXT[] := ARRAY[
        'mediaclaw-cny-1',
        'mediaclaw-cny-5',
        'mediaclaw-cny-20',
        'mediaclaw-cny-50',
        'mediaclaw-cny-100',
        'mediaclaw-cny-500'
    ];
    target_count INTEGER;
    equal_value_count INTEGER;
BEGIN
    SELECT COUNT(*)
      INTO target_count
      FROM openclaw_account.plans
     WHERE code = ANY (fixed_credit_codes)
       AND status = 'active'
       AND currency = 'credit'
       AND price_cny = credit_amount;

    SELECT COUNT(*)
      INTO equal_value_count
      FROM openclaw_account.plans
     WHERE status = 'active'
       AND currency = 'credit'
       AND price_cny = credit_amount;

    IF target_count <> 6 OR equal_value_count <> 6 THEN
        RAISE EXCEPTION
            '036 expected exactly six active equal-value credit products; target=% equal_value=%',
            target_count,
            equal_value_count;
    END IF;
END;
$$;

-- The temporary definition permits only the six-row classification backwash.
CREATE OR REPLACE FUNCTION openclaw_account.enforce_plan_catalog_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    fixed_credit_codes CONSTANT TEXT[] := ARRAY[
        'mediaclaw-cny-1',
        'mediaclaw-cny-5',
        'mediaclaw-cny-20',
        'mediaclaw-cny-50',
        'mediaclaw-cny-100',
        'mediaclaw-cny-500'
    ];
BEGIN
    IF TG_OP = 'INSERT' OR TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'plan catalog is closed' USING ERRCODE = '55000';
    END IF;

    IF OLD.status = 'active'
       AND NEW.status = OLD.status
       AND OLD.code = ANY (fixed_credit_codes)
       AND NEW.audience = 'all'
       AND NEW.product_kind = 'balance_pack'
       AND ROW(
            NEW.id, NEW.code, NEW.name, NEW.price_cny, NEW.credit_amount,
            NEW.text_quota, NEW.image_quota, NEW.currency, NEW.revision,
            NEW.status, NEW.created_at
       ) IS NOT DISTINCT FROM ROW(
            OLD.id, OLD.code, OLD.name, OLD.price_cny, OLD.credit_amount,
            OLD.text_quota, OLD.image_quota, OLD.currency, OLD.revision,
            OLD.status, OLD.created_at
       )
       AND NEW.updated_at >= OLD.updated_at THEN
        RETURN NEW;
    END IF;

    IF OLD.status = 'active'
       AND NEW.status = 'retired'
       AND ROW(
            NEW.id, NEW.code, NEW.name, NEW.price_cny, NEW.credit_amount,
            NEW.text_quota, NEW.image_quota, NEW.currency, NEW.revision,
            NEW.audience, NEW.product_kind, NEW.created_at
       ) IS NOT DISTINCT FROM ROW(
            OLD.id, OLD.code, OLD.name, OLD.price_cny, OLD.credit_amount,
            OLD.text_quota, OLD.image_quota, OLD.currency, OLD.revision,
            OLD.audience, OLD.product_kind, OLD.created_at
       )
       AND NEW.updated_at >= OLD.updated_at THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'plan catalog immutable fields changed' USING ERRCODE = '55000';
END;
$$;

UPDATE openclaw_account.plans
   SET audience = 'all',
       product_kind = 'balance_pack'
 WHERE code = ANY (ARRAY[
    'mediaclaw-cny-1',
    'mediaclaw-cny-5',
    'mediaclaw-cny-20',
    'mediaclaw-cny-50',
    'mediaclaw-cny-100',
    'mediaclaw-cny-500'
]::TEXT[])
   AND (audience IS DISTINCT FROM 'all' OR product_kind IS DISTINCT FROM 'balance_pack');

DO $$
DECLARE
    fixed_credit_codes CONSTANT TEXT[] := ARRAY[
        'mediaclaw-cny-1',
        'mediaclaw-cny-5',
        'mediaclaw-cny-20',
        'mediaclaw-cny-50',
        'mediaclaw-cny-100',
        'mediaclaw-cny-500'
    ];
    classified_count INTEGER;
BEGIN
    SELECT COUNT(*)
      INTO classified_count
      FROM openclaw_account.plans
     WHERE code = ANY (fixed_credit_codes)
       AND audience = 'all'
       AND product_kind = 'balance_pack';

    IF classified_count <> 6 THEN
        RAISE EXCEPTION '036 catalog backwash incomplete; classified=%', classified_count;
    END IF;
END;
$$;

ALTER TABLE openclaw_account.plans
    ADD CONSTRAINT plans_audience_valid
    CHECK (audience IN ('personal', 'organization', 'all')),
    ADD CONSTRAINT plans_product_kind_valid
    CHECK (product_kind IN ('balance_pack', 'organization_plan'));

ALTER TABLE openclaw_account.plans
    ALTER COLUMN audience SET NOT NULL,
    ALTER COLUMN product_kind SET NOT NULL;

CREATE OR REPLACE FUNCTION openclaw_account.enforce_plan_catalog_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' OR TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'plan catalog is closed' USING ERRCODE = '55000';
    END IF;

    IF OLD.status = 'active'
       AND NEW.status = 'retired'
       AND ROW(
            NEW.id, NEW.code, NEW.name, NEW.price_cny, NEW.credit_amount,
            NEW.text_quota, NEW.image_quota, NEW.currency, NEW.revision,
            NEW.audience, NEW.product_kind, NEW.created_at
       ) IS NOT DISTINCT FROM ROW(
            OLD.id, OLD.code, OLD.name, OLD.price_cny, OLD.credit_amount,
            OLD.text_quota, OLD.image_quota, OLD.currency, OLD.revision,
            OLD.audience, OLD.product_kind, OLD.created_at
       )
       AND NEW.updated_at >= OLD.updated_at THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'plan catalog immutable fields changed' USING ERRCODE = '55000';
END;
$$;
