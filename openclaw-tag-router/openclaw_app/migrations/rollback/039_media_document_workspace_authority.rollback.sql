-- 039 is a one-way authority hardening migration. Reversal requires an
-- explicitly reviewed data repair and must not be performed implicitly.
DO $$
BEGIN
    RAISE EXCEPTION '039_media_document_workspace_authority rollback is blocked';
END;
$$;
