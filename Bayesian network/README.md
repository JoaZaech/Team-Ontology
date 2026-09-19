# Bayesian network

An offline implementation of PLAN.md: timestamp-correct evidence snapshots,
exact Bayesian inference, expert-parameter sensitivity, fail-safe decisions,
immutable receipts, and authenticated local human-resolution demonstrations.

**Open `build/index.html`** for the portable transaction drill-down. It is
self-contained and works without a server or internet connection. Search
`TR03359` to inspect the earlier example. Select any purchase to view its
feature states, posterior influence, sensitivity and eligible source IDs.

These are contextual-anomaly estimates, not fraud probabilities or explanations
of why an issuer declined. Historical approved and declined outcomes are used
only to describe the original result; they are not training labels. Only past
approved purchases contribute to familiarity/amount summaries. The present
transaction's original outcome never enters its feature snapshot.

## Run

From this directory, using the existing graph environment:

```sh
../Knowledge_graph/.venv/bin/python -m unittest discover -s tests -v
../Knowledge_graph/.venv/bin/python -m bayesian_network.demonstrations
../Knowledge_graph/.venv/bin/python -m bayesian_network.replay
../Knowledge_graph/.venv/bin/python -m bayesian_network.verification
```

Python 3.9+; runtime reuses the sibling Knowledge_graph package. The graph's
requirements.txt supplies jsonschema for fixture validation and contract tests.
No Bayesian dependency, training download, service or cloud account is needed.

Replay produces `build/index.html`, `report.json`, `summary.json`, and a new
`receipts-<run-time>.sqlite` audit database. Demonstrations produce
`demonstrations.json` and a separate demo database. Each run preserves older
receipt databases; no receipt is rewritten. The HTML and JSON are shareable;
SQLite runtime databases are excluded from Git. Full receipts include facts,
versions, provenance, feature definitions, hashes and influence explanations.
The `source_facts` table preserves every referenced source version by content hash.
The summary names its corresponding database. HTML contains compact receipts.

To inspect a complete receipt, query the database's `receipts` table by `scope`
(the report JSON includes it). Customer outcomes append to `resolutions`;
`spends` contains exactly one row per approved request; `revocations` prevents
subsequent approval under the revoked authority. Test keys are ephemeral.

## Code organization

| File | Responsibility |
|---|---|
| `config/contracts.schema.json` | Machine-readable request, fact, model, feature, receipt and resolution contracts |
| `config/model.json` | Versioned expert priors, exhaustive CPTs and threshold policy |
| `bayesian_network/configuration.py` | Configuration and feature binding validation |
| `bayesian_network/evidence.py` | Scoped, versioned bitemporal adapter; reuses graph summary calculations |
| `bayesian_network/inference.py` | Exact inference, sensitivity, leave-one-observation-out influence |
| `bayesian_network/policy.py` | Hard-rule precedence, fail-safe orchestration and receipt hashes |
| `bayesian_network/receipts.py` | Transactional immutable audit storage and idempotency |
| `bayesian_network/human.py` | Authenticated demo resolution and authority revocation |
| `bayesian_network/demonstrations.py` | Eight synthetic acceptance demonstrations |
| `bayesian_network/replay.py` | Historical/scenario replay, independent recomputation and provenance checks |
| `bayesian_network/verification.py` | Independent persisted receipt/schema/hash/source/temporal checks |
| `bayesian_network/reporting.py` | Offline HTML generator and drill-down interaction |
| `tests/test_network.py` | Temporal, inference, contract, failure, storage and resolution tests |

## Scope and limitations

- Historical replay covers all 4,565 purchases, including originally approved and
  declined purchases. The 136 cash/refund events contribute appropriate prior
  context but are outside the purchase target population.
- Fixtures have no actual knowledge timestamps. Replay explicitly assumes
  event-time availability and fixture completeness. Strict mode rejects this
  assumed provenance. It requires actual ingestion timestamps and current,
  scoped coverage supplied by an external trusted source.
- Historical eligibility is an analytical assumption. SCEN0001 reuses existing
  simulation hard rules; other scenario mandates are uncompiled and step up.
- Exact repeatability is checked both with same-key retries and independent
  recomputation. Timing is measured separately; no production SLA is claimed.
- The threshold and sensitivity scenarios are prototype expert choices. No
  labeled anomaly/fraud validation or calibration has been performed.
- Human HMAC authentication demonstrates the binding/state machine. Production
  identity, complete authoritative policy adapters, operational ingestion and
  deployment remain integration work. `live_layer` is untouched.
- Ordinary database writes cannot mutate receipts; host administrator tamper
  resistance requires an external immutable audit service.

See MODEL.md for operational target semantics and dependence assumptions, and
data.md for the underlying fixture/time contract. Future labeled evaluation
must use chronological splits and hold out complete customers/cards.
