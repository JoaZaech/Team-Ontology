# Frontend decision-workflow research

**Date:** 19 September 2026  
**Scope:** the Vue decision-lab prototype, the local Viseca-shaped mock, and the supplied challenge contract.  
**Recommendation:** build an **evidence-first decision replay** now; introduce a small interactive graph only when the workflow has branches or multiple transactions. Keep the payment authorizer deterministic. An LLM may assist policy drafting or wording, but must never be the approving node.

## Executive conclusion

The current UI is a good *linear rehearsal* but not yet a trustworthy workflow demonstration. It proves one happy-path fixture can be pulled, evaluated, manually selected, and “recorded”; it does **not** exercise the local mock or hosted API, cannot show an escalation/resolution path, and does not expose rule inputs or provenance.

The best visual story for the challenge is not a generic node editor. It is a clear answer to five questions, in this order:

1. What did the customer permit, and which confirmed policy version applied?
2. What purchase arrived, from which trusted and untrusted inputs?
3. Which checks ran, in what order, and what evidence did each use?
4. Why did the system approve, decline, or pause for a person?
5. What was recorded or resolved, before the deadline?

Use an outcome-first top summary, a horizontal workflow/timeline below it, and an evidence drawer. This is easier to understand under demo pressure than a zoomable graph. Add an optional **“Workflow graph”** view for the judge/analyst audience, driven by the *same typed run data*.

## What exists today

| Area | Current implementation | What it proves | Gap for a workflow demo |
| --- | --- | --- | --- |
| App shell | Vue 3, TypeScript, Vite; no state or graph dependency. | Small and low-risk build. | UI state is spread across mutable refs rather than modeled transitions. |
| Progress | `StepIndicator.vue` renders three cards: pull → evaluate → record. | Clear happy-path progress. | Has no branches for `decline`, `step_up`, human resolution, retry, expiry, or failure. |
| Purchase | `PurchaseRequestCard.vue` shows card, merchant, amount, basket, and raw envelope. | The proposal facts are visible. | No policy snapshot, timing/deadline, source/trust label, or transaction history. |
| Rules | `RulebookDecisionCard.vue` lists pass/fail/review checks and permits a manual override. | Check-level explanations already exist. | The result is a flat list; no provenance, precedence, or distinction between engine recommendation and customer action. |
| UI API | `src/api.ts` replays `fixtures.ts` in memory with deliberate sleeps. | The component contract is testable without network access. | It makes no `fetch` calls and can drift from the engine and API. |
| Local API | `viseca_mock.py` serves one envelope, evaluates it at `/mock/evaluate`, and records `/v1/authorizations/{id}/decision`. | The local contract supports a realistic request/decision rehearsal. | It does not currently expose a human `/resolve` route or an event stream. |
| Engine | `rulebook.py` combines authority, basket, total, mandate cap, merchant familiarity, and velocity checks. | Deterministic, explainable `approve` / `decline` / `step_up`. | The frontend type loses structured evidence emitted by the lower-level guardian. |

The source makes the deliberate static boundary explicit: [App.vue](/Users/joazach/Team-Ontology/live_layer/decision-lab/src/App.vue:126) says “NO API CALLS,” and [api.ts](/Users/joazach/Team-Ontology/live_layer/decision-lab/src/api.ts:5) returns baked fixtures. In contrast, [viseca_mock.py](/Users/joazach/Team-Ontology/live_layer/viseca_mock.py:179) already exposes the next-request endpoint and [technical_details.md](/Users/joazach/Team-Ontology/viseca-2026/technical_details.md:306) defines the hosted decision contract.

## Target experience

### One run, two complementary views

**1. Customer / demo view — default**

Show a single transaction as a readable replay. It is the primary view for a 2–3 minute demonstration.

```text
Confirmed policy ──► Purchase received ──► Deterministic checks ──► Outcome
     v3 / active          12:00:00              6 checks              APPROVE
                           7.4 s left            5 pass, 1 review
                                                         │
                          [approve] [decline] ──────────┴──► recorded
                                            [step up] ─────► customer review ► resolved
```

