# Expert model and temporal contract

This is an offline advisory prototype. It estimates an expert-defined **material
context departure** for purchase requests, relative to the same card's approved
purchases in the preceding 90 days. It is not a fraud model, a reconstruction of
issuer reasoning, or a calibrated measure of real-world anomaly frequency.

Examples included in this event: an amount exceeding 1.5 times the prior p95,
a previously unseen merchant combined with an unfamiliar session, or at least
three prior attempts in ten minutes. A routine purchase with familiar merchant,
country, device and amount is counter-evidence. Missing history, a historical
decline, a hard-rule breach, and device absence on a device-free channel are not
anomaly observations. Sparse histories require step-up. Novelty means no approved
matching purchase in a sufficiently covered observation window; it does not mean
that the customer has never interacted with that merchant anywhere.

The reference sample requires five approved purchases and seven days of declared
coverage. Coverage is an explicit scoped input, with provenance and freshness;
a list of rows alone cannot establish completeness. Optional device evidence is
marginalized when missing or not applicable. Required evidence is merchant,
amount, country and velocity. At present this model is supported for purchases;
other event types contribute to eligible attempt velocity but are not scored.

## Expert dependence assumptions

The committed `config/model.json` contains all normalized binary CPT rows. States
0 and 1 mean ordinary/novel-or-atypical for observed features, and false/true for
latent anomalies. The DAG is:

- merchant → country; merchant and country → device; merchant → amount;
- device, country and velocity → session;
- merchant, amount and session → anomaly.

Novel contexts are correlated in the root feature distribution. Country/device
co-occurrence uses a capped maximum plus a small interaction, not two independent
likelihood multipliers. Session indicators reach the target only through session.
Amount and merchant interact through their joint CPT. Velocity is an independent
root assumption. These are explicit expert assumptions, not demonstrated causal
relationships. Shared source IDs are retained for review. Duplicate node names
and duplicate parents are rejected. Tests bound the chosen country/device bundle
increment; this is a regression guard, not proof of absence of all double-counting.

The baseline and two scenarios vary root and conditional anomaly probabilities
coherently by 0.8 and 1.2 with declared caps. This finite scenario set is parameter
sensitivity, not a posterior distribution over parameters. Approve only if **all**
scenario posteriors are below 0.35. Equality steps up, using unrounded binary64
values. This conservative prototype threshold trades additional human review
for fewer approvals under parameter variation; no optimality claim is made.

Influence = P(anomaly | all observed evidence) minus P(anomaly | all evidence
except this feature), integrating the omitted feature over the full joint model.
Signed deltas overlap, are not additive causal shares, and can show counter-evidence.

## Availability and scope

Facts append versions with immutable hashes. Select the newest version known by
decision time, then apply exclusive event-time, tenant, run, customer and card
filters. Equal event timestamps never enter history. Known-at equality is allowed.
UTC-aware timestamps are mandatory. Effective static versions use [from,to).
The model consumes country/channel/amount supplied in the current validated request;
it does not backdate today's card or merchant catalog status into prior decisions.

Synthetic fixture replay assumes each historical outcome was known at its event
time and assumes complete fixture coverage from its start through each decision.
Both assumptions are marked, never asserted as genuine ingestion history. Strict
mode requires actual ingestion timestamps on facts and coverage. Importing old
rows now cannot make them available to a decision in the past.

## Rules, storage and identity integration boundaries

The decision service accepts request-bound results from a trusted authoritative
rule evaluator. Historical replay supplies an explicitly analytical eligibility
assumption, not a historical issuer decision or a live payment permission.
Production integration must supply authenticated complete mandatory checks and
historically valid authority facts. No code is connected to live_layer.

SQLite records receipts, spends, human resolutions and revocations transactionally.
Triggers prevent ordinary update/delete; this is local append-only integrity, not
protection against a host administrator. Same-key retries pin the first snapshot;
changed request/rule/config hashes conflict. For re-evaluation use a new key and
`supersedes_scope` pointing to the earlier receipt. Storage failure cannot emit
approval, returns a nonpersisted recovery response, and requires a same-key retry.
Wall-clock telemetry is deliberately excluded from hashed receipts.

The human demonstration authenticates signed customer events with local test keys.
Production identity provisioning, transport, expiry/replay controls and trusted rule
adapter deployment are external integration work. Approval invokes current mandatory
policy/authority rechecks inside the storage transaction. Reject/revoke never add
spending. Revocation blocks pending and subsequent decisions using that authority.
An already approved request cannot be retroactively revoked by this pending-request
API. Pending decisions never become purchase familiarity automatically.
