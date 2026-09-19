# KG_Rootcause Plan

## 1. Objective

Build a dynamic, semantic knowledge and root-cause layer called
`KG_Rootcause`.

The layer will:

- Connect all 11 supplied datasets through typed relationships.
- Precompute historical relationships and behavioural evidence.
- Ground customer language in trusted dataset concepts and fields.
- Create dynamic context for every new transaction.
- Pass structured knowledge evidence to the future guardrail.
- Explain decisions with rules, facts, provenance, and graph paths.
- Return frontend-ready nodes and relationships for highlighting.
- Support deterministic simulations of 10, 45, 100, and 1,000 requests.

The graph does not independently authorize payments. Customer-confirmed rules
and the deterministic guardrail remain authoritative.

```text
Dataset ingestion
      -> source and lineage graph
      -> precomputed historical relationships
      -> semantic concept mappings
      -> dynamic transaction overlay
      -> KG_Rootcause context
      -> future guardrail
      -> decision explanation and highlighted path
```

## 2. Core principles

1. Customer-confirmed policy remains authoritative.
2. Graph evidence cannot override a hard-rule failure.
3. Missing or uncertain required evidence normally produces `step_up`.
4. Only information available before a transaction may evaluate it.
5. Approved purchases establish spending and familiarity baselines.
6. Declined attempts remain evidence but are not completed spending.
7. Approved refunds reduce spending but do not create familiarity.
8. Historical authorization status is not a fraud label.
9. Free-text merchant and item fields are untrusted data.
10. Every derived fact retains its source, calculation version, and as-of time.
11. Replaying identical input and state must produce identical output.

## 3. Feature classification

### Observed facts

Directly supplied by datasets or trusted runtime inputs:

- Customer, account, card, authority, merchant, device, item, and scenario IDs.
- Amount, currency, channel, timestamp, merchant category, and location.
- Items, quantities, prices, delivery, return, and cancellation terms.
- Card and authority lifecycle status.
- Related authorization IDs.

### Derived evidence

Computed only from earlier events:

- Merchant, device, category, country, and amount familiarity.
- Amount percentiles and historical ranges.
- Frequency, velocity, burst, duplicate, and retry indicators.
- Shared-device relationships.
- Human-versus-agent transaction history.
- Unusual merchant, amount, device, country, or category indicators.

### Policy constraints

Provided by the confirmed mandate:

- Transaction, period, merchant, category, and agent budgets.
- Merchant and category allowlists or blocklists.
- Permitted products, quantities, countries, channels, and terms.
- New-device and unfamiliar-merchant step-up requirements.
- Kill switch, expiry, and revocation state.

### Runtime proofs

Produced by the live wallet-control system:

- Signed mandate, agent identity, and service identity.
- Credential scope and proof of possession.
- Nonce and replay protection.
- Checkout hash and transaction binding.
- Authentication and tamper detection.
- Receipt and settlement validation.

### External evidence

Potential later enrichment:

- Merchant reputation and dispute history.
- Sanctions results.
- Provider reliability.
- Web investigation findings.

## 4. Source and lineage graph

All dataset entities and events are connected using documented identifiers.

```text
(Customer)-[:OWNS]->(Account)
(Account)-[:HAS_CARD]->(Card)
(Authorization)-[:BY_CUSTOMER]->(Customer)
(Authorization)-[:ON_ACCOUNT]->(Account)
(Authorization)-[:ON_CARD]->(Card)
(Authorization)-[:AT_MERCHANT]->(Merchant)
(Authorization)-[:USED_DEVICE]->(Device)
(Merchant)-[:IN_CATEGORY]->(MerchantCategory)
(Authorization)-[:RELATED_TO]->(Authorization)
(Refund)-[:REFUNDS]->(Authorization)

(Scenario)-[:HAS_ATTEMPT]->(PurchaseAttempt)
(Scenario)-[:USES_AUTHORITY]->(Authority)
(Authority)-[:FOR_CUSTOMER]->(Customer)
(Authority)-[:CONTROLS]->(Card)
(PurchaseAttempt)-[:ON_CARD]->(Card)
(PurchaseAttempt)-[:AT_MERCHANT]->(Merchant)
(PurchaseAttempt)-[:USED_DEVICE]->(Device)
(PurchaseAttempt)-[:CONTAINS]->(Item)
(Item)-[:IN_CATEGORY]->(ItemCategory)
(PurchaseAttempt)-[:RELATED_TO]->(PurchaseAttempt)

(TransactionCurrency)-[:CONVERTED_BY]->(FXRate)
(FXRate)-[:TO_CURRENCY]->(BillingCurrency)
```