The selected/current stage has a strong outline and status text. Completed stages retain their outcome colour. Future paths are muted—not hidden—so `step_up` visibly means “paused, awaiting a human,” rather than a disguised approval.

**2. Analyst / judge view — optional tab**

Render the same run as a compact directed graph:

```text
Customer-confirmed policy ──────┐
Trusted event facts ────────────┼──► Rule evaluation ─► Decision receipt ─► API record
History / merchant catalogue ───┤          │
Untrusted merchant text ────────┘          └──► uncertainty ─► human resolution
```

Clicking a node opens its source data, rule version, timestamps, and result. Clicking a check highlights only the incoming evidence and its decision edge. This graph is an *explanation* of a completed run, never a tool to modify policy or decide a payment.

### Information architecture

| Screen / component | Purpose | Minimum content |
| --- | --- | --- |
| `RunHeader` | Establish state immediately. | Final/current outcome, authorization ID, live deadline countdown, engine version, run ID, replay status. |
| `PolicySnapshotCard` | Prove consent precedes execution. | Original instruction, active/revoked state, rule summary, uncertainty policy, version/hash, “view exact policy.” |
| `WorkflowReplay` | Explain sequence and branches. | Six lifecycle stages, timestamp/duration, active/complete/error state, keyboard-selectable stages. |
| `CheckRail` | Explain the decision. | Rule name, result, reason code, compact evidence sentence, rule and source links. |
| `EvidenceDrawer` | Supply audit depth on demand. | Canonical values, source class, freshness, request/policy identifiers; redact card/customer details. |
| `DecisionPanel` | Keep authority clear. | Engine recommendation; allowable operator action; submit status; immutable receipt after success. |
| `HumanReviewPanel` | Show the real customer-control branch. | Reason, purchase summary, remaining human window, Approve/Decline actions, resolution receipt. |
| `RunTimeline` | Let the demo tell three stories. | Ordinary approval, intervention/step-up, final human decision or mandate revocation. |

## Recommended decision state model

Separate the browser’s presentation state from the payment decision. The following finite states cover the API contract and prevent invalid UI actions:

```text
idle → loading → received → evaluating → recommended
                                      ├→ submitting → recorded
                                      ├→ step_up_submitting → awaiting_customer → resolving → resolved
                                      └→ failed / expired
```

Transitions must be triggered by actual adapter results, not animation timers. In particular:

- `recommended` is not a final decision.
- `step_up` ends the automatic-decision portion but **does not approve** a purchase.
- `recorded` must retain the API response; a repeat response is reconciliation, not a second submission.
- `awaiting_customer` is independent from receiving subsequent events; the worker continues to poll.
- A deadline needs a visible `expired` terminal state. Never simulate success after it.

The supplied brief requires an 8-second automated deadline, long polling, idempotent handling of repeated deliveries, and a separate resolution after `step_up`; see the local [polling and deadline rules](/Users/joazach/Team-Ontology/viseca-2026/technical_details.md:243) and [resolution rule](/Users/joazach/Team-Ontology/viseca-2026/technical_details.md:332).

## How AI belongs in the visualization

The current engine is rule-based, not AI-based. The interface must say that plainly. Calling the check list an “AI workflow” would overstate what runs today and weaken the trust story.

If an optional model is introduced, display it in a separate **assistive lane**:

```text
Customer text ─► AI extracts a draft policy ─► validation + customer confirmation ─► active policy
Merchant text ─► AI extracts an unverified fact ─► deterministic policy check ─► review if material
                                                       └───────────────► never automatic permission
```

The authorization lane remains: **confirmed policy + trusted transaction data + deterministic checks → decision**. Mark any model-derived item with “candidate / unverified,” its model/version, source snippet, validation status, and whether it influenced only an escalation. Do not put an “AI confidence” gauge next to an approval: confidence is not customer authority.

