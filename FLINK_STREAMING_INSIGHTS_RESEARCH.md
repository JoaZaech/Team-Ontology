# Apache Flink for the Knowledge-Graph / Decision-System Feedback Loop

**Research date:** 19 September 2026<br>
**Recommendation:** use Apache Flink, run locally via PyFlink (no cluster), as the stream processor that fills the outbox → async-projection role `TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md` already designs but leaves unimplemented — continuously enriching the Neo4j evidence graph **and** writing live-computed features back into a store the deterministic evaluator reads on the next decision.

## Executive summary

Today, every signal the guardrail uses to judge a new purchase is either a **static snapshot taken once at process boot** or a **hardcoded placeholder**. Nothing in the repository currently computes anything continuously, and nothing writes derived knowledge back into the system after a decision is made. That is the literal gap the user's question points at: how do we get downstream value out of the knowledge graph and decision system, and how do we close the loop so new decisions make future decisions smarter?

Flink is the right tool for exactly this seam, for two reasons that map onto two separate jobs:

1. **Continuous graph enrichment.** A stateful stream job can consume decision events and keep the Neo4j "Consent & Evidence Graph" ([TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md](TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md)) up to date via idempotent upserts — replacing the one-shot batch CSV loader that existed before commit `c0ea2f6` deleted it, and adding real-time duplicate/lookalike-merchant detection the old batch loader never had.
2. **Write-back into the decision path.** A second stateful job can maintain the rolling aggregates the guardrail actually needs — merchant familiarity, rolling approved spend, attempt velocity — as Flink keyed state, and continuously project the *current value* into a small local store the deterministic evaluator reads synchronously. This is the "write new insights back to the system" half of the question: each decision that happens now measurably changes what the *next* decision sees, without Flink, Neo4j, or any external service ever sitting in the synchronous authorization path.

That last constraint is not a preference, it is the architecture's existing trust-boundary rule: "an unavailable dependency never becomes implicit permission" ([TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md](TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md#trust-boundaries)). Flink slots in underneath that rule, not around it — every synchronous read stays local, and unavailability degrades to the same conservative fallback the system already uses today.

## The gap, grounded in the current code

