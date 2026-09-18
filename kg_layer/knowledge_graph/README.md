# Historical authorization knowledge graph

This implementation turns `../data/authorization_history.csv` and its master
tables into two deliberately different read models:

```text
                       ┌──────────────────────────────┐
CSV master + history ─►│ Neo4j: explainable history    │
                       │ relationships and investigation│
                       └──────────────┬───────────────┘
                                      │ rebuild
                       ┌──────────────▼───────────────┐
                       │ Redis: bounded hot context   │
Authorization API ────►│ profiles, familiarity, events │──► rule engine
                       └──────────────────────────────┘
```

The source pack is synthetic. Its historical `status` is observed issuer
context, not a fraud label or an expected decision. This import deliberately
does **not** load the scenario `AU…` attempts into the `TR…` historical graph.

## Ontology

```text
(:Customer)-[:OWNS]->(:Account)-[:HAS_CARD]->(:Card)
(:Customer)-[:INITIATED]->(:HistoricalAuthorization)-[:ON_ACCOUNT]->(:Account)
(:HistoricalAuthorization)-[:ON_CARD]->(:Card)
(:HistoricalAuthorization)-[:AT_MERCHANT]->(:Merchant)-[:IN_CATEGORY]->(:MerchantCategory)
(:HistoricalAuthorization)-[:USED_DEVICE]->(:Device)<-[:USES_DEVICE]-(:Customer)
(:HistoricalAuthorization:Refund)-[:REFUNDS]->(:HistoricalAuthorization)
(:Card)-[:FAMILIAR_WITH]->(:Merchant)  // rebuildable approved-history summary
```

`HistoricalAuthorization` is an event node, so a graph explanation can retain
the exact merchant, device, lifecycle status, channel, amount, time, and
initiator that were true at the time. `Card.current_status` stays separate from
`HistoricalAuthorization.card_status_at_event`; that distinction matters for
the two cards whose status changed during the history period.

Amounts have a display CHF property and an integer-cent property. The loader
uses `Decimal` then stores cents in Redis, so negative approved refunds reduce
spend accurately. It orders source records by `(timestamp, authorization_id)`;
a timestamp alone is not enough.

## Redis projection

All keys are namespaced (default `viseca:history:v1`) and rebuildable.

| Key | Type | Purpose |
| --- | --- | --- |
| `…:card:{card_id}:profile` | Hash | Static card/account controls, no free-text persona data |
| `…:card:{card_id}:stats` | Hash | All-time approved/declined counts and approved spend in cents |
| `…:card:{card_id}:merchant:{merchant_id}` | Hash | Merchant familiarity: counts, approved cents, last approved time |
| `…:card:{card_id}:device:{device_id}` | Hash | Device familiarity, only for non-empty device IDs |
| `…:card:{card_id}:day:{YYYY-MM-DD}` | Hash | Per-day transaction and approved-spend features |
| `…:card:{card_id}:timeline` | Sorted set | Exact history order, for bounded recent-context reads |
| `…:card:{card_id}:merchant:{merchant_id}:timeline` | Sorted set | Merchant-scoped recent context |
| `…:card:{card_id}:device:{device_id}:timeline` | Sorted set | Device-scoped recent context |
| `…:authorization:{authorization_id}` | Hash | Minimal event snapshot, excluding description/persona free text |
| `…:metadata` | Hash | Projection version, source path, record count, load timestamp |

