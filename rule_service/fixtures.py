"""Local fixture builder for exercising the rule engine without a live event source.

This mirrors the SCEN0000 / AU0001 shape that ``mock_api``'s viseca_mock builds
for its own demo; it is duplicated here (rather than imported across the
service boundary) so this service's tests and benchmark stay independent of
the mock-agent service.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[1] / "viseca-2026" / "data"
MOCK_AUTHORIZATION_ID = "MOCK_AU0001"


def _csv_row(path: Path, key: str, value: str) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as stream:
        return next(row for row in csv.DictReader(stream) if row[key] == value)


def build_connection_event(data_dir: Path = DATA_DIR, now: datetime | None = None) -> dict[str, Any]:
    """Build the SCEN0000 / AU0001 purchase as a live-event-shaped JSON object."""

    now = now or datetime.now(timezone.utc)
    fixture = json.loads((data_dir / "scenario_fixtures" / "connection_check.json").read_text())
    source = fixture["authorization"]
    merchant = _csv_row(data_dir / "merchants.csv", "merchant_id", source["merchant_id"])
    scenario = _csv_row(data_dir / "scenario_catalogue.csv", "scenario_id", "SCEN0000")
    authority = _csv_row(data_dir / "scenario_authorities.csv", "authority_id", source["authority_id"])
    items = []
    for item in fixture["items"]:
        items.append({**item, "line_no": int(item["line_no"]),
                      "quantity": int(item["quantity"]), "unit_price": float(item["unit_price"])})
    authorization = {
        "authorization_id": MOCK_AUTHORIZATION_ID,
        "source_authorization_id": source["authorization_id"],
        "scenario_id": "SCEN0000",
        "replay_order": int(source["replay_order"]),
        "mandate_id": "TM_MOCK_0001",
        "profile_id": "PROFILE_MOCK_0001",
        "card_id": source["card_id"],
        "initiator_type": "agent",
        "merchant": merchant,
        "timestamp": source["timestamp"],
        "amount": float(source["amount"]),
        "currency": source["currency"],
        "billing_amount_chf": float(source["billing_amount_chf"]),
        "items_subtotal": float(source["items_subtotal"]),
        "delivery_fee": float(source["delivery_fee"]),
        "channel": source["channel"],
        "customer_device_id": source["customer_device_id"],
        "authority_status": source["authority_status"],
        "card_status_at_attempt": source["card_status_at_attempt"],
        "spend_in_period_before_chf": None,
        "recent_attempt_count_10m": 0,
        "fulfillment_method": source["fulfillment_method"],
        "delivery_by": source["delivery_by"],
        "order_returnable": source["order_returnable"],
        "order_cancellable": source["order_cancellable"],
        "related_authorization_id": None,
        "related_authorization_status": None,
        "purchase_description": source["purchase_description"],
        "items": items,
    }
    return {
        "type": "authorization.request",
        "request_id": "req_mock_0001",
        "deadline_at": (now + timedelta(seconds=8)).isoformat().replace("+00:00", "Z"),
        "authorization": authorization,
        "mandate": {
            "mandate_id": "TM_MOCK_0001",
            "status": "active",
            "customer_id": authority["customer_id"],
            "card_id": authority["card_id"],
            "instruction": scenario["cardholder_instruction"],
            "hard_rules": [{"field": "authorization.billing_amount_chf", "operator": "<=",
                            "value": 20, "currency": "CHF", "scope": "purchase"}],
            "uncertainty_policy": "ask",
            "profile_id": "PROFILE_MOCK_0001",
        },
        "context": {"approved_spend_in_period_chf": 0.0, "recent_authorizations": []},
        "runtime": {"received_at": now.isoformat().replace("+00:00", "Z"),
                    "history_window_minutes": 10,
                    "context_basis": "run_decisions_and_scenario_timestamps"},
    }
