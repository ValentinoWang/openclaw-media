DELETE FROM media_product.tenant_data_migration_audit older
USING media_product.tenant_data_migration_audit newer
WHERE older.source_tenant_id = newer.source_tenant_id
  AND older.target_tenant_id = newer.target_tenant_id
  AND older.table_name = newer.table_name
  AND older.id < newer.id;

ALTER TABLE media_product.tenant_data_migration_audit
    ADD CONSTRAINT tenant_data_migration_audit_identity
    UNIQUE (source_tenant_id, target_tenant_id, table_name);
