# SCEN0001 baseline

Simulation policy only; no expected decisions are supplied by the dataset.

| Metric | Result |
| --- | --- |
| request_count | 10 |
| approve_count | 5 |
| step_up_count | 0 |
| decline_count | 5 |
| average_evaluation_latency_ms | 105.949 |
| p95_evaluation_latency_ms | 170.257 |
| context_coverage_percent | 100.000 |
| explanation_completeness_percent | 100.000 |
| valid_provenance_path_percent | 100.000 |
| missing_evidence_count | 0 |
| future_leakage_count | 0 |
| deterministic_replay_percent | 100.000 |
| invalid_graph_reference_count | 0 |
| duplicate_state_updates | 0 |
| baseline_passed | True |

## Decisions

| Request | Decision | Cause |
| --- | --- | --- |
| AU0002 | approve | maximum_order, rolling_budget, item_category, delivery, card_active, authority_active, required_evidence, related_approved_purchase, merchant_familiarity |
| AU0003 | approve | maximum_order, rolling_budget, item_category, delivery, card_active, authority_active, required_evidence, related_approved_purchase, merchant_familiarity |
| AU0004 | decline | maximum_order |
| AU0005 | approve | maximum_order, rolling_budget, item_category, delivery, card_active, authority_active, required_evidence, related_approved_purchase, merchant_familiarity |
| AU0006 | approve | maximum_order, rolling_budget, item_category, delivery, card_active, authority_active, required_evidence, related_approved_purchase, merchant_familiarity |
| AU0007 | decline | rolling_budget, item_category |
| AU0008 | decline | rolling_budget |
| AU0009 | decline | rolling_budget |
| AU0010 | decline | maximum_order, rolling_budget |
| AU0011 | approve | maximum_order, rolling_budget, item_category, delivery, card_active, authority_active, required_evidence, related_approved_purchase, merchant_familiarity |

## Limitations

- Synthetic data; simulation policy is an explicit interpretation of SCEN0001, not a confirmed mandate or expected-decision answer key.
- Source graph contains all fixtures; context evidence reads only prior history and this run's earlier decisions.
- Static catalogue validity cannot be reconstructed without effective-date records.
- Semantic extraction is a conservative draft, not a complete natural-language policy compiler.
- Index is card-partitioned; aggregates scan the time-filtered card history. No bounded prefix aggregates or production latency target yet.
- No fraud model or live-layer integration. Step-up resolution is not implemented.

Every business output compared recursively, including context, checks, explanation, highlights, and before/after state. Measured wall-clock latency is separate non-deterministic telemetry.
