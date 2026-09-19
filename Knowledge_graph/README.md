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

`build/` is generated. Review pages and decline-audit outputs are tracked; large intermediate files are ignored:

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

## Rebuild the graph and all saved reports

```sh
.venv/bin/python -m kg_rootcause.reports --rebuild
```

This single command validates source data, builds the graph and baseline,
runs the historical decline audit, and renders self-contained browser pages.
It requires no Codex installation, plugin files, network access, or temporary
scripts. Omit `--rebuild` to reuse existing graph outputs; the audit verifies
that they still match the source dataset.

Open `build/index.html` for all report links:

- `build/precomputed-knowledge-graph.html`: all-card graph explorer.
- `build/tr03359-reason-review.html`: same explorer focused on TR03359.
- `build/decline_audit/decline_smoke_report.html`: all historical decline traces.
- `build/decline_audit/decline_case_traces.json`: machine-readable case evidence.
- `build/decline_audit/decline_case_index.csv`: compact case index.
- `build/README.md` and `build/report_manifest.json`: output-to-source mapping.

The browser-ready review pages, report index, manifest, and decline-audit outputs
are tracked in Git so teammates can open them after cloning. Large graph JSON
intermediates, latency outputs, and the virtual environment remain ignored.
Edit source code and templates, regenerate, then commit the updated pages.
The graph's JavaScript, CSS, and data are embedded in each generated HTML file;
there is no separate runtime script to look for inside `build/`.

## Source structure

```text
kg_rootcause/
  reports.py                         # One command to generate all reports
  audit/
    factors.py                       # Diagnostic names and classifications
    tracing.py                       # Pure timestamp-correct case analysis
    runner.py                        # Graph/aggregate checks and cohort counts
    declines.py                      # Backwards-compatible audit CLI
  reporting/
    declines.py                      # Audit HTML/JSON/CSV/Markdown export
    html.py                          # Self-contained graph page wrapper
  frontend_contract/
    explorer.py                      # Data payload and graph rendering CLI
    templates/knowledge_explorer.html # Graph page markup, not a runnable page
    assets/explorer.js               # Draws nodes/edges; click and drill-down logic
    assets/explorer.css              # Graph-specific styling
    assets/standalone.css            # Portable page theme and control styles
```

The explorer uses the same `audit/tracing.py` logic as the decline report.
First-merchant notes are computed from source records and an exclusive cutoff;
there is no hard-coded TR03359 explanation in the page. A focused report is
just a renderer option:

```sh
.venv/bin/python -m kg_rootcause.frontend_contract.explorer \
  --authorization TR03359 --output build/tr03359-reason-review.html
```

The explorer CLI generates standalone HTML by default. Use `--format fragment`
only for an in-conversation visualization host that supplies theme styles.

## Historical decline smoke test

```sh
.venv/bin/python -m kg_rootcause.audit.declines
```

The read-only audit checks every historical decline against source graph
connections and strictly earlier records. It compares stored aggregates with
fresh calculations and checks merchant/device/category/country counts, p95,
and recent attempts independently. The report separates observable rule
conflicts, behavioral context, and unexplained cases. It includes approved
purchase comparison counts to avoid treating a common behavior as a proven
cause. Thresholds are explicit; original issuer reason codes remain unavailable.
No historical outcomes are changed and no new authorization decisions are made.
