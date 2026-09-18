-- Sanity check row counts against the pack's own metadata.json.
SET search_path TO viseca, public;

DO $$
DECLARE
    expected jsonb := '{
        "customers": 20, "accounts": 31, "cards": 41, "merchants": 58,
        "items": 66, "fx_rates": 4, "authorization_history": 4701,
        "scenario_catalogue": 5, "scenario_authorities": 5,
        "purchase_attempts": 45, "purchase_attempt_items": 56
    }'::jsonb;
    tbl text;
    want integer;
    got integer;
BEGIN
    FOR tbl, want IN SELECT * FROM jsonb_each_text(expected) LOOP
        EXECUTE format('SELECT count(*) FROM %I', tbl) INTO got;
        IF got <> want THEN
            RAISE EXCEPTION 'row count mismatch in %: expected %, got %', tbl, want, got;
        END IF;
        RAISE NOTICE '% OK (% rows)', tbl, got;
    END LOOP;
END $$;
