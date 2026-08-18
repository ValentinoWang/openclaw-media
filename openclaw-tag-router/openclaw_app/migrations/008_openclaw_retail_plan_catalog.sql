DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM openclaw_account.plans) THEN
        RAISE EXCEPTION 'plan catalog must be empty before 008 cutover';
    END IF;
END;
$$;

INSERT INTO openclaw_account.plans(id, code, name, price_cny, credit_amount, status)
VALUES
    ('80000000-0000-4000-8000-000000000001', 'mediaclaw-cny-1', 'MediaClaw CNY 1 Credit', 1, 1, 'active'),
    ('80000000-0000-4000-8000-000000000005', 'mediaclaw-cny-5', 'MediaClaw CNY 5 Credit', 5, 5, 'active'),
    ('80000000-0000-4000-8000-000000000020', 'mediaclaw-cny-20', 'MediaClaw CNY 20 Credit', 20, 20, 'active'),
    ('80000000-0000-4000-8000-000000000050', 'mediaclaw-cny-50', 'MediaClaw CNY 50 Credit', 50, 50, 'active'),
    ('80000000-0000-4000-8000-000000000100', 'mediaclaw-cny-100', 'MediaClaw CNY 100 Credit', 100, 100, 'active'),
    ('80000000-0000-4000-8000-000000000500', 'mediaclaw-cny-500', 'MediaClaw CNY 500 Credit', 500, 500, 'active');

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
       AND ROW(NEW.id, NEW.code, NEW.name, NEW.price_cny, NEW.credit_amount, NEW.created_at)
           IS NOT DISTINCT FROM
           ROW(OLD.id, OLD.code, OLD.name, OLD.price_cny, OLD.credit_amount, OLD.created_at)
       AND NEW.updated_at >= OLD.updated_at THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'plan catalog immutable fields changed' USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER plans_catalog_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON openclaw_account.plans
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.enforce_plan_catalog_immutability();

CREATE UNIQUE INDEX product_mappings_one_active_plan
    ON openclaw_account.product_mappings(plan_id)
    WHERE status = 'active';

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
       AND ROW(NEW.id, NEW.external_provider, NEW.external_product_id, NEW.plan_id, NEW.created_at)
           IS NOT DISTINCT FROM
           ROW(OLD.id, OLD.external_provider, OLD.external_product_id, OLD.plan_id, OLD.created_at)
       AND NEW.retired_at IS NOT NULL THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'product mapping immutable fields changed' USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER product_mappings_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON openclaw_account.product_mappings
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.enforce_product_mapping_immutability();

INSERT INTO openclaw_account.schema_migrations(revision)
VALUES ('008_openclaw_retail_plan_catalog');
