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
