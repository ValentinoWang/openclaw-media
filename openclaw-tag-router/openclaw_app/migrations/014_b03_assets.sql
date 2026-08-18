BEGIN;

CREATE INDEX IF NOT EXISTS assets_tenant_created_public_idx
    ON media_product.assets (tenant_id, created_at DESC, public_id ASC);

CREATE INDEX IF NOT EXISTS assets_tenant_updated_public_idx
    ON media_product.assets (tenant_id, updated_at DESC, public_id ASC);

CREATE INDEX IF NOT EXISTS assets_canonical_data_gin_idx
    ON media_product.assets USING gin (canonical_data jsonb_path_ops);

CREATE INDEX IF NOT EXISTS material_usages_tenant_asset_created_idx
    ON media_product.material_usages
       (tenant_id, (canonical_data->>'asset_id'), created_at DESC, public_id ASC);

CREATE INDEX IF NOT EXISTS material_deconstructions_tenant_asset_created_idx
    ON media_product.material_deconstructions
       (tenant_id, (canonical_data->>'asset_id'), created_at DESC, public_id ASC);

CREATE INDEX IF NOT EXISTS creative_patterns_supporting_assets_gin_idx
    ON media_product.creative_patterns USING gin (canonical_data jsonb_path_ops);

INSERT INTO media_product.migration_ledger (version, name)
VALUES (14, 'b03_assets_read_model')
ON CONFLICT (version) DO NOTHING;

COMMIT;
