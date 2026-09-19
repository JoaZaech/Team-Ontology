# Viseca data pack — Postgres

Loads the CSV data pack in [`../data`](../data) into a queryable Postgres 16
database running in Docker, with proper types, primary keys, foreign keys,
and indexes (see `init/01_schema.sql` for the full DDL, derived from
`data/data_dictionary.md` and `data/README.md`).

## Start it

```bash
cd db
docker compose up -d
```

On first start, Postgres runs the scripts in `init/` in order:

1. `01_schema.sql` — creates the `viseca` schema and all tables/constraints/indexes.
2. `02_load.sql` — `\copy`s each CSV from the read-only `/data` mount into its table.
3. `03_verify.sql` — asserts each table's row count matches `metadata.json`.

Watch it come up:

```bash
docker compose logs -f db
```

Look for the `NOTICE` lines from step 3 (`customers OK (20 rows)`, …). If a
row count doesn't match, the init sequence raises an exception and Postgres
exits — check the log for which table and why.

## Connect

```bash
docker compose exec db psql -U viseca -d viseca
```

Or from the host (requires local `psql`):

```bash
psql "postgresql://viseca:viseca@localhost:5432/viseca"
```

The database's `search_path` already includes the `viseca` schema, so table
names don't need qualifying, e.g.:

```sql
select count(*) from authorization_history where initiator_type = 'agent';

select p.authorization_id, p.merchant_id, m.merchant_name, p.billing_amount_chf
from purchase_attempts p
join merchants m using (merchant_id)
where p.scenario_id = 'SCEN0002';
```

## Visual interface

[Adminer](https://www.adminer.org/) runs alongside the database at
**http://localhost:8080**. Log in with:

| | |
| --- | --- |
| System | `PostgreSQL` |
| Server | `db` |
| Username | `viseca` |
| Password | `viseca` |
| Database | `viseca` |

It gives you table browsing, a SQL query box, and an ER diagram (the "DB
schema" link at the top of a table listing) — no separate install needed
since it's just the second container in `docker-compose.yml`.

## Re-loading after a data pack change

Init scripts only run against an empty data volume. To rebuild from scratch
(e.g. after the CSVs change):

```bash
docker compose down -v   # drops the viseca_pgdata volume — destroys current DB contents
docker compose up -d
```

## Connection details

| | |
| --- | --- |
| Host | `localhost` |
| Port | `5432` |
| User | `viseca` |
| Password | `viseca` |
| Database | `viseca` |
| Schema | `viseca` |

These are local dev defaults for synthetic challenge data only — not meant
for anything beyond this container.

## Decision history

The local Viseca mock stores its activity history in this database. Start the
database, then run the mock with:

```bash
export ACTIVITY_DATABASE_URL='postgresql://viseca:viseca@127.0.0.1:5432/viseca'
python3 -B ../../mock_api/viseca_mock.py
```

The mock creates `activity_events` and `transactions` on startup. An approved
or declined decision, and a resolved step-up, returns only after its
transaction history projection has committed.
