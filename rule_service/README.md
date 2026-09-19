# Local Rule Service

The service evaluates a fixed mandate plus the active customer policy. Policies are durable JSON documents in a local SQLite database, rather than executable code supplied over HTTP. On first use, the complete default document is derived from the trusted `Knowledge_graph` history for its card and stores the graph version, as-of time, and supporting authorization IDs alongside the customer policy.

Run the service with:

```sh
export RULE_SERVICE_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python server.py
```

`RULE_SERVICE_API_TOKEN` is mandatory and must be at least 32 characters. Keep it in a secret manager or other protected runtime configuration; never commit it. Every `/v1/` request must provide it in `X-Rule-Service-Token`; `/healthz` is the only unauthenticated route.

The service binds only to `127.0.0.1`, does not provide TLS, and is not an Internet-facing server. To expose it, place an authenticated TLS reverse proxy in front of the loopback listener; do not bind this process directly to a network interface.

The default database is `var/rules.sqlite3`. Set `RULE_SERVICE_DB_PATH` to use another local path whose parent directory is private and owned by the service user. Database, WAL, and shared-memory files must be private regular files owned by that user. The database is intentionally excluded from source control.

The store keeps a current policy document and an immutable-in-application revision ledger. Every write is validated, uses an optimistic `expectedRevision`, is committed atomically, and records a SHA-256 document digest plus the previous digest. New policies must start at revision 1, and creation/update audit fields are service-owned. Reads revalidate the document and reject a corrupted or inconsistent record. SQLite parameters are always bound rather than interpolated.

Use the policy endpoints as follows:

- `GET /v1/rules/policy` reads the default policy.
- `PATCH /v1/rules/policy` applies a validated patch using `policyId`, `expectedRevision`, and `patch`.
- `GET /v1/rules/policies` lists stored policies.
- `POST /v1/rules/policies` adds a complete validated policy document for a new card.
- `POST /v1/rules/policies/from-knowledge-graph` with `{"cardId":"CA0002"}` derives and stores a complete policy for that card from the knowledge graph.
- `GET /v1/rules/policies/{policyId}/revisions` returns its revision ledger.

Evaluation always loads the policy bound to the event card from the local database. A caller cannot inject a policy snapshot into `/v1/rules/evaluate`.

The revision ledger detects malformed, incomplete, and internally inconsistent records. OS permissions protect this local design from other users; do not treat a database stored on a shared or compromised account as protected from that account owner. A user or process able to alter both the database and service configuration remains outside this local threat model.
