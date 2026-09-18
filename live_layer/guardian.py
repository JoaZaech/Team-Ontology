"""Deterministic pre-payment checks adapted to Viseca's synthetic data.

This is a guard result, not the complete wallet-policy decision. A caller must
also check the customer's confirmed item, order-term, and other permissions.
No network service, blockchain registry, or model is used here.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


ENGINE_VERSION = "viseca-guardian-v1"


def _money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("amount must be numeric") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("amount must be finite and non-negative")
    return amount


@dataclass(frozen=True)
class GuardPolicy:
    """Limits supplied by the trusted, customer-confirmed policy layer."""

    max_purchase_chf: Decimal | None = None
    max_period_chf: Decimal | None = None
    approved_spend_in_period_chf: Decimal | None = None
    require_familiar_merchant: bool = False
    max_recent_attempts_10m: int = 3


class MerchantHistory:
    def __init__(self, merchants: dict[str, dict[str, str]], approved: Counter):
        self.merchants = merchants
        self.approved = approved

    @classmethod
    def from_data_dir(cls, data_dir: str | Path) -> "MerchantHistory":
        data_dir = Path(data_dir)
        with (data_dir / "merchants.csv").open(newline="", encoding="utf-8") as stream:
            merchants = {row["merchant_id"]: row for row in csv.DictReader(stream)}
        approved: Counter = Counter()
        with (data_dir / "authorization_history.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            for row in csv.DictReader(stream):
                if row["status"] == "approved" and row["transaction_type"] == "purchase":
                    approved[row["card_id"], row["merchant_id"]] += 1
        return cls(merchants, approved)


def evaluate_guard(
    event: Mapping[str, Any], history: MerchantHistory, policy: GuardPolicy
) -> dict[str, Any]:
    """Return an auditable guard decision without mutating spend or history.

    ``approve`` means these three checks passed; it is not permission to bypass
    the rest of the customer's wallet policy. An uncertain check becomes
    ``step_up``. A known hard-limit breach becomes ``decline``.
    """

    authorization = event["authorization"]
    merchant = authorization["merchant"]
    amount = _money(authorization["billing_amount_chf"])
    merchant_id = merchant["merchant_id"]
    card_id = authorization["card_id"]
    checks: list[dict[str, Any]] = []

    def add(name: str, outcome: str, code: str, **evidence: Any) -> None:
        checks.append({"name": name, "outcome": outcome, "reason_code": code,
                       "evidence": evidence})

    if policy.max_purchase_chf is None:
        add("spend_cap", "review", "purchase_limit_unavailable")
    elif amount > _money(policy.max_purchase_chf):
        add("spend_cap", "fail", "purchase_limit_exceeded",
            amount_chf=str(amount), limit_chf=str(policy.max_purchase_chf))
    else:
        add("spend_cap", "pass", "purchase_within_limit",
            amount_chf=str(amount), limit_chf=str(policy.max_purchase_chf))

    if policy.max_period_chf is not None:
        if policy.approved_spend_in_period_chf is None:
            add("period_cap", "review", "period_spend_unavailable")
        else:
            spent = _money(policy.approved_spend_in_period_chf)
            cap = _money(policy.max_period_chf)
            add("period_cap", "fail" if spent + amount > cap else "pass",
                "period_limit_exceeded" if spent + amount > cap else "period_within_limit",
                projected_chf=str(spent + amount), limit_chf=str(cap))

    catalogue = history.merchants.get(merchant_id)
    familiarity = history.approved[card_id, merchant_id]
    if catalogue is None:
        add("merchant_trust", "review", "merchant_not_in_catalogue",
            merchant_id=merchant_id)
    elif any(merchant.get(field) != catalogue[field] for field in (
        "merchant_name", "merchant_category", "merchant_mcc", "merchant_country"
    )):
        add("merchant_trust", "review", "merchant_identity_mismatch",
            merchant_id=merchant_id)
    elif policy.require_familiar_merchant and familiarity == 0:
        add("merchant_trust", "review", "merchant_unfamiliar_to_card",
            merchant_id=merchant_id, prior_approved_purchases=0)
    else:
        add("merchant_trust", "pass", "merchant_catalogue_match",
            merchant_id=merchant_id, prior_approved_purchases=familiarity)

    recent = authorization["recent_attempt_count_10m"]
    if not isinstance(recent, int) or isinstance(recent, bool) or recent < 0:
        add("rate_anomaly", "review", "recent_attempt_count_invalid")
    elif recent >= policy.max_recent_attempts_10m:
        add("rate_anomaly", "review", "attempt_velocity_high",
            prior_attempts_10m=recent, threshold=policy.max_recent_attempts_10m)
    else:
        add("rate_anomaly", "pass", "attempt_velocity_normal",
            prior_attempts_10m=recent, threshold=policy.max_recent_attempts_10m)

    outcomes = {check["outcome"] for check in checks}
    decision = "decline" if "fail" in outcomes else "step_up" if "review" in outcomes else "approve"
    return {
        "authorization_id": authorization["authorization_id"],
        "decision": decision,
        "reason_codes": [c["reason_code"] for c in checks if c["outcome"] != "pass"],
        "checks": checks,
        "engine_version": ENGINE_VERSION,
    }
