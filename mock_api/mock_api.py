"""Local-only mock AI-agent entry point. Delegates every decision to rule_service."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from collections import defaultdict
import csv
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from decision_receipts import DecisionReceiptLedger, canonical_json
from observability import Telemetry
from rule_client import PolicyConflictError, PolicyValidationError, RuleServiceClient


DATA_DIR = Path(__file__).resolve().parents[1] / "viseca-2026" / "data"


class RequestError(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code


def _money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("amount must be numeric") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("amount must be finite and non-negative")
    return amount


def _fixed_mandate_policy_hash(policy: Mapping[str, Any], dynamic_policy: dict[str, Any] | None = None) -> str:
    value = {
        "max_purchase_chf": str(policy["max_purchase_chf"]) if policy.get("max_purchase_chf") is not None else None,
        "require_familiar_merchant": policy.get("require_familiar_merchant", False),
    }
    value["dynamic_wallet_policy"] = dynamic_policy
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _iso_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _load_merchant_catalogue(data_dir: Path) -> dict[str, dict[str, str]]:
    with (data_dir / "merchants.csv").open(newline="", encoding="utf-8") as stream:
        return {row["merchant_id"]: row for row in csv.DictReader(stream)}


class MockAgentService:
    """Mock policy and session state; no payment or authoritative ledger."""

    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        receipt_ledger: DecisionReceiptLedger | None = None,
        telemetry: Telemetry | None = None,
        rule_client: RuleServiceClient | None = None,
    ):
        self.merchants = _load_merchant_catalogue(data_dir)
        with (data_dir / "items.csv").open(newline="", encoding="utf-8") as stream:
            self.items = {row["item_id"]: row for row in csv.DictReader(stream)}
        self.policies = {
            "TM_DEMO_GROCERY": ("CA0001", {
                "max_purchase_chf": Decimal("20.00"), "require_familiar_merchant": True,
            })
        }
        self.seen: dict[str, tuple[str, dict[str, Any]]] = {}
        self.attempts: dict[tuple[str, str], list[float]] = defaultdict(list)
        self.receipt_ledger = receipt_ledger or DecisionReceiptLedger(":memory:")
        self.telemetry = telemetry or Telemetry()
        self.rule_client = rule_client or RuleServiceClient()

    def close(self) -> None:
        self.receipt_ledger.close()

    def wallet_policy(self) -> dict[str, Any]:
        """Return the customer-controlled snapshot used for new requests."""

        return self.rule_client.get_policy()

    def update_wallet_policy(self, request: Any) -> dict[str, Any]:
        """Persist a versioned policy update before it can affect a decision."""

        return self.rule_client.update_policy(request)

    def _rulebook_event(
        self,
        *,
        request_id: str,
        buyer: dict[str, str],
        merchant: dict[str, str],
        order: dict[str, Any],
        total: Decimal,
        delivery: Decimal,
        recent_attempts: int,
        timestamp: float,
        policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Normalize an agent proposal into the trusted evaluator's event shape.

        The agent supplies IDs, quantities, and quoted prices.  Product and
        merchant facts are resolved from the Viseca data pack here, before the
        rule service sees the proposal.  Unknown item IDs are deliberately
        retained as unknown facts so the policy engine can stop the
        grocery-only mandate.
        """

        items: list[dict[str, Any]] = []
        for index, proposed in enumerate(order["items"], start=1):
            catalogue = self.items.get(proposed["item_id"])
            items.append({
                "line_no": index,
                "item_id": proposed["item_id"],
                "item_name": catalogue["item_name"] if catalogue else "Unrecognised item",
                "item_category": catalogue["item_category"] if catalogue else "unknown",
                "item_details": "Resolved from the trusted item catalogue." if catalogue else "",
                "quantity": proposed["quantity"],
                "unit_price": float(_money(proposed["unit_price_chf"])),
                "currency": "CHF",
            })
        event_time = _iso_time(timestamp)
        subtotal = total - delivery
        limit = policy.get("max_purchase_chf")
        hard_rules: list[dict[str, Any]] = []
        if limit is not None:
            hard_rules.append({
                "field": "authorization.billing_amount_chf",
                "operator": "<=",
                "value": float(limit),
                "currency": "CHF",
                "scope": "purchase",
            })
        return {
            "type": "authorization.request",
            "request_id": request_id,
            "deadline_at": event_time,
            "authorization": {
                "authorization_id": request_id,
                "source_authorization_id": request_id,
                "scenario_id": "LOCAL_AGENT",
                "replay_order": 1,
                "mandate_id": buyer["mandate_id"],
                "profile_id": "PROFILE_LOCAL_AGENT",
                "card_id": buyer["card_id"],
                "initiator_type": "agent",
                "merchant": merchant,
                "timestamp": event_time,
                "amount": float(total),
                "currency": "CHF",
                "billing_amount_chf": float(total),
                "items_subtotal": float(subtotal),
                "delivery_fee": float(delivery),
                "channel": "ecommerce",
                "customer_device_id": "DVC-LOCAL-AGENT",
                "authority_status": "active",
                "card_status_at_attempt": "active",
                "spend_in_period_before_chf": None,
                "recent_attempt_count_10m": recent_attempts,
                "fulfillment_method": "delivery",
                "delivery_by": None,
                "order_returnable": "unknown",
                "order_cancellable": "unknown",
                "related_authorization_id": None,
                "related_authorization_status": None,
                "purchase_description": "Agent-proposed purchase",
                "items": items,
            },
            "mandate": {
                "mandate_id": buyer["mandate_id"],
                "status": "active",
                "customer_id": "CU0001",
                "card_id": buyer["card_id"],
                "instruction": "Buy one ordinary grocery item for CHF 20 or less from a shop I use regularly.",
                "hard_rules": hard_rules,
                "uncertainty_policy": "ask",
                "profile_id": "PROFILE_LOCAL_AGENT",
            },
            "context": {"approved_spend_in_period_chf": 0.0, "recent_authorizations": []},
            "runtime": {
                "received_at": event_time,
                "history_window_minutes": 10,
                "context_basis": "mock_agent_in_memory_attempts",
            },
        }

    def evaluate(self, body: Any, now: float | None = None) -> dict[str, Any]:
        correlation_id = body.get("request_id", "invalid-request") if isinstance(body, dict) else "invalid-request"
        with self.telemetry.trace(correlation_id=str(correlation_id)) as trace:
            self.telemetry.event(
                "decision.request_received",
                trace=trace,
                labels={"component": "mock_api"},
            )
            try:
                with self.telemetry.span("decision.validate", trace=trace, labels={"component": "mock_api"}):
                    if not isinstance(body, dict) or set(body) != {"request_id", "buyer", "merchant_id", "order"}:
                        raise RequestError(400, "invalid_request_fields")
                    request_id = body["request_id"]
                    buyer, merchant_id, order = body["buyer"], body["merchant_id"], body["order"]
                    if not isinstance(request_id, str) or not request_id.strip():
                        raise RequestError(400, "invalid_request_id")
                    if not isinstance(merchant_id, str) or not merchant_id.strip():
                        raise RequestError(400, "invalid_merchant_id")
                    if not isinstance(buyer, dict) or set(buyer) != {"card_id", "mandate_id"}:
                        raise RequestError(400, "invalid_buyer")
                    if not all(isinstance(buyer[key], str) and buyer[key] for key in buyer):
                        raise RequestError(400, "invalid_buyer")
                    if not isinstance(order, dict) or set(order) != {
                        "billing_amount_chf", "delivery_fee_chf", "items"
                    }:
                        raise RequestError(400, "invalid_order")
                    try:
                        total = _money(order["billing_amount_chf"])
                        delivery = _money(order["delivery_fee_chf"])
                        if total <= 0 or not isinstance(order["items"], list) or not order["items"]:
                            raise ValueError()
                        subtotal = Decimal("0")
                        for item in order["items"]:
                            if not isinstance(item, dict) or set(item) != {
                                "item_id", "quantity", "unit_price_chf"
                            }:
                                raise ValueError()
                            if not isinstance(item["item_id"], str) or not item["item_id"]:
                                raise ValueError()
                            if (not isinstance(item["quantity"], int) or
                                    isinstance(item["quantity"], bool) or item["quantity"] < 1):
                                raise ValueError()
                            price = _money(item["unit_price_chf"])
                            if price <= 0:
                                raise ValueError()
                            subtotal += price * item["quantity"]
                        if subtotal + delivery != total:
                            raise RequestError(400, "order_total_mismatch")
                    except (ValueError, TypeError) as exc:
                        if isinstance(exc, RequestError):
                            raise
                        raise RequestError(400, "invalid_order") from exc
                self.telemetry.event(
                    "decision.schema_validated",
                    trace=trace,
                    labels={"component": "mock_api"},
                )

                fingerprint = json.dumps(body, sort_keys=True, separators=(",", ":"))
                if request_id in self.seen:
                    previous, response = self.seen[request_id]
                    if fingerprint != previous:
                        raise RequestError(409, "request_id_conflict")
                    self.telemetry.event(
                        "decision.recorded",
                        trace=trace,
                        labels={"component": "mock_api", "status": "ok"},
                    )
                    return response

                mandate_id = buyer["mandate_id"]
                configured = self.policies.get(mandate_id)
                if configured is None or configured[0] != buyer["card_id"]:
                    raise RequestError(403, "buyer_policy_not_found")
                policy = configured[1]
                timestamp = time.time() if now is None else now
                key = (buyer["card_id"], merchant_id)
                with self.telemetry.span("decision.context", trace=trace, labels={"component": "mock_api"}):
                    recent = [t for t in self.attempts[key] if timestamp - 600 < t <= timestamp]
                    self.attempts[key] = recent
                    merchant = self.merchants.get(merchant_id)
                    if merchant is None:
                        merchant = {"merchant_id": merchant_id}
                self.telemetry.event(
                    "decision.context_resolved",
                    trace=trace,
                    labels={"component": "mock_api"},
                )
                event = self._rulebook_event(
                    request_id=request_id,
                    buyer=buyer,
                    merchant=merchant,
                    order=order,
                    total=total,
                    delivery=delivery,
                    recent_attempts=len(recent),
                    timestamp=timestamp,
                    policy=policy,
                )
                started = time.perf_counter()
                with self.telemetry.span("decision.evaluate", trace=trace, labels={"component": "mock_api"}):
                    guard = self.rule_client.guard(event, {
                        "max_purchase_chf": str(policy["max_purchase_chf"]),
                        "require_familiar_merchant": policy["require_familiar_merchant"],
                    })
                    evaluated = self.rule_client.evaluate(event)
                    evaluation = evaluated["evaluation"]
                    policy_snapshot = evaluated["policy_snapshot"]
                duration_ms = (time.perf_counter() - started) * 1000
                self.telemetry.event(
                    "decision.evaluated",
                    trace=trace,
                    labels={"component": "mock_api", "outcome": evaluation["recommended_decision"]},
                )
                with self.telemetry.span("decision.record", trace=trace, labels={"component": "mock_api"}):
                    receipt = self.receipt_ledger.append(
                        authorization_id=request_id,
                        idempotency_key=f"mock-agent:{request_id}",
                        decision=evaluation["recommended_decision"],
                        policy_hash=_fixed_mandate_policy_hash(policy, policy_snapshot),
                        policy_version=f"{mandate_id}:dynamic-{policy_snapshot['revision']}",
                        engine_version=evaluation["engine_version"],
                        reason_codes=evaluation["reason_codes"],
                        checks=evaluation["checks"],
                        evidence_refs=("merchant_catalogue", "item_catalogue", "approved_history", "request_derived_velocity"),
                        request_id=request_id,
                        evaluated_at=_iso_time(timestamp),
                    )
                self.telemetry.record_decision(
                    evaluation["recommended_decision"],
                    reason_codes=evaluation["reason_codes"],
                    trace=trace,
                    duration_ms=duration_ms,
                )
                self.telemetry.event(
                    "decision.recorded",
                    trace=trace,
                    labels={"component": "mock_api", "outcome": evaluation["recommended_decision"], "status": "ok"},
                )
                response = {
                    "request_id": request_id,
                    "guard": guard,
                    "evaluation": evaluation,
                    "policy_snapshot": policy_snapshot,
                    "decision_receipt_hash": receipt["receipt_hash"],
                    "payment_authorized": False,
                    "message": "The deterministic rule service evaluated the confirmed policy. This local mock does not initiate a payment.",
                }
                self.attempts[key].append(timestamp)
                self.seen[request_id] = (fingerprint, response)
                return response
            except RequestError as exc:
                self.telemetry.record_error(exc.code, trace=trace, labels={"component": "mock_api"})
                raise


