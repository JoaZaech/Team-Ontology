"""Generate customer-confirmable wallet-policy drafts from precomputed graph history."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping


RECOMMENDATION_VERSION = "policy-recommendation-v1"
MINIMUM_APPROVED_PURCHASES = 3
PROFILE_DATASET_CATEGORIES = {
    "Groceries": frozenset({"groceries"}),
    "Transport": frozenset({"transport", "fuel"}),
    "Dining": frozenset({"dining", "food_delivery"}),
    "Shopping": frozenset({
        "books", "clothing", "cosmetics", "electronics", "gift_card", "health",
        "home_improvement", "household", "sporting_goods",
    }),
}


def _percentile(amounts: list[int], quantile: float) -> int:
    return amounts[math.ceil(len(amounts) * quantile) - 1]


def _round_up_to_five_chf(amount_cents: int) -> int:
    return math.ceil(amount_cents / 500) * 500


def _format_chf(amount_cents: int) -> str:
    return f"CHF {amount_cents / 100:,.2f}"


def _profile_recommendation(
    profile_category: str,
    approved_rows: list[Mapping[str, Any]],
    declined_count: int,
) -> dict[str, Any]:
    ordered_rows = sorted(approved_rows, key=lambda row: int(row["billing_amount_chf"]))
    amounts = [int(row["billing_amount_chf"]) for row in ordered_rows]
    median = _percentile(amounts, 0.5)
    p95 = _percentile(amounts, 0.95)
    maximum = _round_up_to_five_chf(p95)
    profile = {
        "maximumChf": maximum / 100,
        "typicalRange": f"{_format_chf(median)}-{_format_chf(p95)}",
        "explanation": (
            f"Based on {len(approved_rows)} approved {profile_category.lower()} purchases "
            "in the precomputed knowledge graph."
        ),
    }
    return {
        "recommendation_id": f"category-maximum-{profile_category.lower()}",
        "kind": "adaptive_spend_profile",
        "profile_category": profile_category,
        "name": f"{profile_category} approval maximum",
        "description": (
            f"Set a {profile_category.lower()} maximum that covers the highest usual "
            "approved amounts in your card history."
        ),
        "rule": (
            f"Automatically approve familiar {profile_category.lower()} purchases up to "
            f"{_format_chf(maximum)} when every other saved rule passes."
        ),
        "profile": profile,
        "signals": [
            {"value": str(len(approved_rows)), "label": f"approved {profile_category.lower()} purchases"},
            {"value": _format_chf(median), "label": "typical approved amount"},
            {"value": _format_chf(p95), "label": "high usual amount"},
            {"value": str(declined_count), "label": "past declines shown as context"},
        ],
        "evidence": {
            "approved_purchase_count": len(approved_rows),
            "declined_purchase_count": declined_count,
            "supporting_event_ids": [row["authorization_id"] for row in ordered_rows],
            "calculation": "approved_purchase_p95_rounded_up_to_chf_5",
        },
        "requires_customer_confirmation": True,
    }


def _matching_profiles(row: Mapping[str, Any]) -> list[str]:
    return [
        profile_category
        for profile_category, categories in PROFILE_DATASET_CATEGORIES.items()
        if row.get("merchant_category") in categories
    ]


def _profile_history(rows: list[Mapping[str, Any]]) -> tuple[dict[str, list[Mapping[str, Any]]], dict[str, int]]:
    approved_by_profile: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    declined_by_profile: dict[str, int] = defaultdict(int)
    for row in rows:
        if row.get("transaction_type") != "purchase":
            continue
        target = approved_by_profile if row.get("status") == "approved" else declined_by_profile
        if row.get("status") not in {"approved", "declined"}:
            continue
        for profile_category in _matching_profiles(row):
            if target is approved_by_profile:
                target[profile_category].append(row)
            else:
                target[profile_category] += 1
    return approved_by_profile, declined_by_profile


def _recommendations_for_card(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    approved_by_profile, declined_by_profile = _profile_history(rows)
    return [
        _profile_recommendation(
            profile_category,
            approved_by_profile[profile_category],
            declined_by_profile[profile_category],
        )
        for profile_category in PROFILE_DATASET_CATEGORIES
        if len(approved_by_profile[profile_category]) >= MINIMUM_APPROVED_PURCHASES
    ]


def _source_as_of(rows: list[Mapping[str, Any]]) -> set[str]:
    return {
        source["source_as_of"]
        for row in rows
        for source in [row.get("_source")]
        if isinstance(source, Mapping) and isinstance(source.get("source_as_of"), str)
    }


def build_policy_recommendations(history_by_card: Mapping[str, list[Mapping[str, Any]]]) -> dict[str, Any]:
    """Create recommendation drafts without treating declines as customer preferences."""

    by_card: dict[str, list[dict[str, Any]]] = {}
    source_as_of: set[str] = set()
    for card_id, rows in sorted(history_by_card.items()):
        source_as_of.update(_source_as_of(rows))
        recommendations = _recommendations_for_card(rows)
        if recommendations:
            by_card[card_id] = recommendations
    return {
        "recommendation_version": RECOMMENDATION_VERSION,
        "generated_from": {
            "artifact": "historical_evidence_index.json",
            "source_as_of": max(source_as_of) if source_as_of else None,
            "calculation": "approved_purchase_p95_rounded_up_to_chf_5",
        },
        "by_card": by_card,
    }