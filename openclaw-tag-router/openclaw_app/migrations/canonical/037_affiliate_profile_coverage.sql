INSERT INTO openclaw_account.affiliate_profiles(user_id, invite_code)
SELECT users.id,
       upper(substr(md5(users.id::text || ':mediaclaw-affiliate-v1'), 1, 20))
FROM openclaw_account.users AS users
WHERE NOT EXISTS (
    SELECT 1
    FROM openclaw_account.affiliate_profiles AS profile
    WHERE profile.user_id = users.id
);

DO $$
DECLARE
    missing_count INTEGER;
BEGIN
    SELECT count(*)
      INTO missing_count
      FROM openclaw_account.users AS users
      LEFT JOIN openclaw_account.affiliate_profiles AS profile
        ON profile.user_id = users.id
     WHERE profile.user_id IS NULL;

    IF missing_count <> 0 THEN
        RAISE EXCEPTION '037 affiliate profile coverage incomplete: missing=%', missing_count;
    END IF;
END;
$$;
