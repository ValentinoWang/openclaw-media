ALTER TABLE media_document.resources OWNER TO openclaw_account;

ALTER SEQUENCE media_document.resources_id_seq OWNER TO openclaw_account;

DO $$
DECLARE
    table_owner TEXT;
    sequence_owner TEXT;
BEGIN
    SELECT tableowner INTO table_owner
      FROM pg_tables
     WHERE schemaname = 'media_document'
       AND tablename = 'resources';

    SELECT pg_get_userbyid(relowner) INTO sequence_owner
      FROM pg_class
     WHERE oid = 'media_document.resources_id_seq'::regclass;

    IF table_owner IS DISTINCT FROM 'openclaw_account'
       OR sequence_owner IS DISTINCT FROM 'openclaw_account' THEN
        RAISE EXCEPTION 'media document resource ownership is not assigned to the runtime role';
    END IF;
END;
$$;
