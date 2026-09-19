"""Small confirmed rulebook for the Viseca SCEN0000 local demonstration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from guardian import GuardPolicy, MerchantHistory, _money, evaluate_guard
from wallet_policy import evaluate_wallet_policy


@dataclass(frozen=True)
class ConfirmedRules:
    """Customer-confirmed facts that are not in Viseca's generic hard-rule list."""

    item_category: str = "groceries"
    item_count: int = 1
    require_familiar_merchant: bool = True


def evaluate_request(
    event: Mapping[str, Any], history: MerchantHistory,
    rules: ConfirmedRules = ConfirmedRules(),
    wallet_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess one live-event-shaped purchase without changing account state.

    ``wallet_policy`` is an optional server-owned customer-policy snapshot.
    The static mandate checks above remain the hard baseline; dynamic policy
    checks are additive and therefore can only tighten a decision.
    """

    authorization = event["authorization"]
    mandate = event["mandate"]
    checks: list[dict[str, Any]] = []

    def add(name: str, outcome: str, code: str, detail: str) -> None:
        checks.append({"name": name, "outcome": outcome,
                       "reason_code": code, "detail": detail})

    if (mandate["status"] != "active" or
            mandate["card_id"] != authorization["card_id"] or
            mandate["mandate_id"] != authorization["mandate_id"] or
            authorization["authority_status"] != "active" or
            authorization["card_status_at_attempt"] != "active"):
        add("buyer authority", "fail", "buyer_or_mandate_inactive",
            "The mandate, card, and authority must be active and bound together.")
    else:
        add("buyer authority", "pass", "buyer_authorized",
            "The active mandate is bound to this card.")

    items = authorization["items"]
    if (len(items) != rules.item_count or
            any(item["item_category"] != rules.item_category for item in items)):
        add("requested basket", "fail", "basket_outside_instruction",
            "The order must contain one grocery item and no additions.")
    else:
        add("requested basket", "pass", "basket_matches_instruction",
            "The order contains one grocery item.")

    try:
        if authorization["currency"] != "CHF" or any(
            item["currency"] != "CHF" for item in items
        ):
            add("order total", "review", "currency_needs_review",
                "This mock rulebook only reconciles CHF item prices.")
        else:
            subtotal = sum((_money(item["unit_price"]) * item["quantity"]
                            for item in items), Decimal("0"))
            total = subtotal + _money(authorization["delivery_fee"])
            if (total != _money(authorization["billing_amount_chf"]) or
                    subtotal != _money(authorization["items_subtotal"])):
                add("order total", "review", "order_total_mismatch",
                    "The billed total does not reconcile with the item prices and delivery fee. Human review is required.")
            else:
                add("order total", "pass", "order_total_verified",
                    f"CHF {subtotal:.2f} in items plus CHF {_money(authorization['delivery_fee']):.2f} delivery.")
    except (ValueError, TypeError, KeyError):
        add("order total", "review", "order_total_unverifiable",
            "The order total could not be reconciled.")

    amount_rule = next((rule for rule in mandate["hard_rules"]
                        if rule.get("field") == "authorization.billing_amount_chf"
                        and rule.get("operator") == "<="
                        and rule.get("scope") == "purchase"
                        and rule.get("currency") == "CHF"), None)
    limit = _money(amount_rule["value"]) if amount_rule else None
    guard = evaluate_guard(event, history, GuardPolicy(
        max_purchase_chf=limit,
        require_familiar_merchant=rules.require_familiar_merchant,
    ))
    for check in guard["checks"]:
        evidence = check["evidence"]
        if check["name"] == "spend_cap":
            name = "Spend limit"
            if check["outcome"] == "review":
                detail = "No confirmed purchase limit is available."
            else:
                relation = "within" if check["outcome"] == "pass" else "above"
                detail = (f"CHF {Decimal(evidence['amount_chf']):.2f} is {relation} the "
                          f"CHF {Decimal(evidence['limit_chf']):.2f} purchase limit.")
        elif check["name"] == "merchant_trust":
            name = "Merchant familiarity"
            count = evidence.get("prior_approved_purchases", 0)
            detail = (f"{authorization['merchant']['merchant_name']} matches the catalogue; "
                      f"this card has {count} prior approved purchases there.") if check["outcome"] == "pass" else "The merchant identity or familiarity needs customer review."
        else:
            name = "Recent attempts"
            detail = (f"{evidence['prior_attempts_10m']} earlier attempts in ten minutes; "
                      f"review starts at {evidence['threshold']}.") if check["outcome"] == "pass" else "Repeated attempts need customer review."
        checks.append({"name": name,
                       "outcome": check["outcome"],
                       "reason_code": check["reason_code"],
                       "detail": detail})

    if wallet_policy is not None:
        checks.extend(evaluate_wallet_policy(event, history, wallet_policy))

    outcomes = {check["outcome"] for check in checks}
    decision = "decline" if "fail" in outcomes else "step_up" if "review" in outcomes else "approve"
    return {
        "authorization_id": authorization["authorization_id"],
        "recommended_decision": decision,
        "reason_codes": [check["reason_code"] for check in checks
                         if check["outcome"] != "pass"],
        "checks": checks,
        "engine_version": "viseca-mock-rulebook-v2" if wallet_policy is not None else "viseca-mock-rulebook-v1",
    }