Historical `TR...` records and scenario `AU...` records remain separate event
namespaces.

Every graph element retains provenance:

```json
{
  "source_file": "authorization_history.csv",
  "source_id": "TR00123",
  "source_fields": ["card_id", "merchant_id"],
  "event_time": "2026-01-20T10:30:00Z",
  "source_as_of": "2026-07-31T23:59:59Z",
  "graph_version": "kg-v1"
}
```

## 5. Precomputed historical knowledge

The authorization path uses bounded summaries instead of scanning every event.

### Card-to-merchant

```text
(Card)-[:USED_MERCHANT {
    approved_count,
    declined_count,
    approved_amount_chf,
    average_approved_amount_chf,
    amount_p50_chf,
    amount_p95_chf,
    first_approved_at,
    last_approved_at,
    supporting_event_ids
}]->(Merchant)
```

### Card-to-device

```text
(Card)-[:USED_DEVICE {
    approved_count,
    declined_count,
    first_seen_at,
    last_seen_at,
    first_approved_at,
    last_approved_at,
    supporting_event_ids
}]->(Device)
```

### Card-to-category

```text
(Card)-[:PURCHASED_CATEGORY {
    approved_count,
    declined_count,
    approved_amount_chf,
    average_approved_amount_chf,
    amount_p50_chf,
    amount_p95_chf,
    merchant_count,
    last_approved_at,
    supporting_event_ids
}]->(Category)
```

### Additional summaries

- Card-to-country familiarity.
- Customer-to-device familiarity.
- Device-to-card and device-to-customer associations.
- Card amount distributions.
- Activity by hour and day of week.
- Human-versus-agent spending summaries.
- Rolling approved spending windows.
- Merchant and category diversity.
- Recent attempts and recent approved transactions.

Every summary distinguishes missing evidence, no prior relationship,
insufficient history, known-but-unapproved relationships, and stale context.

## 6. Semantic ontology

The semantic layer maps customer language to trusted dataset concepts. Its
logical design remains technology-neutral.

### Node types

```text
Concept
Phrase
DatasetField
DatasetValue
Operator
RelationshipType
PolicyTemplate
```

### Relationships

```text
(Phrase)-[:SYNONYM_OF]->(Concept)
(Concept)-[:SUBCLASS_OF]->(Concept)
(Concept)-[:MAPS_TO_FIELD]->(DatasetField)
(Concept)-[:MAPS_TO_VALUE]->(DatasetValue)
(Concept)-[:DERIVED_FROM]->(RelationshipType)
(Concept)-[:SUPPORTS_OPERATOR]->(Operator)
(Concept)-[:REQUIRES]->(Concept)
(Concept)-[:CONFLICTS_WITH]->(Concept)
```

Initial domains include merchant and item categories, channels, spending
limits, familiarity, currency, delivery, fulfilment, returns, cancellation,
recurring purchases, device integrity, duplicates, and retries.

### Example grounding

```text
"sports equipment"
    -> Concept:SportingGoods
    -> Field:items[].item_category
    -> Value:sporting_goods

"familiar shop"
    -> Concept:FamiliarMerchant
    -> Relationship:Card-USED_MERCHANT-Merchant
    -> Condition:approved_count > 0

"under CHF 200"
    -> Concept:TransactionLimit
    -> Field:authorization.billing_amount_chf
    -> Operator:<=
    -> Value:200
```

Ambiguous language must request clarification instead of inventing a value.

## 7. NLP-to-policy workflow

```text
Customer instruction
    -> extract phrases, amounts, units, and conditions
    -> resolve phrases to concepts
    -> map concepts to trusted fields and operators
    -> validate types, conflicts, and missing values
    -> present the compiled policy for confirmation
    -> store an immutable confirmed policy version
```

Every compiled rule retains its source text and span, resolved concept,
canonical field and value, operator, typed threshold, confidence, ontology
version, and confirmation status.

## 8. Dynamic transaction overlay

A new transaction is temporarily connected to historical and semantic context:

```text
(NewTransaction)-[:ON_CARD]->(Card)
(NewTransaction)-[:AT_MERCHANT]->(Merchant)
(NewTransaction)-[:USED_DEVICE]->(Device)
(NewTransaction)-[:CONTAINS]->(Items)
(NewTransaction)-[:IN_SCENARIO]->(Scenario)
(NewTransaction)-[:CONTROLLED_BY]->(Mandate)
```

