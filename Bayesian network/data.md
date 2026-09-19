# Bayesian network — data and temporal contract

Status: the purchase-context adapter is implemented in bayesian_network/evidence.py.
MODEL.md defines the implemented feature subset and explicit fixture assumptions.
The broader integration requirements below remain applicable to future inputs.

Use the same immutable eleven-CSV pack as the knowledge graph. The source
inventory is [Knowledge_graph/data.md](../Knowledge_graph/data.md); authoritative
field semantics are in the [data dictionary](../viseca-2026/data/data_dictionary.md).
Do not copy or alter the raw CSVs. This document specifies how the Bayesian layer
must consume their evidence.

## 1. Inputs and responsibilities

| Input | Use | Restriction |
| --- | --- | --- |
| authorization_history.csv | Prior behavioral evidence and recorded outcomes | Current outcome is excluded from model inputs; outcomes are not anomaly/fraud labels |
| customers, accounts, cards | Identity joins and policy/lifecycle context | Current catalogue values are not proof of past state |
| merchants | Merchant identity/category/country | Join by ID, not name; country does not determine billing currency |
| items, purchase_attempt_items | Scenario basket facts | Historical authorizations have no structured basket; free text is untrusted |
| purchase_attempts | New requests and ordered scenario replay | Future attempts must not enter current context |
| scenario_authorities, scenario_catalogue | Authority scope, validity and scenario metadata | Instructions require an explicit policy; catalogue is not expected decisions |
| fx_rates | Supplied fixed-rate conversion convention | Rates dated 2026-08-01 do not prove availability before that date |

The graph provides a timestamp-specific feature snapshot; the Bayesian network
consumes it. The model must not consume an unfiltered final graph or final
end-of-history aggregates to score an earlier transaction. Raw records are used
for ingestion and independent verification, not a second competing evidence score.

## 2. Four distinct times

| Field | Meaning |
| --- | --- |
| event_time | When the source activity happened; historical CSV timestamp |
| transaction_time | Event time of the transaction currently being evaluated |
| known_at | When this fact/version became available to this system |
| decision_time | When the decision snapshot was fixed |

For prior behavioral evidence, require both:

```text
event_time < transaction_time
known_at <= decision_time
```

Parse timezone-aware timestamps and normalize to UTC. Reject naive/malformed
timestamps. Do not use string order for timestamps with differing offsets.
Use explicit half-open intervals for activity windows:

```text
transaction_time - 10 minutes <= event_time < transaction_time
```

Apply the known_at filter in addition to the event-time window. The current
request is a separate observed input, not a historical event contributing to
its own familiarity, amount distribution, or velocity.

### Example: transaction_time 10:00, decision_time 10:00:02 UTC

| Evidence | event_time | known_at | Eligible? |
| --- | --- | --- | --- |
| Earlier purchase | 09:50 | 09:51 | Yes |
| Delayed earlier purchase | 09:50 | 10:01 | No: learned after the decision |
| Simultaneous purchase | 10:00 | 10:00:01 | No: equal event time |
| Future activity | 10:05 | 10:00:01 | No: event time is in the future |

Ordering by (timestamp, authorization_id) makes replay deterministic, but does
not make an equal-timestamp record eligible. Process same-event-time groups
against the same historical cutoff.

## 3. What is missing from this dataset

The fixtures do not supply genuine per-record known_at timestamps. File modified
time, Git commit time, metadata dates, and graph source_as_of are not substitutes.
The existing graph adapter currently enforces event-time cutoffs, not a complete
bitemporal contract.

Support two clearly labeled modes:

- Strict ingestion: record actual known_at for each fact/version as it arrives.
  A request, authorization result, and later resolution may have different
  knowledge timestamps. Earlier approved behavior is usable only once that
  approval is known. New historical imports are known now, not retroactively.
- Synthetic retrospective replay: use a versioned, explicit availability
  assumption, for example event-time availability of historical records. Mark
  known_at_basis=assumed_event_time and preserve the assumption in every receipt. This is
  not evidence that outcomes were actually available instantly.

Static catalogue validity also needs explicit assumptions for synthetic replay.
Where a required historical fact cannot be reconstructed, report missing evidence
and step up rather than silently using today's value.

## 4. Static facts and corrections

Static policy/lifecycle facts need effective_from/effective_to plus known_at.
Choose the fact version effective at transaction_time and known by decision_time.
Use the recorded card_status at the historical event where supplied, rather
than cards.csv's current status. Do not assume other catalogue attributes have
complete historical validity just because a row exists.

