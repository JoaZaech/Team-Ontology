# KG_Rootcause baseline

A portable source graph, historical evidence index, deterministic explanation
builder, and audited ten-request replay of SCEN0001. It is independent of
`live_layer` and does not authorize real payments.

## Run

From `Knowledge_graph` with Python 3.9 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s kg_rootcause/tests -v
.venv/bin/python -m kg_rootcause
```

The command accepts `--data /path/to/data` and `--output /path/to/build`.
Open `build/evidence_viewer.html` directly in a browser; it is self-contained
and makes no network requests. Choose a request and evidence path to inspect
real graph nodes, relationship direction, source records, and checks.

## Components and contracts

- `ingestion`: validates all eleven supplied CSV contracts, keys, ownership,
  related records, scenario order, timestamps, currency conversion, and baskets.
  Empty optional values become null; `unknown` and `not_applicable` stay distinct.
- `schema/contracts.schema.json`: Draft 2020-12 JSON Schema definitions for
  snapshots, nodes, relationships, provenance, semantic drafts, confirmed-policy
  inputs, contexts, guardrail checks, explanations, simulation results and reports.
  Every emitted context, explanation, result and report is validated.
- `precompute`: complete source graph, grouped historical summaries with
  supporting IDs, and a card-partitioned temporal history index.
- `semantic`: thirteen initial deterministic concept mappings and conservative
  phrase extraction. Extracted drafts remain unconfirmed and cannot authorize.
- `context`: linked identities, basket, authority, temporary transaction overlay,
  semantic matches, evidence gaps and exclusive-cutoff historical aggregates.
- `explanation`: hard failures precede unknown evidence and uncertainty; passing
  checks become counter-evidence when a decision is adverse. Failed checks are
  never counter-evidence. Connected graph paths carry source provenance.
- `simulation`: isolated run state and an explicit SCEN0001 simulation policy.
- `frontend_contract`: path/reference auditing and the offline evidence viewer.

All monetary fields inside the component use integer minor units. Existing
source names are retained: `billing_amount_chf=12000` means CHF 120.00, and
`unit_price=650` means 6.50 in that line's currency. FX conversion uses Decimal
and half-even rounding. Raw CSV files are never modified.

## Baseline policy and state

The simulation policy interprets SCEN0001 as grocery-category items, delivery,
CHF 120 maximum per order including delivery, and CHF 300 over the preceding
seven days including the proposed order. Grocery-category-only is an explicit
simulation interpretation, not a customer-confirmed mandate. Missing evidence,
an unfamiliar merchant, or a link to an already approved purchase triggers
step-up unless a hard rule fails. These are prototype uncertainty checks,
not a fraud model or the unfinished live guardrail.

The rolling interval includes its lower boundary and excludes the current
instant: `[timestamp - 7 days, timestamp)`. Spend is scoped to the authority's
approvals in this run. Step-up adds a pending attempt but no approved spending
or familiarity. Declines remain attempt evidence. Applying the same decision
ID twice makes no second state update; the replay runner rejects duplicate
request IDs and out-of-order input.

Historical familiarity counts only approved purchases, not refunds or cash
withdrawals. Net historical spending includes approved negative refunds.
Recent-attempt summaries include every status. Candidate duplicate/retry lists
are deliberately broad, merchant-matched candidates within ten minutes, not
assertions that two baskets are identical. Historical fixture counters are not
used as precomputed truth; evidence is recalculated from source rows.

## Outputs and audit

`build/` is generated and ignored by Git:

- `data_quality_report.json`, `source_graph.json`, `graph_validation_report.json`
- `precomputed_evidence.json`, `historical_evidence_index.json`, `ontology.json`
- `semantic_policy_draft.json`
- `simulation_results.json`, `replay_results.json`
- `latency.json`, `replay_latency.json`
- `baseline_report.json`, `baseline_report.md`, `evidence_viewer.html`

Replay equality covers every business result: inputs, context, checks,
explanations, highlights, and state before/after. Wall-clock latency is separate
telemetry and cannot be byte-identical between runs. Latency includes context,
explanation, state update and schema validation; excludes ingestion and graph
construction. p95 uses the nearest-rank method.

A baseline pass requires ten results, zero detected future evidence, zero invalid
references, zero duplicate state updates, complete explanations and 100% replay
agreement. Reference audits verify connected paths and actual source records.
Coverage means a context has no declared missing evidence; it is not a measure
of real-world risk coverage. Evidence contributions use explicit equal weights
among active explanation checks, rounded to basis points with residual assigned
to the last check. The hard-failure set determines 100% of a decline decision.
Weights are explanatory, not calibrated probabilities or fraud causation.

## Boundaries and next steps

Automated checks cover checkpoints A–G in the attached plan. For checkpoint H,
the offline viewer is supplied; visual browser verification was blocked by the
local browser URL policy. The complete graph
contains all 45 source attempts, but only SCEN0001's ten requests are evaluated.
Other scenarios require their own explicit policies; the baseline policy must
not silently be applied to them. The semantic compiler currently extracts
recognized phrases and amount candidates; it flags unresolved scope and clauses
instead of claiming to compile arbitrary natural language.

The temporal index excludes equal/future event times and isolates scenario runs.
End-of-history materialized summaries are for inspection; earlier cutoffs are
computed from the indexed source rows. Retrieval is not yet a bounded prefix
aggregate query. Static catalogue records have no effective-date history, so
catalogue states cannot be reconstructed at historical dates. Source provenance
uses the pack's fixed-rate date as its snapshot convention; it is not a claim
about when a production system learned a record. Historical billing evidence
uses supplied billing amounts, not a lookup of future-dated FX records.

Runtime proofs, step-up resolution, general unseen-transaction ingestion, a real
frontend adapter, production storage, 45/100/1,000-request expansion, and the
future live-layer adapter remain subsequent work. No graph database or model is
selected by this baseline.

## Interactive precomputed explorer

The in-conversation explorer now has a reproducible builder:

```sh
.venv/bin/python -m kg_rootcause.frontend_contract.explorer --output build/precomputed-explorer.html
```

`frontend_contract/explorer.py` assembles the data;
`frontend_contract/knowledge_explorer.html` contains the visual layout and
interactions. The generated file is an inline visualization fragment, distinct
from the standalone `build/evidence_viewer.html` simulation viewer.

Select a relationship to see its declined authorizations, recorded purchase
description, amount, timestamp, merchant, channel and card status. Historical
records have no per-event decline-reason field. The explorer marks the reason
as unavailable and shows exclusively prior evidence as context, not causation.
The five SCEN0001 simulated declines appear separately with actual failed checks.
