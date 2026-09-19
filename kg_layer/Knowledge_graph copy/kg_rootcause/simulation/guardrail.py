"""Simulation only. These checks are not the live authorization guardrail."""
from datetime import timedelta
from ..common import timestamp
from ..schema import validate


def simulate_checks(transaction, policy, context, state):
    validate("ConfirmedPolicy", policy)
    if policy["status"] not in ("confirmed", "simulation_assumption"):
        raise ValueError("Unconfirmed policy cannot authorize")
    t = transaction
    if policy["scope"] != t["scenario_id"]:
        raise ValueError("Policy scope mismatch")
    cutoff = timestamp(t["timestamp"])
    prior = [e for e in state["events"] if e["authority_id"] == t["authority_id"] and e["status"] == "approved" and cutoff - timedelta(days=policy["rolling_days"]) <= timestamp(e["timestamp"]) < cutoff]
    total = sum(e["billing_amount_chf"] for e in prior)
    checks = []
    def add(rule, passed, expected, observed, kind="hard", events=()):
        checks.append({"rule": rule, "kind": kind, "status": "unknown" if passed is None else ("pass" if passed else "fail"), "expected": expected, "observed": observed, "source_event_ids": list(events)})
    add("maximum_order", t["billing_amount_chf"] <= policy["maximum_order_cents"], policy["maximum_order_cents"], t["billing_amount_chf"])
    add("rolling_budget", total + t["billing_amount_chf"] <= policy["rolling_limit_cents"], policy["rolling_limit_cents"], total + t["billing_amount_chf"], events=[e["authorization_id"] for e in prior])
    items = context["entities"]["items"]
    add("item_category", all(r["item_category"] in policy["item_categories"] for r in items) if items else None, policy["item_categories"], [r["item_category"] for r in items])
    add("delivery", t["fulfillment_method"] == policy["fulfillment_method"], policy["fulfillment_method"], t["fulfillment_method"])
    add("card_active", t["card_status_at_attempt"] == "active", "active", t["card_status_at_attempt"])
    authority = context["entities"]["authority"]
    active = t["authority_status"] == "active" and timestamp(authority["valid_from"]) <= cutoff < timestamp(authority["valid_until"])
    add("authority_active", active, "active within validity interval", t["authority_status"])
    add("required_evidence", not context["missing_evidence"], [], context["missing_evidence"], "uncertainty")
    duplicate = t.get("related_authorization_id")
    approved = [e["authorization_id"] for e in state["events"] if e["status"] == "approved" and timestamp(e["timestamp"]) < cutoff]
    add("related_approved_purchase", duplicate not in approved, "no related approved purchase", duplicate, "uncertainty", [duplicate] if duplicate in approved else [])
    merchant = context["historical_evidence"]["card_merchant"]
    add("merchant_familiarity", merchant["approved_count"] > 0, "prior approved purchase", merchant["approved_count"], "uncertainty", merchant["supporting_event_ids"])
    validate("GuardrailCheckInput", {"transaction": t, "confirmed_policy": policy, "context": context, "checks": checks})
    return checks
