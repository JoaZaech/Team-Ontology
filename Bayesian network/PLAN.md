# Bayesian network implementation plan

Status: implemented as an offline expert prototype. See README.md for commands,
MODEL.md for assumptions and integration boundaries, and build/index.html for the
replay drill-down. Live deployment, real ingestion provenance, independently
labeled calibration and uncompiled scenario mandates remain outside this milestone.

## 1. First milestone and target event

For one rule-eligible transaction, construct an auditable feature snapshot,
run a versioned Bayesian network, and produce an approve or step-up
recommendation with an immutable decision receipt. Hard rules remain authoritative.

The model output is:

`P(transaction_context_is_anomalous = true | eligible evidence)`

This is an expert-defined contextual anomaly event: the transaction's merchant,
amount, or session context departs materially from the documented reference
behavior represented by the feature definitions and conditional probability
tables (CPTs). Before implementing inference, define the event's inclusion and
exclusion examples and the reference population in the model specification.
The node name alone is not an operational definition. Missing evidence is not
itself an observed anomaly.

This probability is neither fraud probability nor probability of policy
noncompliance. Until an independent labeling protocol and validation data exist,
it is an expert-model posterior, not an empirically calibrated probability.
Historical authorization outcomes are never fraud labels or model ground truth.

Report parameter sensitivity separately: recompute the posterior over a fixed,
versioned set of coherent expert-prior/CPT configurations. Report the baseline,
minimum, maximum, and whether the recommendation changes. Call this a
parameter-sensitivity range, not a confidence or credible interval. A genuine
Bayesian parameter-uncertainty interval would require distributions over the
parameters and a separate inference specification.

## 2. Processing order

1. Normalize and validate the request.
2. Evaluate authoritative hard rules.
3. Check required-evidence availability.
4. Build the bitemporal feature snapshot.
5. Run versioned Bayesian inference within a bounded deadline.
6. Apply the prototype posterior-to-recommendation policy.
7. Persist an immutable explanation/decision receipt before emitting a result.

A known hard-rule violation always declines, regardless of model availability
or output. Other paths may approve or step up. No weighted average combines
rule, graph, and Bayesian scores. The graph is an evidence provider, not an
independent voter. A transaction is rule-eligible until the final decision.

## 3. Evidence states

Represent evidence state separately from feature value:

- observed: sufficient eligible history supports the measured feature value;
- observed_novelty: an available, adequately covered history contains no prior
  matching relationship; novelty is relative to that observation window;
- history_unavailable: the source or snapshot cannot be retrieved or trusted;
- insufficient_history: the available sample or coverage cannot support the
  specified feature or discretization;
- not_applicable: the feature has no meaning for this transaction, such as a
  cardholder device on a supported device-free channel.

Zero matching events must not automatically imply sufficient coverage. Record
sample size, coverage window, freshness, and the reason for missingness.
Unknown enum values are contract errors, not new states and not zero-risk values.
Each feature specification declares which states require step-up and which
optional missing states can be marginalized by the network.

## 4. Bitemporal evidence contract

Each source fact or version needs event_time and known_at. A fact is eligible
only if:

- event_time < transaction_time;
- known_at <= decision_time;
- its tenant, customer/card scope, and run scope match the request.

Record snapshot ID, immutable source record/version IDs, transaction_time,
decision_time, observation window, and feature calculation version. Static facts
require effective validity intervals and knowledge timestamps rather than an
invented transaction event time. Corrections append new versions; they never
rewrite the prior receipt's snapshot.

Equal event timestamps are excluded even if delivery order differs. Define a
stable tie-break order for storage/replay without letting that order bypass the
strict event-time cutoff. Known-at equality is allowed.

### Existing-data limitation

The supplied CSV pack has event timestamps but no genuine per-record known_at
history or full effective-date catalogue history. The graph's source_as_of field
is not a substitute for known_at. We cannot certify historical bitemporal
correctness from these fixtures alone.

Provide two explicit modes:

- strict ingestion mode: record real ingestion/knowledge timestamps and reject
  requests whose required facts were not known by decision_time;
- synthetic retrospective mode: assign a documented availability convention,
  mark known_at as assumed, and label outputs as synthetic temporal replay.

Synthetic tests with late-arriving facts and corrections validate the machinery;
they do not establish that historical fixture availability was real.

## 5. Network and dependence design

Initial candidate structure:

- device novelty, velocity, and country novelty -> session anomaly;
- merchant novelty, amount atypicality, and session anomaly -> transaction
  context anomaly.

This is a design candidate, not a justified independence claim. Document each
node's meaning, states, parents, and conditional independence assumptions.
Construct joint CPTs for interacting parent combinations, inspect shared source
support, and review whether additional dependencies are needed. Do not multiply
independent likelihoods for correlated history-derived signals. A DAG alone
does not establish that double-counting has been prevented.

Do not feed the same raw session indicators into both the session node and the
transaction node without an explicit dependence rationale. Test duplicate signals,
correlated feature bundles, and redundant evidence for posterior overstatement.
Keep the model small enough for exact inference and exhaustive CPT validation.

## 6. Versioned contracts and configuration

Define machine-readable contracts for:

- normalized request and authoritative rule result;
- bitemporal fact and feature snapshot;
- Bayesian model specification, priors, CPTs, and validation report;
- posterior result and parameter-sensitivity range;
- posterior-influence explanation;
- immutable decision receipt and step-up resolution event.

