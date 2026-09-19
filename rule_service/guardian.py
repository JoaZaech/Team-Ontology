"""Deterministic pre-payment checks adapted to Viseca's synthetic data.

This is a guard result, not the complete wallet-policy decision. A caller must
also check the customer's confirmed item, order-term, and other permissions.
No network service, blockchain registry, or model is used here.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
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
    """Trusted, read-only context derived from the supplied Viseca data pack.

    The name is retained for backwards compatibility with the first guardian
    prototype.  Besides merchant familiarity it now exposes the two additional
    transaction facts used by the wallet-policy layer: approved-device counts
    and calendar-day completed spend.  The agent never supplies either value.
    """

    def __init__(
        self,
        merchants: dict[str, dict[str, str]],
        approved: Counter,
        approved_devices: Counter | None = None,
        approved_daily_spend: Counter | None = None,
        items: dict[str, dict[str, str]] | None = None,
        approved_merchant_times: dict[tuple[str, str], list[datetime]] | None = None,
        approved_device_times: dict[tuple[str, str], list[datetime]] | None = None,
        approved_country_times: dict[tuple[str, str], list[datetime]] | None = None,
    ):
        self.merchants = merchants
        self.approved = approved
        self.approved_devices = approved_devices or Counter()
        self.approved_daily_spend = approved_daily_spend or Counter()
        self.items = items or {}
        self.approved_merchant_times = approved_merchant_times or {}
        self.approved_device_times = approved_device_times or {}
        self.approved_country_times = approved_country_times or {}

    @classmethod
    def from_data_dir(cls, data_dir: str | Path) -> "MerchantHistory":
        data_dir = Path(data_dir)
        with (data_dir / "merchants.csv").open(newline="", encoding="utf-8") as stream:
            merchants = {row["merchant_id"]: row for row in csv.DictReader(stream)}
        with (data_dir / "items.csv").open(newline="", encoding="utf-8") as stream:
            items = {row["item_id"]: row for row in csv.DictReader(stream)}
        approved: Counter = Counter()
        approved_devices: Counter = Counter()
        approved_daily_spend: Counter = Counter()
        approved_merchant_times: dict[tuple[str, str], list[datetime]] = {}
        approved_device_times: dict[tuple[str, str], list[datetime]] = {}
        approved_country_times: dict[tuple[str, str], list[datetime]] = {}
        with (data_dir / "authorization_history.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            for row in csv.DictReader(stream):
                if row["status"] == "approved" and row["transaction_type"] == "purchase":
                    timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                    approved[row["card_id"], row["merchant_id"]] += 1
                    approved_merchant_times.setdefault(
                        (row["card_id"], row["merchant_id"]), []
                    ).append(timestamp)
                    approved_country_times.setdefault(
                        (row["card_id"], row["merchant_country"]), []
                    ).append(timestamp)
                    if row["customer_device_id"]:
                        approved_devices[row["card_id"], row["customer_device_id"]] += 1
                        approved_device_times.setdefault(
                            (row["card_id"], row["customer_device_id"]), []
                        ).append(timestamp)

                # A completed refund reverses spend.  Declines and pending-like
                # attempts never enter this trusted, completed-spend context.
                if row["status"] == "approved" and row["transaction_type"] in {"purchase", "refund"}:
                    timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                    approved_daily_spend[row["card_id"], timestamp.date().isoformat()] += Decimal(
                        row["billing_amount_chf"]
                    )
        return cls(
            merchants,
            approved,
            approved_devices,
            approved_daily_spend,
            items,
            approved_merchant_times,
            approved_device_times,
            approved_country_times,
        )

    def approved_device_count(self, card_id: str, device_id: str) -> int:
        """Return prior approved transactions for a card/device pair."""

        return self.approved_devices[card_id, device_id]

    def approved_spend_on(self, card_id: str, date: str) -> Decimal:
        """Return dataset-backed completed spend for one card/calendar day."""

        return Decimal(self.approved_daily_spend[card_id, date])

    def approved_merchant_count_before(
        self, card_id: str, merchant_id: str, timestamp: str
    ) -> int:
        moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return sum(
            approved_at < moment
            for approved_at in self.approved_merchant_times.get((card_id, merchant_id), [])
        )

    def approved_device_count_before(
        self, card_id: str, device_id: str, timestamp: str
    ) -> int:
        moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return sum(
            approved_at < moment
            for approved_at in self.approved_device_times.get((card_id, device_id), [])
        )

    def approved_country_count_before(
        self, card_id: str, country: str, timestamp: str
    ) -> int:
        moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return sum(
            approved_at < moment
            for approved_at in self.approved_country_times.get((card_id, country), [])
        )


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
