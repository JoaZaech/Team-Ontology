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

The response contains a `guard.decision` and individual checks. It always sets
`payment_authorized: false`: this prototype has no full item/return-policy
engine, customer approval flow, payment, persistent ledger, or Viseca API
connection. Its in-memory retry and rate state resets when restarted. Bind it
only to local loopback as shown; it has no authentication.

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