Version/hash feature definitions, discretization thresholds, model structure,
priors/CPTs, input snapshot, decision policy, and inference implementation.
Every result records those versions and hashes. Reject non-finite probabilities,
invalid states, missing CPT rows, inconsistent dimensions, and rows that do not
sum to one within an explicit numeric tolerance.

Choose the prototype step-up threshold explicitly and record its trade-offs.
It is a decision-policy setting, not a discovered correct probability. Specify
boundary equality, numeric precision, and policy behavior if the sensitivity
range crosses the threshold. No threshold may create a model-only decline.

## 7. Influence explanations

For every relevant feature show:

- value, evidence state, sample size, and temporal coverage;
- source IDs and graph path references;
- baseline posterior and posterior under a specified evidence-removal or
  alternative-value comparison;
- signed posterior delta and a plain-language interpretation;
- supporting and counter-evidence.

Define the comparison operation mathematically. Evidence removal means
marginalization, not arbitrary substitution with a normal value. Individual
posterior deltas can overlap and need not add up to the full posterior change;
do not normalize them into causal contribution percentages.

Use wording such as 'Including this evidence raises the model estimate from
0.18 to 0.42.' Do not claim that a feature caused fraud, risk, or an original
historical decline. Hard-rule decision causes are recorded separately.

## 8. Failure and idempotence behavior

On rule-eligible paths, model timeout, unavailable snapshot, invalid configuration,
unknown state, inference error, non-finite output, or missing required evidence
returns a deterministic step-up with a specific reason code. Never silently
fall back to approval. A known hard-rule violation still declines.

If durable receipt storage is unavailable, do not emit an approval; surface a
step-up/service-unavailable result through the configured response contract.
Define the audit/recovery path explicitly rather than claiming persistence when
it failed.

Use an idempotency key scoped to tenant and run. Repeating the same request and
input/configuration hashes returns its stored result without another state
mutation. Reusing a key with different content raises a conflict and cannot
approve. Retries return the original decision-time snapshot; re-evaluation is
an explicitly linked new version.

Separate deterministic result content from wall-clock latency telemetry.

## 9. Human resolution path

Demonstrate customer approve, reject, and revoke outcomes:

- approve: resolve the linked pending request after rechecking mandatory policy,
  authority validity, and transaction binding; record final approval once;
- reject: record a customer-rejected final outcome, without approved spending;
- revoke: revoke the authority and prevent pending/future requests using it from
  being approved.

Keep the original recommendation receipt immutable. Append authenticated,
linked resolution events and enforce idempotent state transitions. A pending
step-up never counts as approved spending or purchase familiarity. A customer's
approval must not override an unresolved hard-rule violation; policy changes
require an explicit separate process.

## 10. Implementation sequence

A. Contracts, anomaly-event specification, and evidence-state definitions.
B. Bitemporal graph adapter and coverage checks, with fixture limitations marked.
C. Versioned network, expert CPTs, dependence review, and configuration validator.
D. Exact inference and coherent parameter-sensitivity scenarios.
E. Decision-policy adapter, fail-safe behavior, and immutable/idempotent receipts.
F. Source-linked influence explanations and counter-evidence.
G. Human step-up resolution state machine and demonstrations.
H. Historical and scenario replay, smoke-test report, and visual drill-down.

Keep implementation outside live_layer until the contracts and demonstrations
pass. The folder is named 'Bayesian network'; use an importable package such as
bayesian_network inside it. Separate configuration, evidence adapters, inference,
policy/receipt handling, reporting, simulation, and tests. Do not duplicate graph
aggregation logic or hard-code reviewed transaction explanations.

## 11. Tests and demonstrations

Required demonstrations:

1. Hard-rule violation declines even with a low anomaly posterior.
2. Rule-eligible unusual context steps up.
3. Rule-eligible normal context approves under the prototype policy.
4. Missing required evidence steps up.
5. Customer approve/reject/revoke resolution paths.

Required tests:

- zero future-event, late-arrival, cross-run, and cross-customer leakage;
- equal event-time exclusion and known_at boundary inclusion;
- sparse history, genuine novelty, unavailable history, and not-applicable states;
- exact inference against hand-calculated small networks;
- CPT validation, configuration hashes, and threshold equality;
- dependence/duplicate-signal and sensitivity scenarios;
- model unavailable, timeout, invalid state, and persistence failure;
- reproducible replay, idempotency, conflicting duplicate requests, and exactly-once
  state updates;
- valid provenance paths and immutable linked human-resolution receipts;
- measured latency and deadline enforcement (no invented production target).

Replay approved and declined historical records using only eligible evidence.
Original authorization outcomes remain observational comparison fields, never
labels for anomaly, fraud, or correctness. Without anomaly labels, report
coverage, sensitivity, stability, recommendation rates, and latency—not fraud
accuracy, recall, or calibration claims. Future labeled evaluation must split
chronologically and hold out complete customers/cards.

## 12. Acceptance

Reproducible and idempotent inference; bitemporal evidence provenance with
assumed availability explicitly marked; no future or cross-run leakage;
deterministic fail-safe behavior; hard rules cannot be overridden; the model
can recommend only approve or step-up; explanations describe influence rather
than causation; and historical authorization outcomes are never presented as
fraud labels or model ground truth.
