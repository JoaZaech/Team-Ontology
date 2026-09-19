"""Canonical loader and event builder for the bundled Viseca benchmark data."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping


DATA_DIR = Path(__file__).resolve().parents[1] / "viseca-2026" / "data"


class BenchmarkDataError(ValueError):
    pass


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _number(value: str) -> float:
    try:
        return float(Decimal(value))
    except Exception as exc:
        raise BenchmarkDataError(f"invalid numeric value {value!r}") from exc


def _integer(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkDataError(f"invalid integer value {value!r}") from exc


def _optional(value: str | None) -> str | None:
    return value or None


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BenchmarkDataError(f"invalid timestamp {value!r}") from exc


def _iso_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _policy_value(value: Mapping[str, Any], snake_case: str, camel_case: str) -> Any:
    if snake_case in value:
        return value[snake_case]
    if camel_case in value:
        return value[camel_case]
    raise BenchmarkDataError(f"policy binding is missing {camel_case}")


@dataclass(frozen=True)
class BenchmarkPolicyBinding:
    policy_id: str
    scenario_id: str
    mandate_id: str
    profile_id: str
    customer_id: str
    card_id: str
    instruction: str
    hard_rules: tuple[dict[str, Any], ...]
    uncertainty_policy: str

    @classmethod
    def from_policy_snapshot(cls, policy: Mapping[str, Any]) -> "BenchmarkPolicyBinding":
        subject = policy.get("subject")
        mandate = policy.get("mandate")
        if not isinstance(subject, Mapping) or not isinstance(mandate, Mapping):
            raise BenchmarkDataError("policy snapshot is missing subject or mandate")
        try:
            hard_rules = _policy_value(mandate, "hard_rules", "hardRules")
            if not isinstance(hard_rules, list) or not all(isinstance(rule, Mapping) for rule in hard_rules):
                raise BenchmarkDataError("policy mandate hard rules are invalid")
            return cls(
                policy_id=str(_policy_value(policy, "policy_id", "policyId")),
                scenario_id=str(_policy_value(policy, "scenario_id", "scenarioId")),
                mandate_id=str(_policy_value(mandate, "mandate_id", "mandateId")),
                profile_id=str(_policy_value(mandate, "profile_id", "profileId")),
                customer_id=str(_policy_value(subject, "customer_id", "customerId")),
                card_id=str(_policy_value(subject, "card_id", "cardId")),
                instruction=str(mandate["instruction"]),
                hard_rules=tuple(dict(rule) for rule in hard_rules),
                uncertainty_policy=str(_policy_value(mandate, "uncertainty_policy", "uncertaintyPolicy")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, BenchmarkDataError):
                raise
            raise BenchmarkDataError("policy snapshot has an invalid binding") from exc

    def mandate(self) -> dict[str, Any]:
        return {
            "mandate_id": self.mandate_id,
            "status": "active",
            "customer_id": self.customer_id,
            "card_id": self.card_id,
            "instruction": self.instruction,
            "hard_rules": [dict(rule) for rule in self.hard_rules],
            "uncertainty_policy": self.uncertainty_policy,
            "profile_id": self.profile_id,
        }


class VisecaBenchmark:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        scenario_rows = _read_rows(self.data_dir / "scenario_catalogue.csv")
        authority_rows = _read_rows(self.data_dir / "scenario_authorities.csv")
        attempt_rows = _read_rows(self.data_dir / "purchase_attempts.csv")
        item_rows = _read_rows(self.data_dir / "purchase_attempt_items.csv")
        merchant_rows = _read_rows(self.data_dir / "merchants.csv")
        catalogue_item_rows = _read_rows(self.data_dir / "items.csv")
        flattened_rows = _read_rows(self.data_dir / "mock_rule_testing.csv")
        self.scenarios = {row["scenario_id"]: row for row in scenario_rows}
        self.authorities = {row["authority_id"]: row for row in authority_rows}
        self.merchants = {row["merchant_id"]: row for row in merchant_rows}
        self.catalogue_items = {row["item_id"]: row for row in catalogue_item_rows}
        self.attempts_by_source_id = {row["authorization_id"]: row for row in attempt_rows}
        self.flattened_rows_by_source_id = {
            row["authorization_id"]: row for row in flattened_rows
        }
        self.attempts_by_scenario: dict[str, tuple[dict[str, str], ...]] = {}
        grouped_attempts: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in attempt_rows:
            grouped_attempts[row["scenario_id"]].append(row)
        for scenario_id, rows in grouped_attempts.items():
            self.attempts_by_scenario[scenario_id] = tuple(sorted(rows, key=lambda row: _integer(row["replay_order"])))
        grouped_items: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in item_rows:
            grouped_items[row["authorization_id"]].append(row)
        self.items_by_source_id = {
            source_id: tuple(sorted(rows, key=lambda row: _integer(row["line_no"])))
            for source_id, rows in grouped_items.items()
        }
        self._validate()

    def _validate(self) -> None:
        if not self.scenarios:
            raise BenchmarkDataError("scenario catalogue is empty")
        if len(self.attempts_by_source_id) != sum(len(rows) for rows in self.attempts_by_scenario.values()):
            raise BenchmarkDataError("duplicate purchase authorization IDs")
        if len(self.flattened_rows_by_source_id) != len(self.attempts_by_source_id):
            raise BenchmarkDataError("flattened benchmark rows do not match purchase attempts")
        if set(self.attempts_by_scenario) != set(self.scenarios):
            raise BenchmarkDataError("scenario catalogue and attempts do not agree")
        for scenario_id, scenario in self.scenarios.items():
            attempts = self.attempts_by_scenario.get(scenario_id, ())
            if len(attempts) != _integer(scenario["event_count"]):
                raise BenchmarkDataError(f"scenario {scenario_id} event count does not match")
            if [_integer(row["replay_order"]) for row in attempts] != list(range(1, len(attempts) + 1)):
                raise BenchmarkDataError(f"scenario {scenario_id} replay order is not contiguous")
            previous_time: datetime | None = None
            authority_ids: set[str] = set()
            card_ids: set[str] = set()
            for row in attempts:
                authority = self.authorities.get(row["authority_id"])
                merchant = self.merchants.get(row["merchant_id"])
                items = self.items_by_source_id.get(row["authorization_id"], ())
                if authority is None or merchant is None or not items:
                    raise BenchmarkDataError(f"scenario {scenario_id} has a broken benchmark join")
                if authority["card_id"] != row["card_id"]:
                    raise BenchmarkDataError(f"scenario {scenario_id} authority/card binding does not match")
                parsed_time = _parse_time(row["timestamp"])
                if previous_time is not None and parsed_time < previous_time:
                    raise BenchmarkDataError(f"scenario {scenario_id} timestamps are not ordered")
                previous_time = parsed_time
                authority_ids.add(row["authority_id"])
                card_ids.add(row["card_id"])
            if len(authority_ids) != 1 or len(card_ids) != 1:
                raise BenchmarkDataError(f"scenario {scenario_id} does not have one authority/card binding")
        self._validate_flattened_benchmark()

    def _validate_flattened_benchmark(self) -> None:
        source_columns = (
            "scenario_id",
            "replay_order",
            "authorization_id",
            "authority_id",
            "card_id",
            "merchant_id",
            "timestamp",
            "amount",
            "currency",
            "billing_amount_chf",
            "items_subtotal",
            "delivery_fee",
            "channel",
            "customer_device_id",
            "authority_status",
            "card_status_at_attempt",
            "recent_attempt_count_10m",
            "fulfillment_method",
            "delivery_by",
            "order_returnable",
            "order_cancellable",
            "related_authorization_id",
            "related_authorization_status",
            "purchase_description",
        )
        merchant_columns = (
            "merchant_name",
            "merchant_category",
            "merchant_mcc",
            "merchant_country",
            "merchant_city",
            "merchant_availability",
            "merchant_recurring_capable",
        )
        for source_id, attempt in self.attempts_by_source_id.items():
            flattened = self.flattened_rows_by_source_id.get(source_id)
            if flattened is None:
                raise BenchmarkDataError("a purchase attempt is missing from mock_rule_testing.csv")
            for column in source_columns:
                if flattened[column] != attempt[column]:
                    raise BenchmarkDataError(f"flattened benchmark mismatch for {source_id} field {column}")
            authority = self.authorities[attempt["authority_id"]]
            if flattened["customer_id"] != authority["customer_id"]:
                raise BenchmarkDataError(f"flattened benchmark customer mismatch for {source_id}")
            merchant = self.merchants[attempt["merchant_id"]]
            expected_merchant = {
                "merchant_name": merchant["merchant_name"],
                "merchant_category": merchant["merchant_category"],
                "merchant_mcc": merchant["merchant_mcc"],
                "merchant_country": merchant["merchant_country"],
                "merchant_city": merchant["merchant_city"],
                "merchant_availability": merchant["availability"],
                "merchant_recurring_capable": merchant["recurring_capable"],
            }
            for column in merchant_columns:
                if flattened[column] != expected_merchant[column]:
                    raise BenchmarkDataError(f"flattened benchmark merchant mismatch for {source_id} field {column}")
            items = self.items_by_source_id[source_id]
            if _integer(flattened["cart_line_count"]) != len(items):
                raise BenchmarkDataError(f"flattened benchmark line count mismatch for {source_id}")
            if _integer(flattened["cart_total_quantity"]) != sum(_integer(item["quantity"]) for item in items):
                raise BenchmarkDataError(f"flattened benchmark quantity mismatch for {source_id}")
            for index, item in enumerate(items, start=1):
                catalogue = self.catalogue_items.get(item["item_id"])
                if catalogue is None:
                    raise BenchmarkDataError(f"purchase item catalogue join is missing for {source_id}")
                expected_item = {
                    "line_no": item["line_no"],
                    "id": item["item_id"],
                    "name": item["item_name"],
                    "category": item["item_category"],
                    "quantity": item["quantity"],
                    "unit_price": item["unit_price"],
                    "currency": item["currency"],
                    "details": item["item_details"],
                    "catalogue_description": catalogue["item_description"],
                    "catalogue_price_min_chf": catalogue["unit_price_min_chf"],
                    "catalogue_price_typical_chf": catalogue["unit_price_typical_chf"],
                    "catalogue_price_max_chf": catalogue["unit_price_max_chf"],
                }
                for suffix, expected in expected_item.items():
                    if flattened[f"item_{index}_{suffix}"] != expected:
                        raise BenchmarkDataError(
                            f"flattened benchmark item mismatch for {source_id} field item_{index}_{suffix}"
                        )
            for index in range(len(items) + 1, 3):
                if any(flattened[f"item_{index}_{suffix}"] for suffix in (
                    "line_no", "id", "name", "category", "quantity", "unit_price", "currency", "details",
                    "catalogue_description", "catalogue_price_min_chf", "catalogue_price_typical_chf",
                    "catalogue_price_max_chf",
                )):
                    raise BenchmarkDataError(f"unexpected flattened benchmark item for {source_id}")

    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.scenarios))

    def scenario(self, scenario_id: str) -> dict[str, str]:
        try:
            return dict(self.scenarios[scenario_id])
        except KeyError as exc:
            raise BenchmarkDataError("unknown scenario") from exc

    def attempts(self, scenario_id: str) -> tuple[dict[str, str], ...]:
        try:
            return tuple(dict(row) for row in self.attempts_by_scenario[scenario_id])
        except KeyError as exc:
            raise BenchmarkDataError("unknown scenario") from exc

    def source_attempt(self, source_authorization_id: str) -> dict[str, str]:
        try:
            return dict(self.attempts_by_source_id[source_authorization_id])
        except KeyError as exc:
            raise BenchmarkDataError("unknown source authorization") from exc

    def binding_for_scenario(self, scenario_id: str, policy: Mapping[str, Any]) -> BenchmarkPolicyBinding:
        binding = BenchmarkPolicyBinding.from_policy_snapshot(policy)
        attempts = self.attempts(scenario_id)
        authority = self.authorities[attempts[0]["authority_id"]]
        if binding.scenario_id != scenario_id:
            raise BenchmarkDataError("policy scenario does not match benchmark scenario")
        if binding.customer_id != authority["customer_id"] or binding.card_id != attempts[0]["card_id"]:
            raise BenchmarkDataError("policy subject does not match benchmark authority")
        return binding

    def build_event(
        self,
        source_authorization_id: str,
        policy: BenchmarkPolicyBinding,
        *,
        authorization_id: str | None = None,
        request_id: str | None = None,
        received_at: datetime | None = None,
        deadline_seconds: int = 8,
        approved_spend_in_period_chf: Decimal | float | int = Decimal("0"),
        recent_authorizations: Iterable[Mapping[str, Any]] = (),
        recent_attempt_count_10m: int | None = None,
        live_authorization_ids: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        row = self.source_attempt(source_authorization_id)
        if row["scenario_id"] != policy.scenario_id or row["card_id"] != policy.card_id:
            raise BenchmarkDataError("policy does not bind this source authorization")
        merchant = self.merchants[row["merchant_id"]]
        items = self.items_by_source_id[source_authorization_id]
        timestamp = _parse_time(row["timestamp"])
        current_received_at = received_at or datetime.now(timezone.utc)
        live_id = authorization_id or f"MOCK_{source_authorization_id}"
        related_source_id = _optional(row["related_authorization_id"])
        related_live_id = (
            live_authorization_ids.get(related_source_id, related_source_id)
            if related_source_id is not None and live_authorization_ids is not None
            else related_source_id
        )
        filtered_recent = [dict(value) for value in recent_authorizations]
        if recent_attempt_count_10m is None:
            recent_attempt_count_10m = sum(
                1
                for value in filtered_recent
                if isinstance(value.get("timestamp"), str)
                and timestamp - timedelta(minutes=10) <= _parse_time(value["timestamp"]) < timestamp
            )
        return {
            "type": "authorization.request",
            "request_id": request_id or f"req_{source_authorization_id.lower()}",
            "deadline_at": _iso_time(current_received_at + timedelta(seconds=deadline_seconds)),
            "authorization": {
                "authorization_id": live_id,
                "source_authorization_id": source_authorization_id,
                "scenario_id": row["scenario_id"],
                "replay_order": _integer(row["replay_order"]),
                "mandate_id": policy.mandate_id,
                "profile_id": policy.profile_id,
                "card_id": row["card_id"],
                "initiator_type": "agent",
                "merchant": dict(merchant),
                "timestamp": _iso_time(timestamp),
                "amount": _number(row["amount"]),
                "currency": row["currency"],
                "billing_amount_chf": _number(row["billing_amount_chf"]),
                "items_subtotal": _number(row["items_subtotal"]),
                "delivery_fee": _number(row["delivery_fee"]),
                "channel": row["channel"],
                "customer_device_id": row["customer_device_id"],
                "authority_status": row["authority_status"],
                "card_status_at_attempt": row["card_status_at_attempt"],
                "spend_in_period_before_chf": None,
                "recent_attempt_count_10m": recent_attempt_count_10m,
                "fulfillment_method": row["fulfillment_method"],
                "delivery_by": _optional(row["delivery_by"]),
                "order_returnable": row["order_returnable"],
                "order_cancellable": row["order_cancellable"],
                "related_authorization_id": related_live_id,
                "related_authorization_status": _optional(row["related_authorization_status"]),
                "purchase_description": row["purchase_description"],
                "items": [
                    {
                        "line_no": _integer(item["line_no"]),
                        "item_id": item["item_id"],
                        "item_name": item["item_name"],
                        "item_category": item["item_category"],
                        "quantity": _integer(item["quantity"]),
                        "unit_price": _number(item["unit_price"]),
                        "currency": item["currency"],
                        "item_details": item["item_details"],
                    }
                    for item in items
                ],
            },
            "mandate": policy.mandate(),
            "context": {
                "approved_spend_in_period_chf": float(Decimal(str(approved_spend_in_period_chf))),
                "recent_authorizations": filtered_recent,
            },
            "runtime": {
                "received_at": _iso_time(current_received_at),
                "history_window_minutes": 10,
                "context_basis": "run_decisions_and_scenario_timestamps",
            },
        }
