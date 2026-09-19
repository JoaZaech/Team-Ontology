# Viseca End-to-End Test Plan

## Goal

Prove that the supplied Viseca CSV data can travel through the local mock API, the standalone rule service, and the decision-lab frontend while customer policy is enforced by the server.

The data pack explicitly contains no official expected-decision answer key. The suite therefore checks deterministic policy invariants, API contracts, state transitions, and selected outcomes whose rules are defined in this repository.

## System under test

```text
viseca-2026/data/*.csv
  -> mock_api/viseca_mock.py
  -> mock_api/rule_client.py
  -> rule_service/server.py
  -> rule_service/scenario_rulebook.py
  -> live_layer/decision-lab
```

The rule service and mock API run as separate processes. Every rule evaluation crosses the authenticated HTTP boundary.

## Automated coverage

### 1. Full CSV replay

Replay all five scenarios and all 45 purchase attempts through the mock benchmark API.

Assertions:

- Scenario counts are `1`, `10`, `12`, `11`, and `11`.
- Every source authorization from `AU0001` through `AU0045` appears exactly once.
- Each event is evaluated by the rule service using the server-owned scenario policy.
- The submitted decision and reason codes match the engine recommendation.
- Step-up outcomes are recorded and resolved through the separate customer-resolution route.
- Every run completes and its decision-receipt chain remains valid.
- The resulting set includes approve, decline, and step-up recommendations.

### 2. Frontend approval workflow

Load the decision lab with the default wallet policy and let the UI process the supplied `SCEN0000` / `AU0001` fixture.

Assertions:

- The browser receives `AU0001`, `SCEN0000`, Alpine Basket, and CHF 20 from the mock API.
- The rule service recommends approval and every check passes.
- Merchant familiarity uses the CSV history and reports 26 prior approved purchases.
- The frontend records the engine recommendation through the decision API.
- The visible receipt reports `Approved. Ready to continue.`

### 3. Frontend policy-enforcement workflow

Open Wallet policies, change the daily spending limit from CHF 1,500 to CHF 10, and return to the workflow.

Assertions:

- The policy update is persisted through `PATCH /mock/policy` with an optimistic revision.
- The next `AU0001` evaluation is a decline.
- The `Daily spending limit` rule fails with `daily_spending_limit_exceeded`.
- The mock API accepts the decline and cannot replace it with a client-selected approval.
- The visible receipt reports `Declined. No payment was approved.`

## Runtime measurements

Each test attaches `runtime-metrics` JSON to the Playwright result and prints the same values in the list reporter.

- Full replay: total wall time plus rule-engine p50, p95, and maximum evaluation duration across 45 attempts.
- Browser approval: total workflow time and `/mock/evaluate` HTTP time.
- Policy decline: policy-update HTTP time, total workflow time, and `/mock/evaluate` HTTP time.

Runtime values are observations, not hard pass/fail thresholds. Add thresholds only after collecting stable CI baselines on the target runner.

## Run locally

```bash
cd live_layer/decision-lab
npm install
npx playwright install chromium
npm run test:e2e
```

`npm run test:e2e` builds the Vue app and starts both local Python services. The HTML report is written to `live_layer/decision-lab/playwright-report/` and failure artifacts to `live_layer/decision-lab/test-results/`.

## Exit criteria

- All three Playwright tests pass.
- Exactly 45 distinct source authorizations are replayed.
- Approval, decline, and step-up are all observed.
- Both browser outcomes match the rule-engine recommendation.
- Runtime metrics are present in the test output and attachment.

## Remaining scope

- The complete 45-attempt set is API-to-engine coverage; the current frontend only presents the one-event `SCEN0000` workflow.
- The suite does not call Viseca's hosted sandbox or authorize a real payment.
- The synthetic data provides facts, not official expected decisions. Repository policy documents are the test oracle.