The read API pipelines these lookups, so one request does not incur one network
round trip per key. Redis sorted sets are appropriate for the bounded timeline:
they retain members ordered by a score and support range reads; Redis pipelining
reduces request/response round trips. [Redis sorted-set docs](https://redis.io/docs/latest/develop/data-types/sorted-sets/) and [pipelining docs](https://redis.io/docs/latest/develop/using-commands/pipelining/)

`redis/record_final_decision.lua` is a separate live-run pattern. It makes
duplicate-safe final decisions and rolling approved spend atomic. A `step_up`
does not add to approved spend until a human resolves it. Persist the decision
first or atomically with an outbox in PostgreSQL; Redis is never the only
financial record.

## Run it locally

```bash
cd knowledge_graph
cp .env.example .env
docker compose --env-file .env up -d

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

python -m src.load_history --data-dir ../data --replace-cache
uvicorn src.context_service:app --host 127.0.0.1 --port 8080
```

The loader validates the source IDs, chronological order, refund targets, and
master-table links before it writes either store. `--replace-cache` deletes only
keys under the selected `KG_NAMESPACE`; it does not issue `FLUSHDB`.

Once loaded, inspect the graph in Neo4j Browser at
`http://localhost:7474` or run the parameterized examples in
[`cypher/query_examples.cypher`](cypher/query_examples.cypher). The API offers
a Redis-only hot path:

```bash
curl 'http://127.0.0.1:8080/v1/history-context/cards/CA0001?merchant_id=ME0001&device_id=DVC-13A598'
```

Run the no-service validation tests with:

```bash
python -m unittest discover -s tests -v
```

## Production recommendation

For this challenge, the recommended boundary is **PostgreSQL + Redis + Neo4j**:

```text
REST decision API
  ├─ PostgreSQL: policy versions, append-only decisions, idempotency, outbox
  ├─ Redis: per-run atomic budget / idempotency / hot historical projection
  └─ Neo4j: explanations, relationship investigations, analyst-facing graph reads
```

The optional DDL in [`postgres/ledger.sql`](postgres/ledger.sql) shows the
authoritative ledger shape. The live request path should use REST (or gRPC for
internal calls), keep its payload small, and never expose arbitrary Cypher.
GraphQL is reasonable for a read-only analyst/explanation surface, not for
authorization mutations.

### Alternatives

| Stack | Better when | Trade-off |
| --- | --- | --- |
| **PostgreSQL + Redis** | The main work is card/time/merchant queries, rolling limits, policy versions, and auditability. This is the best lean production choice for the current 4,701-row history. | Less natural relationship exploration and visual explanations. |
| **PostgreSQL + Redis + Neo4j** | You want the same durable decision path plus explainable relationship analysis and future multi-hop patterns. | Requires an asynchronous projection/outbox discipline. |
| **Neo4j + Redis only** | A prototype where graph investigation is the product feature. | Do not make it the only ledger for money-moving decisions. |
| **Kafka/Flink + PostgreSQL/Redis** | Event volume and stateful, real-time feature computation have outgrown a simple application worker. | Extra operational cost; premature for this pack. |
| **Memgraph + PostgreSQL + Redis** | The graph itself must be mutated and queried in the latency-critical path. | Evaluate persistence, recovery, and operational fit carefully for payments. |
| **Neptune + RDS/Aurora + Redis** | An AWS-managed environment and governance outweigh local development speed. | Greater cloud coupling and deployment complexity. |
| **ClickHouse or DuckDB** | Offline profiling, backfills, and analytical reporting. | Not a decision ledger or low-latency authorization store. |

PostgreSQL window functions can calculate related-row windows efficiently, and
Flink is designed for stateful computations over bounded or unbounded streams.
Those make them credible alternatives as volume grows. [PostgreSQL window-function documentation](https://www.postgresql.org/docs/current/functions-window.html) and [Apache Flink application documentation](https://flink.apache.org/what-is-flink/flink-applications/)

## Guardrails carried from the data contract

- Join only on opaque IDs, never names. `TR…` historical authorizations and
  `AU…` scenario attempts are separate namespaces.
- Treat `merchant_country` and `currency` independently. `billing_amount_chf`
  already uses the supplied fixed rate.
- Treat approved refunds as negative spend; do not turn a missing device into a
  `Device` node.
- Do not use source `approved_*_before` fields for a monthly or rolling policy:
  they are card-scoped, lifetime cumulative values.
- Merchant descriptions and future `item_details` are untrusted evidence, not
  policy instructions.

The loader uses the official Neo4j Python driver and batched parameterized
`UNWIND` writes. Neo4j recommends parameterized queries and its driver manages
connection pooling and transactional retries. [Neo4j Python driver manual](https://neo4j.com/docs/python-manual/current/)