def make_handler(service: MockAgentService):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/v1/agent/policy":
                self._json(200, service.wallet_policy())
                return
            if path == "/v1/agent/observability":
                self._json(200, service.telemetry.metrics_snapshot())
                return
            self._json(404, {"error": "not_found"})

        def do_POST(self):
            if urlparse(self.path).path != "/v1/agent/simulate":
                self._json(404, {"error": "not_found"})
                return
            try:
                body = self._read_json_body()
                self._json(200, service.evaluate(body))
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "invalid_json"})
            except RequestError as exc:
                self._json(exc.status, {"error": exc.code})

        def do_PATCH(self):
            if urlparse(self.path).path != "/v1/agent/policy":
                self._json(404, {"error": "not_found"})
                return
            try:
                self._json(200, service.update_wallet_policy(self._read_json_body()))
            except PolicyConflictError as exc:
                self._json(409, {"error": str(exc)})
            except RequestError as exc:
                self._json(exc.status, {"error": exc.code})
            except (PolicyValidationError, ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})

        def _read_json_body(self) -> Any:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 65536:
                raise RequestError(413, "invalid_body_size")
            return json.loads(self.rfile.read(length))

        def _json(self, status: int, body: dict[str, Any]):
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


if __name__ == "__main__":
    receipt_path = os.environ.get("DECISION_RECEIPTS_PATH", ":memory:")
    service = MockAgentService(receipt_ledger=DecisionReceiptLedger(receipt_path))
    server = HTTPServer(("127.0.0.1", 8081), make_handler(service))
    print("Mock AI entry point: http://127.0.0.1:8081/v1/agent/simulate")
    server.serve_forever()
