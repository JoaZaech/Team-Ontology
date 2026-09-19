# Historical decline smoke test

Result: PASS; 259 declines; 0 audit errors.

{"behavioral_context_only": 78, "observable_rule_conflict": 106, "unexplained_by_checked_factors": 75}

| Observed factor | Declined records | Approved purchases with factor | Declined purchases with factor |
| --- | ---: | ---: | ---: |
| Card blocked or expired at event | 6 | 0 | 6 |
| Amount exceeds supplied per-transaction limit | 4 | 0 | 4 |
| Account month-to-date total plus attempt exceeds monthly limit | 0 | 0 | 0 |
| Ecommerce attempt while online payments disabled | 0 | 0 | 0 |
| Foreign merchant while international payments disabled | 98 | 0 | 98 |
| First recorded card–merchant encounter | 66 | 897 | 65 |
| No prior approved purchase at merchant on this card | 148 | 937 | 147 |
| First recorded customer–merchant encounter | 40 | 495 | 39 |
| First recorded use of device on this card | 11 | 108 | 11 |
| First recorded merchant category on this card | 27 | 383 | 26 |
| First recorded country on this card | 29 | 93 | 29 |
| Amount above prior approved-purchase p95 (20+ samples) | 19 | 205 | 19 |
| At least 3 earlier card attempts within 10 minutes | 13 | 33 | 13 |
| Earlier decline at same merchant within 10 minutes | 36 | 48 | 36 |
| UTC hour absent from 20+ prior approved purchases | 48 | 282 | 48 |
| Merchant country is not CH (context only) | 144 | 634 | 144 |

## Interpretation

- Every evidence query uses timestamp < current timestamp. Equal-timestamp events are excluded.
- First encounter means no prior record within the supplied history; absence is not proof of no lifetime relationship.
- Approved purchases establish familiarity and amount baselines. Month-to-date account totals include approved refunds and cash withdrawals.
- Above-p95 and unseen-hour checks require at least 20 earlier approved card purchases; burst means at least 3 earlier attempts in 10 minutes. These are diagnostic thresholds, not recovered issuer logic.
- Foreign merchant means country != CH in this Swiss fixture. It is context, not a decline cause.
- Observable rule conflicts compare supplied fields; issuer enforcement and account balance are unknown. The dictionary specifically documents card-lifecycle declines, but has no per-event reason code.
- Factor groups overlap. Control rates use purchases only, and are descriptive associations, not causal estimates.
- An unexplained case is not evidence of a system error or random decline; the actual logic is unavailable.