Corrections append new fact versions with their own known_at. Preserve the
snapshot and receipt used for the original decision. Re-evaluation creates a
new linked decision version; it does not rewrite the past.

## 5. Feature definitions

The first implementation scores card-level merchant, device and country novelty,
amount atypicality and combined eligible card attempt velocity. Customer-level
familiarity, category novelty and spending are not additional Bayesian inputs;
authority spending remains in the existing scenario hard-rule adapter. Runtime
source IDs retain the TR/AU distinction.

| Feature | Eligible historical population | Missingness/scope |
| --- | --- | --- |
| Merchant familiarity | Earlier approved purchases on the same card and merchant | Separately expose customer-level familiarity; do not merge scopes |
| Device familiarity | Earlier approved purchases on the same card and nonempty device ID | Device absent on a device-free channel is not_applicable, not novel |
| Country/category novelty | Earlier card activity in that country/category | Define whether novelty means no encounters or no approved purchases |
| Amount atypicality | Earlier approved purchases, excluding refunds and cash withdrawals | Require a versioned minimum sample size; normalize currencies consistently |
| Velocity | Earlier attempts in the explicit window, regardless of outcome | Keep historical-card velocity and same-run scenario velocity separately named |
| Spending | Earlier approved transactions within the declared account/card/authority period | Negative approved refunds reduce spend; pending and declined attempts do not add spend |

Distinguish observed_novelty, history_unavailable, insufficient_history,
not_applicable, and observed values. Record coverage and sample size. A zero
count without coverage evidence is not proof of novelty. All novelty is within
the supplied observation window, not lifetime knowledge.

The existing CSV approved_*_before fields are not directly interchangeable with
our features: their ordering is (timestamp, authorization_id), and their approved
counts may include event types excluded from purchase-only familiarity. Recompute
using the Bayesian feature contract. approved_spend_before_chf is lifetime
card spend, not monthly account spend.

## 6. Money and labels

Use integer minor units and Decimal half-even conversion, consistent with graph
ingestion. Existing internal *_chf values are CHF cents; document this in the
adapter rather than feeding ambiguous units into the model. Historical supplied
billing_amount_chf can be retained as a recorded fact under the chosen availability
mode. It must not be described as a historically available future FX lookup.

Never feed the evaluated row's approved/declined status, future resolution,
future chargeback, or final simulation decision into its model features.
Do not train or validate an anomaly/fraud target against historical approvals
and declines. Replay both outcomes; present them only as observed comparisons.

## 7. Scenario time, run isolation, and decisions

Scenario authorization.timestamp is simulated event time. runtime.received_at
and deadline_at use the operational clock. Keep these time domains labeled:
use event time for behavioral windows and operational time for availability and
deadlines in a live run. Synthetic retrospective decision times require their
own declared convention; do not silently mix replay time and wall-clock time.

Scope mutable evidence/state to tenant and run, then card/customer/authority
as the feature definition requires. Historical TR records and scenario AU records
remain separate namespaces. An earlier AU from another scenario/run must not
enter the current run merely because it appears in the full source graph.

A step-up is pending. It adds neither approved spending nor purchase familiarity.
Approval can contribute only after its resolution is known, and only to later
event-time queries satisfying both temporal filters. Reject/revoke resolutions
never create approved-purchase evidence. Duplicate processing must not double
count a request or resolution.

## 8. Feature snapshot and receipt fields

At minimum retain:

```text
transaction_id, tenant_id, run_id
transaction_time, decision_time
snapshot_id, snapshot_hash
feature_definition_version, discretization_version
feature_value, evidence_state, sample_size, coverage_window
source_record_ids, source_version_ids
event_time, known_at, known_at_basis
model_version, model_hash, configuration_hash, decision_policy_version
```

Derived facts retain their supporting source versions and calculation lineage.
No derived availability timestamp may hide a later-known dependency. Persist
exact input feature values/hashes for reproducible replay rather than reading
whatever the latest graph contains.

## 9. Required temporal tests before inference integration

- Current/future events and equal event timestamps are excluded.
- Earlier events learned after the decision are excluded.
- A fact learned exactly at decision_time is eligible if event_time is earlier.
- Different timezone offsets yield the same UTC eligibility.
- Late approval/resolution does not retroactively establish familiarity.
- Catalogue corrections do not change prior snapshots.
- Cross-run and cross-customer evidence does not leak across scopes.
- Missing history, insufficient history, and observed novelty remain distinct.
- Retries return the original receipt without duplicate state updates.
- Fixture results disclose assumed availability and cannot claim verified
  historical bitemporal correctness.