This boundary matches the challenge requirement that a model failure still yields predictable behavior and that merchant text is untrusted. It also follows the OpenTelemetry guidance that traces should model discrete operations with well-defined attributes, which is useful for correlating the workflow without exposing raw sensitive content ([OpenTelemetry trace conventions](https://opentelemetry.io/docs/specs/semconv/general/trace/)).

## Library and rendering evaluation

| Option | Fit here | Strengths | Costs / limits | Decision |
| --- | --- | --- | --- | --- |
| Existing HTML/CSS + semantic list/timeline | Excellent for the first demo. | Small bundle, responsive, naturally keyboard/screen-reader friendly, consistent with existing design. | Manual placement; less exploratory. | **Use for the default replay.** |
| Inline SVG, authored in Vue | Excellent for a fixed six-stage workflow. | Complete visual control, no dependency, can animate the active route. | Must provide equivalent text/list controls; layouts are manual. | **Use only if the timeline needs connector lines.** |
| [Vue Flow](https://vueflow.dev/) | Strong later fit for a clickable evidence graph. | Native Vue 3, custom nodes/edges, zoom/pan, controls, minimap, TypeScript; supports nested flows. | More UI surface than the one-purchase demo needs; graph navigation alone is not accessible explanation. | **Adopt only for the optional Analyst tab.** |
| [bpmn-js](https://bpmn.io/toolkit/bpmn-js/) | Good for a business-process/compliance diagram. | BPMN 2.0 viewer can embed and annotate business flows; suitable if stakeholders require BPMN. | BPMN is too formal/noisy for purchase evidence; XML/modeling overhead; does not replace an audit UI. | **Use for a static architecture/process page, not the live decision screen.** |
| [XState + @xstate/vue](https://stately.ai/docs/xstate-vue) | Strong fit as lifecycle grows. | Makes UI transitions explicit; Vue composables provide the live snapshot and send function; optional Inspector can visualize transitions. | New dependency/learning cost; it must not become the policy engine. | **Add when moving to live adapter and step-up.** |
| Canvas/WebGL graph library | Poor fit. | Can scale large graphs. | Extra accessibility, hit-testing, export, and mobile work; no need at current scale. | **Do not use.** |

Vue Flow’s documented features—custom nodes and edges, nested graphs, zoom/pan, minimap, and controls—make it the appropriate Vue-native choice when a real evidence graph is justified ([Vue Flow documentation](https://vueflow.dev/)). For the lifecycle itself, XState is explicitly designed for predictable event-driven state machines and has Vue support ([XState documentation](https://stately.ai/docs/xstate)). The [Stately Inspector](https://stately.ai/docs/inspector) is useful for developer verification, but should not be the customer-facing screen.

## Integration plan

### 1. Replace the fixture-only module with an adapter boundary

Keep the current fixture adapter for offline demos, but make it one implementation of a `DecisionGateway` interface. Add a real implementation for local/hosted execution. The component should not know which mode it is using.

```ts
interface DecisionGateway {
  nextRequest(): Promise<DecisionEnvelope | null>;
  evaluate(envelope: DecisionEnvelope): Promise<EvaluationResult>;
  submitDecision(input: SubmitDecisionInput): Promise<DecisionRecordResult>;
  resolve?(input: ResolveDecisionInput): Promise<DecisionRecordResult>;
  getMandate?(mandateId: string): Promise<MandateDetail>;
}
```

The existing static implementation maps directly to `nextRequest`, `evaluate`, and `submitDecision`. The local implementation should call:

| UI intent | Local route today | Hosted route / implication |
| --- | --- | --- |
| Receive next purchase | `GET /v1/decision-requests/next` | Long-poll `?wait=25`; 204 is “no event,” not completion. |
| Evaluate | `POST /mock/evaluate` | Do this in the independent backend worker, not in a browser. |
| Submit automated decision | `POST /v1/authorizations/{id}/decision` | Include decision, reason codes, evidence, engine version. |
| Resolve a pause | Not implemented in mock | `POST /v1/authorizations/{id}/resolve`; add to local mock for end-to-end UI parity. |
| Read/change/revoke policy | Not implemented in mock | Mandate endpoints; policy changes affect later runs and require explicit UI confirmation. |

### 2. Do not put a Viseca bearer key in Vite

The browser is the wrong location for long polling, raw API credentials, and hot-path policy evaluation. Use this boundary:

```text
Vue app ── authenticated session ──► application backend / BFF
                                         ├─ worker: poll, validate, evaluate, record
                                         ├─ store: immutable receipt + idempotency
                                         └─ SSE/WebSocket: redacted run updates
                                                        │
                                             Viseca hosted API / local mock
```

The UI receives a redacted `DecisionRunView` by run ID. The worker holds the bearer key, evaluates before the 8-second deadline, persists the accepted outcome, and publishes a state update. The browser may submit the **customer’s resolution** through the BFF, which authenticates the customer and records the returned receipt. This also avoids CORS/credential leakage and lets the frontend reconnect without duplicate evaluation.

For the local prototype, Vite may proxy `/api` to the loopback mock, but retain the same browser-facing routes so production does not require a component rewrite. The mock’s bearer-key check is at [viseca_mock.py](/Users/joazach/Team-Ontology/live_layer/viseca_mock.py:213); that is another reason not to copy it into shipped client code.

### 3. Carry enough data to render evidence

`EvaluationResult` currently has `name`, `outcome`, `reason_code`, and display `detail`. Extend a frontend-only read model rather than exposing arbitrary raw event data:

```ts
type SourceTier = "confirmed_policy" | "trusted_event" | "trusted_history" | "derived" | "untrusted";

interface CheckView {
  id: string;
  ruleId: string;
  name: string;
  outcome: "pass" | "fail" | "review";
  reasonCode: string;
  summary: string;
  evidence: Array<{
    label: string;
    value: string;
    source: SourceTier;
    path?: string;
  }>;
  durationMs?: number;
}

interface DecisionRunView {
  runId: string;
  authorizationId: string;
  policy: { mandateId: string; version?: string; status: string; instruction: string; uncertaintyPolicy: string };
  deadlineAt: string;
  lifecycle: Array<{ state: string; at: string; durationMs?: number }>;
  recommendation?: "approve" | "decline" | "step_up";
  checks: CheckView[];
  receipt?: { finalDecision: string; recordedAt: string; engineVersion: string };
}
```

Use an allow-list of fields and redaction (for example, masked card number / opaque ID) before publishing this view. Keep raw payloads and receipts in the backend audit store. Add a `policy_version` or content hash: a run uses a snapshot, so a later policy edit must not rewrite what the replay says was evaluated.

### 4. Instrument a replay, not surveillance

Emit a run correlation ID across the worker, evaluator, record call, and UI update. Useful spans/events are `decision.request_received`, `decision.evaluate`, `decision.step_up`, `decision.record`, and `decision.resolve`; record durations, outcome, reason codes, engine version, and error class. Do **not** put product descriptions, card/customer IDs, merchant text, or full prompts into telemetry. OpenTelemetry uses spans to represent individual operations and defines common semantic conventions for correlating them across services ([OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/)).

## UI behaviour and accessibility requirements

- Use words and icons together: **Approved**, **Declined**, and **Needs your approval**. Colour is supplemental and must retain sufficient contrast in dark mode.
- The main workflow is an ordered list with `<button>` stage controls; the visual connector is decorative. Every node has a text equivalent and selected state.
- The status region already has `aria-live="polite"`; retain it for new events, but do not announce a countdown every second.
- Preserve focus when a drawer opens, support Escape to close it, and do not blur/hide a focused check while evaluation is running.
- Make raw JSON opt-in and label it “technical payload,” not “evidence.” The evidence view must explain it in plain language.
- Respect `prefers-reduced-motion`; active-edge animation must be off or nonessential.
- Never show an enabled “approve” action while the only state is an automatic `step_up`. The resolution panel is a different authority action.

Structured graphics need semantic alternatives; the W3C Graphics-ARIA module exists specifically to add semantics for charts, graphs, maps, and technical drawings ([W3C Graphics-ARIA](https://www.w3.org/TR/graphics-aria-1.0/)). For this reason, the timeline/list is the accessibility baseline even if Vue Flow is added.

## Delivery sequence

| Phase | Work | Demonstrable result |
| --- | --- | --- |
| 1 — Workflow replay | Add `DecisionRunView`, `RunHeader`, policy snapshot, check rail, six-state timeline, and fixture cases for approve/decline/step-up. Retain static mode. | One ordinary purchase and one useful intervention are understandable without opening JSON. |
| 2 — Contract integration | Add gateway implementations, local mock `/resolve`, BFF/worker, persisted idempotency/receipt, deadline/error states, SSE run updates. | The page displays real local API state; retry is visibly safe; customer resolution completes a step-up. |
| 3 — Graph and observability | Add analyst graph behind a tab, evidence highlighting, redacted traces, contract/component/E2E/accessibility tests. | A judge can inspect why a branch occurred without the graph being required to operate the demo. |

### Acceptance checks

1. An approval, decline, step-up, human approve, human decline, timeout, and retry each render a distinct final/current state.
2. Every displayed check links to a rule and at least one source-labelled evidence item.
3. The displayed policy version is the run snapshot, not the newest policy.
4. Repeated `authorization_id` responses do not create an additional timeline entry or spend record.
5. The API key is absent from the browser bundle, source maps, and client network storage.
6. Keyboard-only users can navigate stages, open evidence, and resolve a step-up; the same meaning is available without the graph.
7. A model outage/invalidation shows a defined fallback or `step_up`; it never defaults to approval.

## Concrete first change set

1. Rename the current `StepIndicator` concept to `WorkflowReplay` and expand it to the six lifecycle states above. Keep it a semantic HTML list; do not add a graph dependency yet.
2. Extract the existing functions from [api.ts](/Users/joazach/Team-Ontology/live_layer/decision-lab/src/api.ts:16) behind `DecisionGateway`; the existing fixture becomes `FixtureDecisionGateway`.
3. Add two more fixture scenarios: an amount/basket hard failure and an unfamiliar-merchant `step_up`. This proves the branch layout before networking is introduced.
4. Add `policy`, deadline, rule/evidence, and receipt fields to a `DecisionRunView` mapper. Do not force raw backend objects into components.
5. Implement the mock `/resolve` endpoint and then the BFF/worker route. Only after that, replace the “static demo” badge with the connected status.
6. Add Vue Flow only if the analyst graph is still useful after the timeline is working; make it lazy-loaded and read-only.

## Verification performed

- `npm run build` in `live_layer/decision-lab` — passed (Vue type check and Vite build).
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s live_layer -p 'test_*.py' -v` from the repository root — passed: 21 tests.

## Research sources

- [Vue Flow: Vue 3 flowchart documentation](https://vueflow.dev/) — Vue-native graph capability and interaction model.
- [bpmn-js toolkit](https://bpmn.io/toolkit/bpmn-js/) and [walkthrough](https://bpmn.io/toolkit/bpmn-js/walkthrough/) — BPMN viewer/modeler trade-offs.
- [XState for Vue](https://stately.ai/docs/xstate-vue) and [Stately Inspector](https://stately.ai/docs/inspector) — explicit lifecycle state and development-time visual inspection.
- [OpenTelemetry trace conventions](https://opentelemetry.io/docs/specs/semconv/general/trace/) and [semantic conventions](https://opentelemetry.io/docs/specs/semconv/) — interoperable operation tracing.
- [W3C Graphics-ARIA](https://www.w3.org/TR/graphics-aria-1.0/) — semantic requirements for structured graphics.
- Local primary references: [challenge brief](/Users/joazach/Team-Ontology/viseca-2026/challenge.md:1), [technical API guide](/Users/joazach/Team-Ontology/viseca-2026/technical_details.md:243), and [existing trustworthy control-layer research](/Users/joazach/Team-Ontology/TRUSTWORTHY_GRAPH_MODEL_RESEARCH.md:1).