| What | Where | Problem |
| --- | --- | --- |
| Merchant familiarity count | `MerchantHistory.from_data_dir()`, [live_layer/guardian.py:47-59](live_layer/guardian.py#L47-L59) | Computed once from `authorization_history.csv` at process start. Never updated as new decisions happen. |
| Rolling approved spend in period | `GuardPolicy.approved_spend_in_period_chf` | No live source anywhere. `viseca_mock.py`'s `build_connection_event()` hardcodes it to `0.0`. |
| Attempt velocity (10 min) | `authorization.recent_attempt_count_10m` | Same story — hardcoded to `0` in `build_connection_event()`. |
| Neo4j graph | `kg_layer/docker-compose.yml`, [kg_layer/README.md](kg_layer/README.md) | Running container, explicitly "not wired up to any application code yet." |
| Rolling-period spend eviction logic | `redis/record_final_decision.lua` | Existed in a deleted design (`git show c0ea2f6^:kg_layer/knowledge_graph/`), never rebuilt. |

`rulebook.py` compounds the gap: its call into `evaluate_guard` ([live_layer/rulebook.py:82-85](live_layer/rulebook.py#L82-L85)) never sets `max_period_chf`, so the period-spend check is silently skipped end-to-end even though `guardian.py` already has a code path for it ([live_layer/guardian.py:92-100](live_layer/guardian.py#L92-L100)).

In short: the deterministic core is well-built and already anticipates these signals — it just has nothing feeding them live.

## Proposed architecture

```
viseca_mock.py                          replay of authorization_history.csv
MockVisecaState.record_decision()       (4,701 historical rows, for volume)
        │                                          │
        ▼                                          ▼
        outbox: append-only JSONL of authorization.requested /
                authorization.decided events (event-time timestamped)
                        │
        ┌───────────────┴───────────────┐
        ▼                                ▼
  Flink Job A                      Flink Job B
  hot_context_job                  graph_projection_job
  (keyed state: familiarity,       (idempotent MERGE upserts,
   rolling spend, velocity)         duplicate / lookalike detection)
        │                                ▼
        ▼                          Neo4j — Consent & Evidence Graph
  local SQLite hot-context store   (read-only, async, investigation
        │                           / explanation surface only)
        ▼  (synchronous, local, read-only, try/except-guarded)
  guardian.py / rulebook.py — unchanged pure evaluator,
  falls back to the static CSV baseline if the store is
  missing, stale, or unreadable
```

Two jobs, not three: duplicate/related-order detection and lookalike-merchant-name detection are folded into Job B as extra keyed-state operators rather than built as a separate CEP job. `flink-cep`'s Python API support is thin, and plain `KeyedProcessFunction` state/timers cover the same patterns (a second authorization at the same merchant within a short window; a merchant name close to a known one under a different ID) with fewer moving parts.

### Job A — hot-context feature aggregation

Keyed purely off fields the guardrail already consumes:

- **Merchant familiarity** — `keyBy(card_id, merchant_id)`, a counter incremented on `authorization.decided` events where `decision == "approve"`. This is the exact same rule `guardian.py` already uses (`status == "approved" and transaction_type == "purchase"`, [guardian.py:57](live_layer/guardian.py#L57)), just computed continuously instead of once.
- **Rolling approved spend in period** — `keyBy(card_id)`, windowed state that sums only *final* approved decisions and evicts entries past the policy window via an event-time timer — mirroring the eviction logic the deleted `record_final_decision.lua` implemented in Redis, reimplemented as Flink state. Only final approvals count, never a pending `step_up`, matching the rule already stated in [TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md](TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md#the-deterministic-decision-contract).
- **Attempt velocity (10 min)** — `keyBy(card_id)`, a sliding count of `authorization.requested` events, evicting anything older than 10 minutes.

Sink: current computed value (not an increment) written into a local SQLite store, so at-least-once delivery or a replay never double-counts.

**Correctness check:** replaying `viseca-2026/data/authorization_history.csv` through this job should converge, for `(card_id=CA0001, merchant_id=ME0001)`, to the same **26** prior approved purchases the static batch load already produces — already asserted today in [live_layer/test_viseca_mock.py:40](live_layer/test_viseca_mock.py#L40). That equality is the concrete proof that the continuous computation isn't inventing a different truth, just a fresher one.

### Job B — Neo4j graph projection

Idempotent `MERGE`-based upserts onto the ontology `TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md` already specifies (`Authorization`/`HistoricalAuthorization`, `Merchant`, `Card`, `Decision`, a minimal `DecisionReceipt`) — a right-sized subset, not the full `MandateVersion`/`PolicyRule`/`RuleCheck`/hash-chained-receipt ledger, which is separate, unrelated work already scoped elsewhere in that document. Constraints are reused from the recoverable prior design (`git show c0ea2f6^:kg_layer/knowledge_graph/cypher/schema.cypher`) rather than invented fresh.

Enrichment folded into the same job:
- `related_authorization_id`, when present on an event, becomes a `RELATED_TO` edge — a direct field mapping.
- A `card_id`-keyed operator flags a second authorization at the same merchant within a short event-time window as a possible duplicate.
- A startup-time comparison over the merchant catalogue (loaded once, not per-event) flags lookalike merchant names within the same category/country as a `lookalike_of` edge.

All of this lands in Neo4j only — an investigation/explanation surface for an analyst, never a synchronous input to a decision, per the architecture's existing rule that a graph outage must never create uncontrolled permission or a missed deadline.

## Write-back into the decision path

The point of this design is that `guardian.py` and `rulebook.py` stay exactly as pure and deterministic as they are today — only the object that feeds them changes:

- `MerchantHistory.approved` (currently a plain `Counter`) is read through a thin overlay: prefer a fresh value from the hot-context store; if the store is missing, stale, or unreadable, fall back to the untouched static CSV `Counter` — today's exact behavior, unchanged.
- `approved_spend_in_period_chf` / `recent_attempt_count_10m` follow a `None`-means-unknown convention. Unavailability doesn't invent a new code path — it routes straight through guardian's *existing* `review`/threshold-sentinel branches ([guardian.py:92-94](live_layer/guardian.py#L92-L94), [guardian.py:119-124](live_layer/guardian.py#L119-L124)).

Net effect: the write-back loop is real (a card's own recent activity measurably changes what its next authorization sees), but it is layered on top of the current deterministic core rather than replacing any of it, and every read on the hot path stays local, synchronous, and safe to fail.

## Runtime: local PyFlink, no cluster

Run both jobs as plain local processes using PyFlink's DataStream API against an embedded mini-cluster (`python3 hot_context_job.py`) — this is genuine Apache Flink (keyed state, event-time watermarks, windows/timers), not a stand-in, just without a standalone JobManager/TaskManager deployment. The event source is Flink's native `FileSource` with continuous file monitoring against the JSONL outbox — no Kafka or Redpanda needed at this scale.

A Docker-based cluster with a web UI (checkpoint graphs, backpressure visualization) is a reasonable later upgrade for demo polish, but is out of scope for this document — it adds operational value, not architectural value, and nothing here depends on it.

## Why this is proportionate, not overkill

The live demo path is a single synthetic authorization end to end — no streaming engine is needed to process one event, and Flink deliberately never sits in that path. But `authorization_history.csv` has 4,701 rows, and computing familiarity/spend/velocity continuously over that volume, with event-time correctness and idempotent replay, is a legitimate stateful-streaming problem — exactly what Flink exists for. Replaying that file through the pipeline and showing it converges to the same trusted numbers the static snapshot already produces (the "26" check above) is the most direct way to demonstrate the continuous version is trustworthy, not just novel.

## Non-goals / risks

- Flink, Neo4j, and the hot-context store are never in the synchronous authorization call graph. `guardian.py`/`rulebook.py`'s only new dependency is a local, synchronous, try/except-guarded read — no network call, no JVM call, no blocking on a Flink checkpoint.
- A Flink job crash, a stale or missing hot-context store, or an unreachable Neo4j container must degrade to the existing conservative fallback — never silent approval, never blocking past the deadline.
- Historical `status` from the replayed CSV is used only as a volume generator for the streaming pipeline, never as a fraud label or expected decision — consistent with the data pack's own guidance, already honored elsewhere in this repo ([TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md](TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md#the-decision-graph-of-evidence-not-a-graph-model-of-authority)).
- This document scopes only the streaming/feedback-loop layer. It does not build the full `MandateVersion`/`PolicyRule`/`RuleCheck`/`Evidence`/hash-chained-receipt ledger — that is separate work `TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md` already scopes on its own.

## Sources and repository evidence

- [live_layer/guardian.py](live_layer/guardian.py) — the existing deterministic evaluator and its static `MerchantHistory` snapshot.
- [live_layer/rulebook.py](live_layer/rulebook.py) — where the period-spend check is currently wired but never populated.
- [live_layer/viseca_mock.py](live_layer/viseca_mock.py) — the mock API, its `record_decision`/`next_request` seams, and today's hardcoded placeholders.
- [live_layer/test_viseca_mock.py](live_layer/test_viseca_mock.py) — the existing familiarity-count assertion used here as a correctness check.
- [kg_layer/README.md](kg_layer/README.md) — current, unwired Neo4j container.
- [TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md](TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md) — the Consent & Evidence Graph ontology, outbox pattern, and trust-boundary rules this document builds on.
- `git show c0ea2f6^:kg_layer/knowledge_graph/` — the deleted prior design (Cypher schema, Redis rolling-window Lua script) recoverable as a reference for constraints and eviction logic.
