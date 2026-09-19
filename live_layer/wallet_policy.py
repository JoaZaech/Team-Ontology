"""Versioned customer wallet policy and deterministic policy checks.

This module deliberately has no HTTP or browser dependency.  It accepts a
canonical Viseca-shaped event plus trusted history loaded from the synthetic
data pack, and returns explainable checks suitable for a decision receipt.
The agent proposal is never treated as a source of policy or history facts.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


REVIEW_TRIGGERS = frozenset({"new_merchant", "online_purchase", "unusual_activity"})
ASSISTANT_AUTHORITIES = frozenset({"review", "trusted", "autopilot"})
SPEND_CATEGORIES = ("Groceries", "Transport", "Dining", "Shopping")

# The policy UI uses customer-facing labels while the Viseca data pack uses a
# stable lowercase vocabulary.  This mapping is intentionally explicit rather
# than inferred from merchant-provided text.
CATEGORY_TO_DATASET = {
    "Groceries": frozenset({"groceries"}),
    "Transport": frozenset({"transport", "fuel"}),
    "Dining": frozenset({"dining", "food_delivery"}),
    "Shopping": frozenset({"books", "clothing", "cosmetics", "electronics", "gift_card", "health", "home_improvement", "household", "sporting_goods"}),
}


class PolicyValidationError(ValueError):
    """Raised when a customer-policy update cannot be made executable."""


class PolicyConflictError(PolicyValidationError):
    """Raised when a write was based on an obsolete policy revision."""


def _money(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise PolicyValidationError(f"{field} must be a number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PolicyValidationError(f"{field} must be a number") from exc
    if not result.is_finite() or result < 0:
        raise PolicyValidationError(f"{field} must be a non-negative finite number")
    return result


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def default_wallet_policy_document() -> dict[str, Any]:
    """Return the server-owned default used by the local demonstration.

    The confirmed mandate still has the stricter CHF 20 purchase ceiling.  The
    dynamic policy adds an independent daily limit, category limits, and a
    customer-selected prompt for a first purchase with a merchant.
    """

    return {
        "policyId": "wallet-policy_CA0001_default",
        "schemaVersion": "2026-09-01",
        "revision": 1,
        "subject": {"customerId": "CU0001", "cardId": "CA0001"},
        "enabled": True,
        "dailySpendingLimitChf": 1500,
        "adaptiveSpendProfiles": {
            "Groceries": {
                "maximumChf": 180,
                "typicalRange": "CHF 35–180",
                "explanation": "Derived from the supplied card transaction history.",
            },
            "Transport": {
                "maximumChf": 90,
                "typicalRange": "CHF 12–90",
                "explanation": "Derived from the supplied card transaction history.",
            },
            "Dining": {
                "maximumChf": 140,
                "typicalRange": "CHF 25–140",
                "explanation": "Derived from the supplied card transaction history.",
            },
            "Shopping": {
                "maximumChf": 250,
                "typicalRange": "CHF 40–250",
                "explanation": "Derived from the supplied card transaction history.",
            },
        },
        "reviewTriggers": ["new_merchant"],
        "assistantAuthority": "trusted",
        "effectiveFrom": "2026-09-19T00:00:00.000Z",
        "updatedAt": "2026-09-19T10:42:00.000Z",
        "updatedBy": "customer",
    }


def _validate_profiles(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping) or set(value) != set(SPEND_CATEGORIES):
        raise PolicyValidationError("adaptiveSpendProfiles must contain every supported category")
    profiles: dict[str, dict[str, Any]] = {}
    for category in SPEND_CATEGORIES:
        profile = value[category]
        if not isinstance(profile, Mapping):
            raise PolicyValidationError(f"{category} profile must be an object")
        maximum = _money(profile.get("maximumChf"), f"{category} maximumChf")
        typical_range = profile.get("typicalRange")
        explanation = profile.get("explanation")
        if not isinstance(typical_range, str) or not isinstance(explanation, str):
            raise PolicyValidationError(f"{category} profile text is invalid")
        profiles[category] = {
            "maximumChf": float(maximum),
            "typicalRange": typical_range,
            "explanation": explanation,
        }
    return profiles


def validate_policy_patch(patch: Any) -> dict[str, Any]:
    """Validate a UI policy patch before it can reach the evaluator."""

    if not isinstance(patch, Mapping):
        raise PolicyValidationError("patch must be an object")
    allowed = {
        "enabled",
        "dailySpendingLimitChf",
        "adaptiveSpendProfiles",
        "reviewTriggers",
        "assistantAuthority",
    }
    unexpected = set(patch) - allowed
    if unexpected:
        raise PolicyValidationError("policy patch contains unsupported fields")

    validated: dict[str, Any] = {}
    if "enabled" in patch:
        if not isinstance(patch["enabled"], bool):
            raise PolicyValidationError("enabled must be a boolean")
        validated["enabled"] = patch["enabled"]
    if "dailySpendingLimitChf" in patch:
        validated["dailySpendingLimitChf"] = float(
            _money(patch["dailySpendingLimitChf"], "dailySpendingLimitChf")
        )
    if "adaptiveSpendProfiles" in patch:
        validated["adaptiveSpendProfiles"] = _validate_profiles(patch["adaptiveSpendProfiles"])
    if "reviewTriggers" in patch:
        triggers = patch["reviewTriggers"]
        if (
            not isinstance(triggers, list)
            or any(not isinstance(trigger, str) for trigger in triggers)
            or len(set(triggers)) != len(triggers)
            or not set(triggers).issubset(REVIEW_TRIGGERS)
        ):
            raise PolicyValidationError("reviewTriggers contains an unsupported trigger")
        validated["reviewTriggers"] = list(triggers)
    if "assistantAuthority" in patch:
        authority = patch["assistantAuthority"]
        if authority not in ASSISTANT_AUTHORITIES:
            raise PolicyValidationError("assistantAuthority is unsupported")
        validated["assistantAuthority"] = authority
    return validated


class WalletPolicyStore:
    """Small in-memory, versioned store used by the local mock services.

    It models the same optimistic-concurrency contract the frontend exposes.
    Production storage belongs behind this boundary; the pure evaluator only
    receives an immutable snapshot from ``get``.
    """

    def __init__(self, initial: Mapping[str, Any] | None = None):
        self._stored = deepcopy(dict(initial or default_wallet_policy_document()))

    def get(self) -> dict[str, Any]:
        return deepcopy(self._stored)

    def update(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise PolicyValidationError("policy update must be an object")
        if set(request) != {"policyId", "expectedRevision", "patch"}:
            raise PolicyValidationError("policy update fields are invalid")
        if request["policyId"] != self._stored["policyId"]:
            raise PolicyValidationError("policy not found")
        revision = request["expectedRevision"]
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise PolicyValidationError("expectedRevision must be an integer")
        if revision != self._stored["revision"]:
            raise PolicyConflictError("policy revision conflict")
        patch = validate_policy_patch(request["patch"])
        self._stored = {
            **self._stored,
            **deepcopy(patch),
            "revision": self._stored["revision"] + 1,
            "updatedAt": _iso_now(),
            "updatedBy": "customer",
        }
        return self.get()


def _event_date(event: Mapping[str, Any]) -> str | None:
    try:
        timestamp = str(event["authorization"]["timestamp"])
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def _policy_categories(items: list[Mapping[str, Any]]) -> set[str]:
    return {str(item.get("item_category")) for item in items if item.get("item_category")}


def _profile_for_categories(categories: set[str]) -> str | None:
    for name, dataset_categories in CATEGORY_TO_DATASET.items():
        if categories and categories.issubset(dataset_categories):
            return name
    return None


def evaluate_wallet_policy(
    event: Mapping[str, Any], history: Any, document: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Evaluate the active customer policy using only trusted event/history facts.

    A confirmed mandate is evaluated elsewhere by ``rulebook.evaluate_request``.
    These checks are additive: a dynamic-policy failure can only tighten the
    result, and an unavailable material fact becomes a review rather than an
    implicit approval.
    """

    try:
        # Validation is intentionally re-run at the execution boundary.  A
        # malformed or tampered persisted document must not grant permission.
        validated_patch = validate_policy_patch({
            key: document[key]
            for key in (
                "enabled",
                "dailySpendingLimitChf",
                "adaptiveSpendProfiles",
                "reviewTriggers",
                "assistantAuthority",
            )
        })
    except (KeyError, PolicyValidationError):
        return [{
            "name": "Dynamic wallet policy",
            "outcome": "review",
            "reason_code": "policy_configuration_invalid",
            "detail": "The active dynamic policy could not be verified, so this purchase needs review.",
        }]

    authorization = event.get("authorization")
    if not isinstance(authorization, Mapping):
        return [{
            "name": "Dynamic wallet policy",
            "outcome": "review",
            "reason_code": "authorization_missing",
            "detail": "The purchase facts required by the dynamic policy are missing.",
        }]

    checks: list[dict[str, Any]] = []

    def add(name: str, outcome: str, reason_code: str, detail: str) -> None:
        checks.append({
            "name": name,
            "outcome": outcome,
            "reason_code": reason_code,
            "detail": detail,
        })

    if not validated_patch["enabled"]:
        add(
            "Dynamic wallet policy",
            "pass",
            "dynamic_policy_disabled",
            "The optional dynamic policy is disabled; the confirmed mandate still applies.",
        )
        return checks

    try:
        amount = _money(authorization["billing_amount_chf"], "authorization.billing_amount_chf")
        card_id = authorization["card_id"]
        if not isinstance(card_id, str) or not card_id:
            raise PolicyValidationError("authorization.card_id is invalid")
    except (KeyError, PolicyValidationError):
        add(
            "Daily spending limit",
            "review",
            "daily_limit_unverifiable",
            "The amount or card identifier needed for the daily limit is unavailable.",
        )
        return checks

    date = _event_date(event)
    if date is None:
        add(
            "Daily spending limit",
            "review",
            "purchase_date_unavailable",
            "The purchase timestamp needed for the daily spending limit is unavailable.",
        )
    else:
        spent = Decimal(history.approved_spend_on(card_id, date))
        limit = _money(validated_patch["dailySpendingLimitChf"], "dailySpendingLimitChf")
        projected = spent + amount
        if projected > limit:
            add(
                "Daily spending limit",
                "fail",
                "daily_spending_limit_exceeded",
                f"CHF {projected:.2f} would exceed the CHF {limit:.2f} daily limit (CHF {spent:.2f} completed today).",
            )
        else:
            add(
                "Daily spending limit",
                "pass",
                "daily_spending_within_limit",
                f"CHF {projected:.2f} stays within the CHF {limit:.2f} daily limit.",
            )

    items_value = authorization.get("items")
    items = [item for item in items_value if isinstance(item, Mapping)] if isinstance(items_value, list) else []
    categories = _policy_categories(items)
    profile_name = _profile_for_categories(categories)
    if not items or len(items) != len(items_value or []):
        add(
            "Category maximum",
            "review",
            "basket_categories_unavailable",
            "The item categories needed for the adaptive limit are unavailable.",
        )
    elif profile_name is None:
        add(
            "Category maximum",
            "pass",
            "category_limit_not_configured",
            "No adaptive maximum is configured for this basket category.",
        )
    else:
        category_limit = _money(
            validated_patch["adaptiveSpendProfiles"][profile_name]["maximumChf"],
            f"{profile_name} maximumChf",
        )
        if amount > category_limit:
            add(
                "Category maximum",
                "fail",
                "category_limit_exceeded",
                f"CHF {amount:.2f} is above the CHF {category_limit:.2f} {profile_name.lower()} maximum.",
            )
        else:
            add(
                "Category maximum",
                "pass",
                "category_limit_within_limit",
                f"CHF {amount:.2f} is within the CHF {category_limit:.2f} {profile_name.lower()} maximum.",
            )

    merchant = authorization.get("merchant")
    merchant_id = merchant.get("merchant_id") if isinstance(merchant, Mapping) else None
    familiarity: int | None = None
    if isinstance(merchant_id, str) and merchant_id:
        familiarity = int(history.approved[card_id, merchant_id])

    triggers = set(validated_patch["reviewTriggers"])
    if "new_merchant" in triggers:
        if familiarity is None:
            add(
                "New merchant review",
                "review",
                "merchant_familiarity_unavailable",
                "The merchant identifier needed to check your first-purchase preference is unavailable.",
            )
        elif familiarity == 0:
            add(
                "New merchant review",
                "review",
                "new_merchant_confirmation_required",
                "This is a new merchant for this card, and your policy asks before a first purchase.",
            )
        else:
            add(
                "New merchant review",
                "pass",
                "merchant_seen_before",
                f"This card has {familiarity} prior approved purchases with this merchant.",
            )

    if "online_purchase" in triggers:
        channel = authorization.get("channel")
        if channel in {"ecommerce", "recurring"}:
            add(
                "Online purchase review",
                "review",
                "online_purchase_confirmation_required",
                "Your policy asks you to confirm card-not-present purchases.",
            )
        elif isinstance(channel, str) and channel:
            add(
                "Online purchase review",
                "pass",
                "online_purchase_not_applicable",
                "This purchase is not on a card-not-present channel.",
            )
        else:
            add(
                "Online purchase review",
                "review",
                "purchase_channel_unavailable",
                "The purchase channel needed for your online-purchase preference is unavailable.",
            )

    if "unusual_activity" in triggers:
        recent = authorization.get("recent_attempt_count_10m")
        device_id = authorization.get("customer_device_id")
        if not isinstance(recent, int) or isinstance(recent, bool) or recent < 0:
            add(
                "Unusual activity review",
                "review",
                "attempt_context_unavailable",
                "The recent-attempt signal needed for your unusual-activity preference is unavailable.",
            )
        elif recent >= 3:
            add(
                "Unusual activity review",
                "review",
                "unusual_attempt_velocity",
                f"There were {recent} earlier attempts in ten minutes, so your policy asks for confirmation.",
            )
        elif isinstance(device_id, str) and device_id and history.approved_device_count(card_id, device_id) == 0:
            add(
                "Unusual activity review",
                "review",
                "unfamiliar_device_confirmation_required",
                "This device has no prior approved purchases for this card, so your policy asks for confirmation.",
            )
        else:
            add(
                "Unusual activity review",
                "pass",
                "activity_within_expected_pattern",
                "The recent-attempt and device signals match this card's known activity.",
            )

    authority = validated_patch["assistantAuthority"]
    if authority == "review":
        add(
            "Assistant approval access",
            "review",
            "customer_review_required",
            "Your approval-access setting asks you before every purchase.",
        )
    elif authority == "trusted" and familiarity == 0:
        add(
            "Assistant approval access",
            "review",
            "trusted_merchant_required",
            "Your assistant may approve trusted purchases only; this merchant is new to this card.",
        )
    else:
        description = "Your assistant may approve a purchase that passes every active rule."
        if authority == "trusted":
            description = "This familiar purchase can be approved automatically after every active rule passes."
        add("Assistant approval access", "pass", "assistant_authorized", description)

    return checks