The context layer evaluates merchant identity and familiarity, device and
category familiarity, amount percentile, country, velocity, duplicates,
retries, basket intent, order terms, and runtime proofs.

All historical queries use an exclusive event-time cutoff. Current and future
events cannot contribute to their own evaluation.

## 9. Guardrail context contract

For every transaction, the layer produces:

```json
{
  "transaction": {
    "authorization_id": "AU0012",
    "card_id": "CA0011",
    "merchant_id": "ME0022",
    "amount_chf": 189.0
  },
  "kg_context": {
    "merchant_familiarity": {
      "status": "known",
      "approved_count": 8
    },
    "device_familiarity": {
      "status": "new",
      "approved_count": 0
    },
    "amount_profile": {
      "status": "available",
      "percentile": 0.94,
      "above_p95": false
    }
  },
  "semantic_context": {
    "merchant_category_matches": true,
    "item_category_matches": true,
    "return_requirement_satisfied": true
  },
  "provenance": {
    "graph_version": "kg-v1",
    "ontology_version": "ontology-v1",
    "source_as_of": "2026-07-31T23:59:59Z"
  }
}
```

The future guardrail receives this beside the original trusted transaction and
confirmed policy. Context never replaces either one.

## 10. Decision and root-cause rules

### Decision precedence

```text
hard rule failure present -> decline
missing required proof    -> step_up
elevated uncertainty      -> step_up
all required checks pass  -> approve
```

### Deterministic causes

A failed hard rule is the actual decision cause:

```json
{
  "decision_cause": {
    "type": "hard_rule",
    "rule": "maximum_purchase_chf",
    "expected": 200,
    "observed": 245,
    "decision_contribution_percent": 100
  }
}
```

### Evidence contributions

Graph evidence may explain an escalation or uncertainty. These are explanation
contributions, not proven fraud causation:

```json
{
  "supporting_evidence": [
    {
      "fact": "Amount is above the card historical p95",
      "evidence_contribution_percent": 65
    },
    {
      "fact": "Device has not previously been used",
      "evidence_contribution_percent": 35
    }
  ],
  "counter_evidence": [
    {
      "fact": "Merchant has eight prior approved purchases"
    }
  ]
}
```

Until a calibrated model exists, contributions use explicit versioned expert
weights and remain separate from hard-rule causes.

## 11. Root-cause paths

Every explanation can return graph IDs and source event IDs.

```json
{
  "path_id": "path-new-device-AU0012",
  "reason_code": "new_device",
  "contribution_percent": 35,
  "nodes": [
    "NewTransaction:AU0012",
    "Card:CA0011",
    "Device:DVC-99"
  ],
  "relationships": [
    "CURRENT_USED_DEVICE:AU0012->DVC-99"
  ],
  "source_event_ids": [],
  "explanation": "No prior approved card-device relationship exists."
}
```

Evidence based on prior activity includes the historical authorization IDs
that created the aggregate.

## 12. Frontend contract

The frontend-facing object is named `KG_Rootcause`:

```json
{
  "KG_Rootcause": {
    "authorization_id": "AU0012",
    "decision": "step_up",
    "decision_cause": {},
    "supporting_evidence": [],
    "counter_evidence": [],
    "root_cause_paths": [],
    "highlight_graph": {
      "nodes": [],
      "relationships": []
    },
    "versions": {
      "graph": "kg-v1",
      "semantic_ontology": "ontology-v1",
      "policy": "policy-v1",
      "evidence_weights": "evidence-weights-v1",
      "model": null
    }
  }
}
```

Each highlighted graph element contains presentation-neutral data:

```json
{
  "id": "USED_DEVICE:CA0011->DVC-99",
  "reason_code": "new_device",
  "contribution_percent": 35,
  "highlight_score": 0.35,
  "highlight_level": "supporting",
  "source_event_ids": []
}
```

Suggested visual meaning:

- Direct decision cause: strong red.
- High-contribution supporting evidence: red.
- Moderate supporting evidence: orange.
- Counter-evidence: green.
- Context-only relationships: grey.

Colour is never the only indicator.

## 13. Component boundaries

```text
Knowledge_graph/
  plan.md
  data.md
  kg_rootcause/
    ingestion/
    schema/
    semantic/
    precompute/
    context/
    explanation/
    frontend_contract/
    simulation/
    tests/
```

The implementation stays separate from the unfinished `live_layer` and
integrates through JSON contracts.

Conceptual interfaces:

```text
build_knowledge(dataset) -> KnowledgeSnapshot
compile_semantics(instruction) -> SemanticPolicyDraft
get_transaction_context(transaction, snapshot, as_of) -> KGContext
explain_decision(transaction, policy, checks, context) -> KG_Rootcause
simulate(requests, initial_state) -> SimulationReport
```

## 14. Ten-request baseline

The initial simulation replays the 10 ordered events in `SCEN0001`.

For each request:

1. Load the transaction and linked records.
2. Build its dynamic transaction overlay.
3. Query history using an exclusive timestamp cutoff.
4. Produce guardrail-ready context JSON.
5. Apply a simulation decision policy.
6. Produce `KG_Rootcause`.
7. Validate all graph IDs and source event IDs.
8. Update state only after a final approval.

The baseline proves:

- Every request produces valid context and root-cause objects.
- Every reason references valid graph elements.
- Every historical fact has provenance.
- Hard rules retain deterministic precedence.
- Missing evidence never weakens the guardrail.
- Step-up does not increase spend before resolution.
- Replay is deterministic.
- No request uses current or future evidence.

## 15. Simulation report

Every run reports:

```text
request_count
approve_count
step_up_count
decline_count
average_evaluation_latency_ms
p95_evaluation_latency_ms
graph_context_coverage_percent
explanation_completeness_percent
valid_provenance_path_percent
future_data_leakage_count
duplicate_processing_count
deterministic_replay_match_percent
missing_evidence_count
```

Detailed per-request results retain input, context, decision, explanation, and
the highlighted graph subset.

## 16. Scale progression

1. Replay the 10 ordered `SCEN0001` requests.
2. Replay all 45 public requests.
3. Generate 100 deterministic requests using fixed seeds.
4. Generate 1,000 deterministic requests for performance testing.

Generated requests include normal, boundary, unfamiliar, duplicate, retry,
and missing-evidence cases. They are never presented as real behaviour or
fraud labels.

## 17. Implementation phases

### Phase 1 — schemas and invariants

- Finalize node types, relationship types, identities, and cardinalities.
- Define time, currency, provenance, missing, unknown, and not-applicable rules.
- Define `KGContext` and `KG_Rootcause` schemas.

### Phase 2 — complete dataset connections

- Connect all 11 CSV datasets.
- Validate every foreign-key relationship.
- Preserve historical and scenario namespaces.
- Produce a portable node-link snapshot.

### Phase 3 — precomputed knowledge

- Create merchant, device, category, country, amount, time, and agent-history
  summaries.
- Retain supporting event IDs.
- Implement exclusive as-of context queries.

### Phase 4 — semantic ontology

- Define canonical concepts, phrases, fields, values, and operators.
- Detect ambiguity and conflicts.
- Produce a customer-confirmable semantic policy draft.

### Phase 5 — dynamic context

- Build transaction overlays.
- Retrieve relevant evidence.
- Produce guardrail-ready JSON.

### Phase 6 — explanation and frontend graph

- Separate causes, supporting evidence, and counter-evidence.
- Produce versioned evidence contributions.
- Return root-cause paths, source IDs, and highlight data.

### Phase 7 — simulation

- Run the 10-event baseline.
- Expand to 45, 100, and 1,000 events.

### Phase 8 — future guardrail integration

- Pass `KGContext` to the future guardrail.
- Pass guardrail checks to the explanation builder.
- Keep knowledge and explanation logic outside the guardrail.

## 18. Technology decision

No graph database, semantic store, or cache is selected yet. The first
artifacts remain portable and storage-neutral.

Technology selection follows validation of query depth, latency, volume,
consistency, temporal requirements, audit, backup, recovery, operational
complexity, portability, and vendor lock-in.

## 19. Acceptance criteria

- All 11 files are represented and connected.
- Every relationship has valid provenance.
- Context is time-correct and excludes current/future information.
- A new transaction produces dynamic graph and semantic context.
- `KGContext` and `KG_Rootcause` validate against their schemas.
- Hard causes are never diluted by graph or model evidence.
- Root-cause paths reference valid graph and source IDs.
- Frontend highlights are complete and presentation-neutral.
- The 10-request simulation is deterministic and passes all invariants.
- The design remains independent of the unfinished `live_layer`.

## 20. Known limitations

- Only 20 customers and 41 cards are supplied.
- Historical authorizations do not contain structured item baskets.
- Structured items exist only for the 45 scenario attempts.
- Historical agent events have no `agent_id`.
- No confirmed fraud, chargeback, or account-takeover labels are supplied.
- IP, precise geolocation, session identity, reputation, sanctions, and
  settlement data are unavailable.
- The public scenarios are too small for a supervised risk model.

