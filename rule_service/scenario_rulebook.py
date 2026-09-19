from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
import re
from typing import Any, Iterable, Mapping

from benchmark_policy import BenchmarkPolicyValidationError, validate_event_binding
from guardian import MerchantHistory, _money
from wallet_policy import evaluate_wallet_policy


ENGINE_VERSION = "viseca-scenario-rulebook-v1"
RETURN_DAYS = re.compile(r"\breturns?\s+accepted\s+within\s+(\d+)\s+days?\b", re.IGNORECASE)


def _event_time(event: Mapping[str, Any]) -> datetime:
    return datetime.fromisoformat(str(event["authorization"]["timestamp"]).replace("Z", "+00:00"))


def _item_signature(items: Iterable[Mapping[str, Any]]) -> tuple[tuple[str, int], ...]:
    signature: list[tuple[str, int]] = []
    for item in items:
        item_id = item.get("item_id")
        quantity = item.get("quantity")
        if not isinstance(item_id, str) or not isinstance(quantity, int) or isinstance(quantity, bool):
            raise ValueError("item signature is invalid")
        signature.append((item_id, quantity))
    return tuple(sorted(signature))


def _catalogue_item_categories(
    items: list[Mapping[str, Any]], history: MerchantHistory
) -> tuple[set[str], bool]:
    categories: set[str] = set()
    complete = True
    for item in items:
        item_id = item.get("item_id")
        catalogue = history.items.get(item_id) if isinstance(item_id, str) else None
        if catalogue is None:
            complete = False
            continue
        if item.get("item_name") != catalogue["item_name"] or item.get("item_category") != catalogue["item_category"]:
            complete = False
            continue
        categories.add(catalogue["item_category"])
    return categories, complete


def _known_merchant_count(
    history: MerchantHistory, card_id: str, merchant_id: str, timestamp: str
) -> int:
    return history.approved_merchant_count_before(card_id, merchant_id, timestamp)


def _known_device_count(
    history: MerchantHistory, card_id: str, device_id: str, timestamp: str
) -> int:
    return history.approved_device_count_before(card_id, device_id, timestamp)


def _known_country_count(
    history: MerchantHistory, card_id: str, country: str, timestamp: str
) -> int:
    return history.approved_country_count_before(card_id, country, timestamp)


