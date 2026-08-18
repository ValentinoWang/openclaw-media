CREATE INDEX IF NOT EXISTS tracks_b02_tenant_updated_public_idx
    ON media_product.tracks (tenant_id, updated_at DESC, public_id ASC);

CREATE INDEX IF NOT EXISTS tracks_b02_parent_lookup_idx
    ON media_product.tracks (
        tenant_id,
        (COALESCE(
            NULLIF(canonical_data->>'parent_track_id', ''),
            NULLIF(canonical_data->>'parentPublicTrackId', '')
        ))
    );

CREATE INDEX IF NOT EXISTS creator_profiles_b02_tenant_updated_public_idx
    ON media_product.creator_profiles (tenant_id, updated_at DESC, public_id ASC);

CREATE INDEX IF NOT EXISTS track_creator_memberships_b02_tenant_updated_public_idx
    ON media_product.track_creator_memberships (tenant_id, updated_at DESC, public_id ASC);

CREATE INDEX IF NOT EXISTS track_creator_memberships_b02_explicit_pair_idx
    ON media_product.track_creator_memberships (
        tenant_id,
        (COALESCE(
            NULLIF(canonical_data->>'track_id', ''),
            NULLIF(canonical_data->>'public_track_id', '')
        )),
        (COALESCE(
            NULLIF(canonical_data->>'creator_profile_id', ''),
            NULLIF(canonical_data->>'public_creator_id', '')
        ))
    );

CREATE UNIQUE INDEX IF NOT EXISTS track_creator_memberships_b02_explicit_pair_uq
    ON media_product.track_creator_memberships (
        tenant_id,
        (COALESCE(
            NULLIF(canonical_data->>'track_id', ''),
            NULLIF(canonical_data->>'public_track_id', '')
        )),
        (COALESCE(
            NULLIF(canonical_data->>'creator_profile_id', ''),
            NULLIF(canonical_data->>'public_creator_id', '')
        ))
    )
    WHERE COALESCE(
        NULLIF(canonical_data->>'track_id', ''),
        NULLIF(canonical_data->>'public_track_id', '')
    ) IS NOT NULL
      AND COALESCE(
        NULLIF(canonical_data->>'creator_profile_id', ''),
        NULLIF(canonical_data->>'public_creator_id', '')
    ) IS NOT NULL;

CREATE INDEX IF NOT EXISTS owned_media_accounts_b02_tenant_updated_public_idx
    ON media_product.owned_media_accounts (tenant_id, updated_at DESC, public_id ASC);

CREATE INDEX IF NOT EXISTS account_track_strategies_b02_tenant_account_updated_idx
    ON media_product.account_track_strategies (
        tenant_id,
        (COALESCE(
            NULLIF(canonical_data->>'public_account_id', ''),
            NULLIF(canonical_data->>'account_id', '')
        )),
        updated_at DESC,
        public_id ASC
    );
