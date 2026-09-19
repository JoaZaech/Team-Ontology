# Viseca merchant guardian

`guardian.py` adapts the three pre-payment checks in the public
[X402LOOKOUT notebook](https://github.com/S1T1/X402LOOKOUT/blob/main/x402_guardian_tavily_final.ipynb):
spend cap, merchant check, and repeated-attempt check. It returns a structured
result with reason codes and evidence. It performs no network calls and uses no
Tavily, x402 payment, or on-chain data.

For this challenge, the merchant check matches a merchant's opaque ID and
catalogue attributes, then counts that card's previously approved purchases.
History is **familiarity evidence**, not a fraud label or an ERC-8004 score.
Unknown, mismatched, or newly encountered merchants trigger `step_up` when
familiarity is required; they are not automatically fraudulent.

The caller supplies `GuardPolicy` from the **customer-confirmed** policy layer.
It must compute the rolling approved spend for the policy's precise period and
pass it as `approved_spend_in_period_chf`. Pending step-ups do not count as
approved spend. The guard is pure: it never debits money or records a decision,
so retries return the same result. The final wallet decision must also check
items, returns, allowed retailer type, session integrity, and the remaining
customer instructions. `approve` here only means these guard checks passed.

Run the focused tests with:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s live_layer -p 'test_*.py' -v
```

## Decision receipts and telemetry

Both local mocks now create a hash-chained decision receipt for each completed
evaluation and record redacted operational events. Receipts capture the policy
snapshot/hash, engine version, rule outcomes, deadline headroom, idempotency
result, and a later customer resolution without mutating the original record.
The telemetry view contains only bounded aggregates and HMAC-pseudonymous
correlation values; it excludes raw customer, card, merchant, product, prompt,
and API-key data.

By default, receipts use an in-memory SQLite database for a local run. Set an
explicit local path when demonstrating replay across a restart:

```bash
export DECISION_RECEIPTS_PATH=/tmp/viseca-decision-receipts.sqlite3
```

The local aggregate metric endpoints are `GET /v1/agent/observability` on port
8081 and authenticated `GET /mock/observability` on port 8082. They are
prototype inspection endpoints, not a production monitoring backend.

## Mock AI entry point

Start the local server with `python3 -B live_layer/mock_api.py`, then send the
included [sample request](mock_request.json):

```bash
curl -sS http://127.0.0.1:8081/v1/agent/simulate \
  -H 'Content-Type: application/json' \
  --data-binary @live_layer/mock_request.json
```

The request contains only:

| Field | Why it is needed |
| --- | --- |
| `request_id` | Safe retries and an audit reference |
| `buyer.card_id` | Look up that card's merchant history |
| `buyer.mandate_id` | Select the customer-confirmed policy |
| `merchant_id` | Resolve merchant details from the trusted catalogue |
| `order.billing_amount_chf` | Enforce the CHF purchase limit |
| `order.delivery_fee_chf` and `order.items` | Check the quoted total and preserve the proposed basket |

The server derives the merchant name/category, policy limit, prior card activity,
and ten-minute attempt count. The agent cannot set them. The mock policy
`TM_DEMO_GROCERY` is bound to `CA0001` and has a CHF 20 purchase limit.

The response contains the guard result, the full rulebook evaluation, a policy
snapshot, and a decision-receipt hash. It always sets `payment_authorized:
false`: this prototype does not initiate a payment or connect a hosted worker.
Its retry and rate state remains in memory; only receipts persist when
`DECISION_RECEIPTS_PATH` is configured. Bind it only to local loopback as
shown; it has no authentication.

## Hosted Viseca API connection

`viseca_client.py` is the Python equivalent of the connection commands in the
company's technical guide. It currently makes read-only calls:

```bash
python3 -B live_layer/viseca_client.py health
export TEAM_API_KEY='<team key from Viseca>'
python3 -B live_layer/viseca_client.py bootstrap
python3 -B live_layer/viseca_client.py reference-data
```

`LEASH_BASE_URL` is optional and defaults to the URL in the Viseca guide. The
key stays in the environment; never commit it. These calls do not start a
scenario or submit a decision. The hosted worker will use this client after the
full customer-policy engine is connected and tested.

## Rehearse the Viseca API locally

The earlier `/v1/agent/simulate` endpoint is a simplified agent purchase
proposal. For a **Viseca-shaped API flow**, run `viseca_mock.py`. It reads the
company's `SCEN0000` / `AU0001` fixture and builds the complete live event
shape defined in `authorization_event.schema.json`, with a fresh mock deadline.

The interactive demo page (`decision-lab/`) is a Vue 3 + TypeScript frontend
for the local Viseca mock. It retrieves the incoming request, asks the local
rule engine to evaluate it, records the selected decision, and reads or updates
the versioned wallet policy. The server joins the request to the bundled
transaction and merchant data; the browser does not make external calls.

Build the frontend, then serve it through the mock API:

```bash
cd live_layer/decision-lab
npm install
npm run build
cd ../..
python3 -B live_layer/viseca_mock.py
```

Open `http://127.0.0.1:8082/` in a browser. Use **Pull request**, **Evaluate
request**, then choose **Approved**, **Not approved**, or **Human requested**
and press **Submit decision**. The default `SCEN0000` request is approved after
the mandate, basket, spend, merchant-history, and saved-policy checks pass.
Edits in the policy panel use optimistic revisions and affect the next incoming
request; for example, reducing the daily cap causes the evaluation to decline.
**Reset demo** replays the local request.

For UI development, keep `viseca_mock.py` running and run `npm run dev` inside
`decision-lab/`. Vite proxies `/mock` and `/v1` to the local mock service.

To rehearse the **Viseca-shaped API itself** (separate from the browser demo
above), run `viseca_mock.py` in terminal 1:

```bash
python3 -B live_layer/viseca_mock.py
```

In terminal 2, from the repository root:

```bash
export LEASH_BASE_URL='http://127.0.0.1:8082'
export TEAM_API_KEY='mock-team-key'
python3 -B live_layer/viseca_client.py health
python3 -B live_layer/viseca_client.py bootstrap
python3 -B live_layer/viseca_client.py reference-data
python3 -B live_layer/viseca_client.py next
```

`next` returns one envelope whose `data` is the mock purchase request. A second
`next` returns `null` (HTTP 204), just as an empty poll should. To try the local
decision endpoint after receiving the request:

```bash
curl -sS "$LEASH_BASE_URL/v1/authorizations/MOCK_AU0001/decision" \
  -H "Authorization: Bearer $TEAM_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"authorization_id":"MOCK_AU0001","decision":"step_up","reason_codes":["customer_confirmation"]}'
```

Resolve a recorded step-up through the separate customer path:

```bash
curl -sS "$LEASH_BASE_URL/v1/authorizations/MOCK_AU0001/resolve" \
  -H "Authorization: Bearer $TEAM_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"authorization_id":"MOCK_AU0001","decision":"approve"}'
```

The local server accepts this decision for workflow rehearsal only. Its bootstrap
and reference-data responses are intentionally small mock responses, not copies
of Viseca's hosted responses. Restarting the server resets the one-request run.
The real team key is used only with the HTTPS hosted API; the dummy key above is
only accepted by the local mock.