def evaluate_scenario_request(
    event: Mapping[str, Any],
    history: MerchantHistory,
    scenario_policy: Mapping[str, Any],
    wallet_policy: Mapping[str, Any] | None = None,
    prior_approved_events: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, outcome: str, reason_code: str, detail: str) -> None:
        checks.append({
            "name": name,
            "outcome": outcome,
            "reason_code": reason_code,
            "detail": detail,
        })

    try:
        validate_event_binding(scenario_policy, event)
        authorization = event["authorization"]
        rules = scenario_policy["rules"]
        authorization_id = authorization["authorization_id"]
        card_id = authorization["card_id"]
        timestamp = str(authorization["timestamp"])
        current_time = _event_time(event)
        if not isinstance(authorization_id, str) or not authorization_id:
            raise ValueError("authorization ID is invalid")
        if not isinstance(card_id, str) or not card_id:
            raise ValueError("card ID is invalid")
    except (BenchmarkPolicyValidationError, KeyError, TypeError, ValueError):
        add(
            "Policy binding",
            "fail",
            "policy_binding_mismatch",
            "The event does not match the server-owned policy binding.",
        )
        return {
            "authorization_id": event.get("authorization", {}).get("authorization_id", "unknown"),
            "recommended_decision": "decline",
            "reason_codes": ["policy_binding_mismatch"],
            "checks": checks,
            "engine_version": ENGINE_VERSION,
        }

    if (
        event["mandate"].get("status") != "active"
        or authorization.get("authority_status") != "active"
        or authorization.get("card_status_at_attempt") != "active"
    ):
        add(
            "Purchase authority",
            "fail",
            "authority_or_card_inactive",
            "The mandate, authority, and card must all be active.",
        )
    else:
        add(
            "Purchase authority",
            "pass",
            "authority_active",
            "The active mandate is bound to this card and scenario.",
        )

    try:
        amount = _money(authorization["billing_amount_chf"])
    except (KeyError, TypeError, ValueError):
        amount = None
        add(
            "Purchase amount",
            "review",
            "purchase_amount_unverifiable",
            "The billed CHF amount is unavailable or invalid.",
        )

    if amount is not None and "maxPurchaseChf" in rules:
        maximum = Decimal(str(rules["maxPurchaseChf"]))
        if amount > maximum:
            add(
                "Purchase limit",
                "fail",
                "purchase_limit_exceeded",
                f"CHF {amount:.2f} exceeds the CHF {maximum:.2f} purchase limit.",
            )
        else:
            add(
                "Purchase limit",
                "pass",
                "purchase_within_limit",
                f"CHF {amount:.2f} is within the CHF {maximum:.2f} purchase limit.",
            )

    merchant = authorization.get("merchant")
    catalogue_merchant: Mapping[str, str] | None = None
    merchant_id: str | None = None
    if isinstance(merchant, Mapping) and isinstance(merchant.get("merchant_id"), str):
        merchant_id = merchant["merchant_id"]
        catalogue_merchant = history.merchants.get(merchant_id)
    if catalogue_merchant is None:
        add(
            "Merchant identity",
            "review",
            "merchant_not_in_catalogue",
            "The merchant could not be verified against the trusted catalogue.",
        )
    elif any(
        str(merchant.get(field)) != catalogue_merchant[field]
        for field in ("merchant_name", "merchant_category", "merchant_mcc", "merchant_country")
    ):
        add(
            "Merchant identity",
            "review",
            "merchant_identity_mismatch",
            "The merchant facts do not match the trusted catalogue record.",
        )
    else:
        add(
            "Merchant identity",
            "pass",
            "merchant_catalogue_match",
            "The merchant identity matches the trusted catalogue.",
        )

    if "allowedMerchantCategories" in rules:
        if catalogue_merchant is None:
            add(
                "Merchant category",
                "review",
                "merchant_category_unverifiable",
                "The merchant category required by this policy could not be verified.",
            )
        elif catalogue_merchant["merchant_category"] not in rules["allowedMerchantCategories"]:
            add(
                "Merchant category",
                "fail",
                "merchant_category_not_allowed",
                "The merchant category is outside the customer-approved scope.",
            )
        else:
            add(
                "Merchant category",
                "pass",
                "merchant_category_allowed",
                "The merchant category is within the customer-approved scope.",
            )

    items_value = authorization.get("items")
    items = [item for item in items_value if isinstance(item, Mapping)] if isinstance(items_value, list) else []
    if not items or len(items) != len(items_value or []):
        add(
            "Requested basket",
            "review",
            "basket_unverifiable",
            "The requested basket is incomplete or invalid.",
        )
    else:
        categories, catalogue_complete = _catalogue_item_categories(items, history)
        if not catalogue_complete:
            add(
                "Requested basket",
                "review",
                "item_catalogue_mismatch",
                "One or more item facts do not match the trusted catalogue.",
            )
        if "exactItemCount" in rules:
            if len(items) != rules["exactItemCount"]:
                add(
                    "Requested basket",
                    "fail",
                    "item_count_not_allowed",
                    "The policy does not permit this number of items.",
                )
            else:
                add(
                    "Requested basket",
                    "pass",
                    "item_count_allowed",
                    "The basket contains the permitted number of items.",
                )
        if "allowedItemIds" in rules:
            item_ids = [item.get("item_id") for item in items]
            if any(item_id not in rules["allowedItemIds"] for item_id in item_ids):
                add(
                    "Requested basket",
                    "fail",
                    "item_not_requested",
                    "The basket contains an item outside the requested purchase.",
                )
            else:
                add(
                    "Requested basket",
                    "pass",
                    "requested_item_confirmed",
                    "Every basket item matches the requested product.",
                )
        if "allowedItemCategories" in rules:
            if not catalogue_complete:
                add(
                    "Requested basket",
                    "review",
                    "item_category_unverifiable",
                    "The item category required by this policy could not be verified.",
                )
            elif not categories.issubset(set(rules["allowedItemCategories"])):
                add(
                    "Requested basket",
                    "fail",
                    "item_category_not_allowed",
                    "The basket contains an item category outside the policy scope.",
                )
            else:
                add(
                    "Requested basket",
                    "pass",
                    "item_categories_allowed",
                    "Every item category is within the customer-approved scope.",
                )
        if "requiredItemText" in rules:
            details = " ".join(str(item.get("item_details", "")) for item in items).casefold()
            missing = [token for token in rules["requiredItemText"] if token.casefold() not in details]
            if missing:
                add(
                    "Requested product details",
                    "fail",
                    "required_product_detail_missing",
                    "The basket does not contain the product details required by the policy.",
                )
            else:
                add(
                    "Requested product details",
                    "pass",
                    "required_product_detail_confirmed",
                    "The required product details are present in the structured basket data.",
                )

    if "requiredFulfillmentMethods" in rules:
        method = authorization.get("fulfillment_method")
        if method not in rules["requiredFulfillmentMethods"]:
            add(
                "Fulfilment method",
                "fail",
                "fulfilment_method_not_allowed",
                "The fulfilment method is outside the policy scope.",
            )
        else:
            add(
                "Fulfilment method",
                "pass",
                "fulfilment_method_allowed",
                "The fulfilment method is permitted by the policy.",
            )

    if "minimumReturnDays" in rules:
        returnable = authorization.get("order_returnable")
        if returnable == "false":
            add(
                "Return terms",
                "fail",
                "return_terms_not_allowed",
                "The order is not returnable as required by the policy.",
            )
        elif returnable != "true":
            add(
                "Return terms",
                "review",
                "return_terms_unverifiable",
                "The order return terms need customer review.",
            )
        else:
            return_days = []
            for item in items:
                match = RETURN_DAYS.search(str(item.get("item_details", "")))
                if match is not None:
                    return_days.append(int(match.group(1)))
            if not return_days:
                add(
                    "Return terms",
                    "review",
                    "return_window_unverifiable",
                    "The return window required by the policy could not be verified.",
                )
            elif min(return_days) < rules["minimumReturnDays"]:
                add(
                    "Return terms",
                    "fail",
                    "return_window_too_short",
                    "The return window is shorter than the customer-approved minimum.",
                )
            else:
                add(
                    "Return terms",
                    "pass",
                    "return_window_allowed",
                    "The return window meets the customer-approved minimum.",
                )

    if "requireFamiliarMerchant" in rules and rules["requireFamiliarMerchant"]:
        if merchant_id is None:
            add(
                "Merchant familiarity",
                "review",
                "merchant_familiarity_unverifiable",
                "The merchant familiarity signal is unavailable.",
            )
        else:
            familiar_count = _known_merchant_count(history, card_id, merchant_id, timestamp)
            if familiar_count < 1:
                add(
                    "Merchant familiarity",
                    "review",
                    "merchant_confirmation_required",
                    "This merchant has no prior approved purchases for this card.",
                )
            else:
                add(
                    "Merchant familiarity",
                    "pass",
                    "merchant_seen_before",
                    f"This card has {familiar_count} prior approved purchases with this merchant.",
                )

    if "requireKnownDevice" in rules and rules["requireKnownDevice"]:
        device_id = authorization.get("customer_device_id")
        if not isinstance(device_id, str) or not device_id:
            add(
                "Session device",
                "review",
                "device_familiarity_unverifiable",
                "The device signal needed to assess session integrity is unavailable.",
            )
        else:
            device_count = _known_device_count(history, card_id, device_id, timestamp)
            if device_count < 1:
                add(
                    "Session device",
                    "review",
                    "new_device_confirmation_required",
                    "This device has no prior approved purchases for this card.",
                )
            else:
                add(
                    "Session device",
                    "pass",
                    "known_device",
                    f"This device has {device_count} prior approved purchases for this card.",
                )

    if "requireKnownMerchantCountry" in rules and rules["requireKnownMerchantCountry"]:
        country = catalogue_merchant.get("merchant_country") if catalogue_merchant else None
        if not country:
            add(
                "Merchant country",
                "review",
                "merchant_country_unverifiable",
                "The country signal needed to assess session integrity is unavailable.",
            )
        else:
            country_count = _known_country_count(history, card_id, country, timestamp)
            if country_count < 1:
                add(
                    "Merchant country",
                    "review",
                    "new_country_confirmation_required",
                    "This card has no prior approved purchases in this merchant country.",
                )
            else:
                add(
                    "Merchant country",
                    "pass",
                    "known_merchant_country",
                    "The merchant country appears in this card's approved purchase history.",
                )

    if "maxRecentAttempts" in rules:
        recent = authorization.get("recent_attempt_count_10m")
        if not isinstance(recent, int) or isinstance(recent, bool) or recent < 0:
            add(
                "Attempt velocity",
                "review",
                "attempt_velocity_unverifiable",
                "The attempt-velocity signal needed to assess session integrity is unavailable.",
            )
        elif recent >= rules["maxRecentAttempts"]:
            add(
                "Attempt velocity",
                "review",
                "attempt_velocity_high",
                "The recent attempt count needs customer confirmation.",
            )
        else:
            add(
                "Attempt velocity",
                "pass",
                "attempt_velocity_normal",
                "The recent attempt count is within the policy threshold.",
            )

    if amount is not None and "rollingPeriod" in rules:
        period = rules["rollingPeriod"]
        window_start = current_time - timedelta(days=period["days"])
        prior_spend = Decimal("0")
        try:
            for prior_event in prior_approved_events:
                prior_authorization = prior_event["authorization"]
                prior_time = _event_time(prior_event)
                if window_start <= prior_time < current_time:
                    prior_spend += _money(prior_authorization["billing_amount_chf"])
        except (KeyError, TypeError, ValueError):
            add(
                "Rolling spending limit",
                "review",
                "rolling_spend_unverifiable",
                "The server-owned approved-spend state could not be verified.",
            )
        else:
            maximum = Decimal(str(period["maximumChf"]))
            projected = prior_spend + amount
            if projected > maximum:
                add(
                    "Rolling spending limit",
                    "fail",
                    "rolling_spending_limit_exceeded",
                    f"CHF {projected:.2f} would exceed the CHF {maximum:.2f} rolling limit.",
                )
            else:
                add(
                    "Rolling spending limit",
                    "pass",
                    "rolling_spending_within_limit",
                    f"CHF {projected:.2f} stays within the CHF {maximum:.2f} rolling limit.",
                )

    if "duplicatePurchase" in rules:
        duplicate = rules["duplicatePurchase"]
        try:
            current_signature = _item_signature(items)
            duplicate_found = False
            for prior_event in prior_approved_events:
                prior_authorization = prior_event["authorization"]
                prior_time = _event_time(prior_event)
                delta = current_time - prior_time
                if not timedelta(0) <= delta <= timedelta(minutes=duplicate["windowMinutes"]):
                    continue
                if duplicate["matchMerchant"]:
                    prior_merchant = prior_authorization.get("merchant", {})
                    if not isinstance(prior_merchant, Mapping) or prior_merchant.get("merchant_id") != merchant_id:
                        continue
                if duplicate["matchItems"] and _item_signature(prior_authorization.get("items", [])) != current_signature:
                    continue
                duplicate_found = True
                break
        except (KeyError, TypeError, ValueError):
            add(
                "Duplicate purchase",
                "review",
                "duplicate_check_unverifiable",
                "The server-owned purchase state needed for duplicate detection is unavailable.",
            )
        else:
            if duplicate_found:
                add(
                    "Duplicate purchase",
                    "review",
                    "possible_duplicate_confirmation_required",
                    "A matching approved purchase was found within the duplicate-protection window.",
                )
            else:
                add(
                    "Duplicate purchase",
                    "pass",
                    "no_recent_duplicate",
                    "No matching approved purchase was found in the duplicate-protection window.",
                )

    if wallet_policy is not None:
        checks.extend(evaluate_wallet_policy(event, history, wallet_policy))

    outcomes = {check["outcome"] for check in checks}
    decision = "decline" if "fail" in outcomes else "step_up" if "review" in outcomes else "approve"
    return {
        "authorization_id": authorization_id,
        "recommended_decision": decision,
        "reason_codes": [check["reason_code"] for check in checks if check["outcome"] != "pass"],
        "checks": checks,
        "engine_version": ENGINE_VERSION,
    }
