from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


class BenchmarkPolicyValidationError(ValueError):
    pass


RULE_FIELDS = frozenset({
    "maxPurchaseChf",
    "rollingPeriod",
    "allowedItemCategories",
    "allowedItemIds",
    "exactItemCount",
    "allowedMerchantCategories",
    "requiredFulfillmentMethods",
    "requiredItemText",
    "minimumReturnDays",
    "requireFamiliarMerchant",
    "requireKnownDevice",
    "requireKnownMerchantCountry",
    "maxRecentAttempts",
    "duplicatePurchase",
})


def _money(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise BenchmarkPolicyValidationError(f"{field} must be a number")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BenchmarkPolicyValidationError(f"{field} must be a number") from exc
    if not amount.is_finite() or amount < 0:
        raise BenchmarkPolicyValidationError(f"{field} must be a non-negative finite number")
    return float(amount)


def _strings(value: Any, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise BenchmarkPolicyValidationError(f"{field} must be a unique non-empty string list")
    return list(value)


def _positive_integer(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise BenchmarkPolicyValidationError(f"{field} must be a positive integer")
    return value


def _validate_rules(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise BenchmarkPolicyValidationError("rules must be a non-empty object")
    unknown = set(value) - RULE_FIELDS
    if unknown:
        raise BenchmarkPolicyValidationError("rules contains unsupported fields")
    validated: dict[str, Any] = {}
    if "maxPurchaseChf" in value:
        validated["maxPurchaseChf"] = _money(value["maxPurchaseChf"], "maxPurchaseChf")
    if "rollingPeriod" in value:
        rolling = value["rollingPeriod"]
        if not isinstance(rolling, Mapping) or set(rolling) != {"days", "maximumChf"}:
            raise BenchmarkPolicyValidationError("rollingPeriod is invalid")
        validated["rollingPeriod"] = {
            "days": _positive_integer(rolling["days"], "rollingPeriod.days"),
            "maximumChf": _money(rolling["maximumChf"], "rollingPeriod.maximumChf"),
        }
    for field in (
        "allowedItemCategories",
        "allowedItemIds",
        "allowedMerchantCategories",
        "requiredFulfillmentMethods",
        "requiredItemText",
    ):
        if field in value:
            validated[field] = _strings(value[field], field)
    for field in ("exactItemCount", "minimumReturnDays", "maxRecentAttempts"):
        if field in value:
            validated[field] = _positive_integer(value[field], field)
    for field in (
        "requireFamiliarMerchant",
        "requireKnownDevice",
        "requireKnownMerchantCountry",
    ):
        if field in value:
            if not isinstance(value[field], bool):
                raise BenchmarkPolicyValidationError(f"{field} must be a boolean")
            validated[field] = value[field]
    if "duplicatePurchase" in value:
        duplicate = value["duplicatePurchase"]
        if not isinstance(duplicate, Mapping) or set(duplicate) != {
            "windowMinutes", "matchMerchant", "matchItems"
        }:
            raise BenchmarkPolicyValidationError("duplicatePurchase is invalid")
        if not isinstance(duplicate["matchMerchant"], bool) or not isinstance(duplicate["matchItems"], bool):
            raise BenchmarkPolicyValidationError("duplicatePurchase match fields must be boolean")
        validated["duplicatePurchase"] = {
            "windowMinutes": _positive_integer(duplicate["windowMinutes"], "duplicatePurchase.windowMinutes"),
            "matchMerchant": duplicate["matchMerchant"],
            "matchItems": duplicate["matchItems"],
        }
    return validated


def validate_scenario_policy_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise BenchmarkPolicyValidationError("scenario policy document must be an object")
    required = {
        "policyId",
        "schemaVersion",
        "revision",
        "scenarioId",
        "subject",
        "mandate",
        "rules",
        "effectiveFrom",
        "updatedAt",
        "updatedBy",
    }
    if set(document) != required:
        raise BenchmarkPolicyValidationError("scenario policy document fields are invalid")
    for field in ("policyId", "schemaVersion", "scenarioId", "effectiveFrom", "updatedAt", "updatedBy"):
        if not isinstance(document[field], str) or not document[field]:
            raise BenchmarkPolicyValidationError(f"{field} is invalid")
    if len(document["policyId"]) > 128:
        raise BenchmarkPolicyValidationError("policyId is invalid")
    revision = document["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise BenchmarkPolicyValidationError("revision is invalid")
    subject = document["subject"]
    if (
        not isinstance(subject, Mapping)
        or set(subject) != {"customerId", "cardId"}
        or any(not isinstance(subject[field], str) or not subject[field] for field in subject)
    ):
        raise BenchmarkPolicyValidationError("policy subject is invalid")
    mandate = document["mandate"]
    mandate_fields = {"mandateId", "profileId", "instruction", "hardRules", "uncertaintyPolicy"}
    if not isinstance(mandate, Mapping) or set(mandate) != mandate_fields:
        raise BenchmarkPolicyValidationError("mandate is invalid")
    if any(not isinstance(mandate[field], str) or not mandate[field] for field in (
        "mandateId", "profileId", "instruction", "uncertaintyPolicy"
    )):
        raise BenchmarkPolicyValidationError("mandate text is invalid")
    if mandate["uncertaintyPolicy"] not in {"ask", "approve", "decline"}:
        raise BenchmarkPolicyValidationError("mandate uncertaintyPolicy is invalid")
    if not isinstance(mandate["hardRules"], list):
        raise BenchmarkPolicyValidationError("mandate hardRules is invalid")
    return {
        "policyId": document["policyId"],
        "schemaVersion": document["schemaVersion"],
        "revision": revision,
        "scenarioId": document["scenarioId"],
        "subject": {"customerId": subject["customerId"], "cardId": subject["cardId"]},
        "mandate": {
            "mandateId": mandate["mandateId"],
            "profileId": mandate["profileId"],
            "instruction": mandate["instruction"],
            "hardRules": deepcopy(mandate["hardRules"]),
            "uncertaintyPolicy": mandate["uncertaintyPolicy"],
        },
        "rules": _validate_rules(document["rules"]),
        "effectiveFrom": document["effectiveFrom"],
        "updatedAt": document["updatedAt"],
        "updatedBy": document["updatedBy"],
    }


def validate_event_binding(document: Mapping[str, Any], event: Mapping[str, Any]) -> None:
    try:
        authorization = event["authorization"]
        mandate = event["mandate"]
        expected = document["mandate"]
        if not isinstance(authorization, Mapping) or not isinstance(mandate, Mapping):
            raise BenchmarkPolicyValidationError("event binding is invalid")
        if authorization["scenario_id"] != document["scenarioId"]:
            raise BenchmarkPolicyValidationError("event scenario does not match policy")
        if authorization["card_id"] != document["subject"]["cardId"]:
            raise BenchmarkPolicyValidationError("event card does not match policy")
        if mandate["mandate_id"] != expected["mandateId"]:
            raise BenchmarkPolicyValidationError("event mandate does not match policy")
        if mandate["card_id"] != document["subject"]["cardId"]:
            raise BenchmarkPolicyValidationError("event mandate card does not match policy")
        if mandate["customer_id"] != document["subject"]["customerId"]:
            raise BenchmarkPolicyValidationError("event mandate customer does not match policy")
        if mandate["profile_id"] != expected["profileId"]:
            raise BenchmarkPolicyValidationError("event profile does not match policy")
    except (KeyError, TypeError) as exc:
        raise BenchmarkPolicyValidationError("event binding is invalid") from exc


def _document(
    scenario_id: str,
    customer_id: str,
    card_id: str,
    instruction: str,
    rules: Mapping[str, Any],
    mandate_id: str | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    mandate_id = mandate_id or f"TM_BENCHMARK_{scenario_id}"
    profile_id = profile_id or f"PROFILE_BENCHMARK_{scenario_id}"
    max_purchase = rules.get("maxPurchaseChf")
    hard_rules = []
    if max_purchase is not None:
        hard_rules.append({
            "field": "authorization.billing_amount_chf",
            "operator": "<=",
            "value": max_purchase,
            "currency": "CHF",
            "scope": "purchase",
        })
    return {
        "policyId": f"benchmark-policy_{scenario_id}",
        "schemaVersion": "2026-09-19",
        "revision": 1,
        "scenarioId": scenario_id,
        "subject": {"customerId": customer_id, "cardId": card_id},
        "mandate": {
            "mandateId": mandate_id,
            "profileId": profile_id,
            "instruction": instruction,
            "hardRules": hard_rules,
            "uncertaintyPolicy": "ask",
        },
        "rules": dict(rules),
        "effectiveFrom": "2026-08-08T00:00:00.000Z",
        "updatedAt": "2026-09-19T00:00:00.000Z",
        "updatedBy": "system",
    }


def benchmark_policy_documents() -> list[dict[str, Any]]:
    documents = [
        _document(
            "SCEN0000",
            "CU0001",
            "CA0001",
            "Buy one ordinary grocery item for CHF 20 or less from a shop I use regularly. Ask me when uncertain.",
            {
                "maxPurchaseChf": 20,
                "allowedItemCategories": ["groceries"],
                "exactItemCount": 1,
                "requireFamiliarMerchant": True,
            },
            mandate_id="TM_MOCK_0001",
            profile_id="PROFILE_MOCK_0001",
        ),
        _document(
            "SCEN0001",
            "CU0001",
            "CA0001",
            "Order our household groceries for delivery. Keep each order at or below CHF 120 including delivery, and keep the total across any seven days at or below CHF 300. Ask me when uncertain.",
            {
                "maxPurchaseChf": 120,
                "rollingPeriod": {"days": 7, "maximumChf": 300},
                "allowedItemCategories": ["groceries"],
                "requiredFulfillmentMethods": ["delivery"],
            },
        ),
        _document(
            "SCEN0002",
            "CU0006",
            "CA0011",
            "Replace my worn road-running shoes in size 43. Buy only from a specialist sports retailer, only if the order can be returned within 14 days or more, and pay no more than CHF 200. Ask me when uncertain.",
            {
                "maxPurchaseChf": 200,
                "allowedMerchantCategories": ["sporting_goods"],
                "allowedItemIds": ["IT0014"],
                "exactItemCount": 1,
                "requiredItemText": ["size 43"],
                "minimumReturnDays": 14,
            },
        ),
        _document(
            "SCEN0003",
            "CU0012",
            "CA0023",
            "The agent may buy clothing for me, up to CHF 250 per order, from shops I have used before. Pause anything that looks like someone other than me is driving the session. Ask me when uncertain.",
            {
                "maxPurchaseChf": 250,
                "allowedItemCategories": ["clothing"],
                "requireFamiliarMerchant": True,
                "requireKnownDevice": True,
                "requireKnownMerchantCountry": True,
                "maxRecentAttempts": 3,
            },
        ),
        _document(
            "SCEN0004",
            "CU0019",
            "CA0039",
            "Buy the 27-inch monitor I chose, from a seller I have bought from before, for CHF 400 or less. Do not add anything I did not ask for. Ask me when uncertain.",
            {
                "maxPurchaseChf": 400,
                "allowedItemIds": ["IT0017"],
                "exactItemCount": 1,
                "requireFamiliarMerchant": True,
                "duplicatePurchase": {
                    "windowMinutes": 1440,
                    "matchMerchant": True,
                    "matchItems": True,
                },
            },
        ),
    ]
    return [validate_scenario_policy_document(document) for document in documents]
