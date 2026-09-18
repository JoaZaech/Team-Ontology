-- Loads the CSV data pack (mounted read-only at /data) into the schema
-- created by 01_schema.sql. Order respects foreign-key dependencies.
SET search_path TO viseca, public;

\copy customers              FROM '/data/customers.csv'              WITH (FORMAT csv, HEADER true, NULL '')
\copy accounts                FROM '/data/accounts.csv'                WITH (FORMAT csv, HEADER true, NULL '')
\copy cards                    FROM '/data/cards.csv'                    WITH (FORMAT csv, HEADER true, NULL '')
\copy merchants                  FROM '/data/merchants.csv'                  WITH (FORMAT csv, HEADER true, NULL '')
\copy items                        FROM '/data/items.csv'                        WITH (FORMAT csv, HEADER true, NULL '')
\copy fx_rates                        FROM '/data/fx_rates.csv'                        WITH (FORMAT csv, HEADER true, NULL '')
\copy authorization_history              FROM '/data/authorization_history.csv'              WITH (FORMAT csv, HEADER true, NULL '')
\copy scenario_catalogue                    FROM '/data/scenario_catalogue.csv'                    WITH (FORMAT csv, HEADER true, NULL '')
\copy scenario_authorities                    FROM '/data/scenario_authorities.csv'                    WITH (FORMAT csv, HEADER true, NULL '')
\copy purchase_attempts                          FROM '/data/purchase_attempts.csv'                          WITH (FORMAT csv, HEADER true, NULL '')
\copy purchase_attempt_items (authorization_id, line_no, item_id, item_name, item_category, quantity, unit_price, currency, item_details) FROM '/data/purchase_attempt_items.csv' WITH (FORMAT csv, HEADER true, NULL '')
