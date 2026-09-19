"""Local Viseca-shaped API for the SCEN0000 connection-check fixture.

This is a contract rehearsal, not Viseca's hosted simulator. It serves one
synthetic request and records one local decision; nothing is sent externally.
"""

from __future__ import annotations

import csv
from hashlib import sha256
import json
import mimetypes
import os
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from decision_receipts import DecisionReceiptLedger, canonical_json
from guardian import MerchantHistory
from observability import Telemetry
from rulebook import evaluate_request
from wallet_policy import PolicyConflictError, PolicyValidationError, WalletPolicyStore


DATA_DIR = Path(__file__).resolve().parents[1] / "viseca-2026" / "data"
MOCK_KEY = "mock-team-key"  # Public dummy value, only for local contract rehearsal.
MOCK_RUN_ID = "RUN_MOCK_0001"
MOCK_AUTHORIZATION_ID = "MOCK_AU0001"

# Built by the TypeScript/Vue app in decision-lab/ — run `npm run build` there after
# changing the UI. This server only serves the resulting static files.
DIST_DIR = Path(__file__).with_name("decision-lab") / "dist"


def _policy_hash(policy: dict[str, Any]) -> str:
    return f"sha256:{sha256(canonical_json(policy).encode('utf-8')).hexdigest()}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _deadline_remaining_ms(deadline_at: str, now: datetime) -> int:
    return max(0, int((_parse_time(deadline_at) - now).total_seconds() * 1000))


def _csv_row(path: Path, key: str, value: str) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as stream:
        return next(row for row in csv.DictReader(stream) if row[key] == value)


def build_connection_event(data_dir: Path = DATA_DIR, now: datetime | None = None) -> dict[str, Any]:
    """Build the actual AU0001 purchase as a live-event-shaped JSON object."""
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


class MockVisecaState:
    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        policy_store: WalletPolicyStore | None = None,
        receipt_ledger: DecisionReceiptLedger | None = None,
        telemetry: Telemetry | None = None,
    ):
        self.data_dir = data_dir
        self.history = MerchantHistory.from_data_dir(data_dir)
        self.policy_store = policy_store or WalletPolicyStore()
        self.receipt_ledger = receipt_ledger or DecisionReceiptLedger(":memory:")
        self.telemetry = telemetry or Telemetry()
        self.delivered = False
        self.decision: dict[str, Any] | None = None
        self.resolution: dict[str, Any] | None = None
        self.event: dict[str, Any] | None = None
        self.evaluation: dict[str, Any] | None = None
        self.policy_snapshot: dict[str, Any] | None = None
        self.trace: Any | None = None
        self.step_up_recorded_at: datetime | None = None

    def close(self) -> None:
        self.receipt_ledger.close()

    def reset(self) -> None:
        self.delivered = False
        self.decision = None
        self.resolution = None
        self.event = None
        self.evaluation = None
        self.policy_snapshot = None
        self.trace = None
        self.step_up_recorded_at = None

    def _receipt_key(self, stage: str) -> str:
        if self.event is None:
            raise ValueError("request_not_delivered")
        return f"{stage}:{self.event['request_id']}:{self.event['runtime']['received_at']}"

    def next_request(self, now: datetime | None = None) -> dict[str, Any] | None:
        if self.delivered:
            return None
        self.delivered = True
        event = build_connection_event(self.data_dir, now=now)
        self.event = event
        self.policy_snapshot = self.policy_store.get()
        self.trace = self.telemetry.start_trace(event["request_id"])
        self.telemetry.event(
            "decision.request_received",
            trace=self.trace,
            labels={"component": "viseca_mock", "status": "received"},
        )
        return {
            "run_id": MOCK_RUN_ID,
            "event_id": "EVT_MOCK_0001",
            "type": "authorization.request",
            "authorization_id": MOCK_AUTHORIZATION_ID,
            "status": "pending",
            "occurred_at": event["runtime"]["received_at"],
            "data": event,
        }

    def evaluate(self) -> dict[str, Any]:
        if self.event is None:
            raise ValueError("request_not_delivered")
        if self.evaluation is not None:
            return self.evaluation
        if self.policy_snapshot is None:
            raise ValueError("policy_snapshot_unavailable")
        started = time.perf_counter()
        with self.telemetry.span(
            "decision.evaluate",
            trace=self.trace,
            labels={"component": "viseca_mock"},
        ):
            result = evaluate_request(
                self.event,
                self.history,
                wallet_policy=self.policy_snapshot,
            )
        duration_ms = (time.perf_counter() - started) * 1000
        evaluated_at = _utc_now()
        authorization = self.event["authorization"]
        receipt = self.receipt_ledger.append(
            authorization_id=authorization["authorization_id"],
            idempotency_key=self._receipt_key("evaluation"),
            decision=result["recommended_decision"],
            policy_hash=_policy_hash(self.policy_snapshot),
            policy_version=self.policy_snapshot["revision"],
            engine_version=result["engine_version"],
            reason_codes=result["reason_codes"],
            checks=result["checks"],
            evidence_refs=(
                "authorization_event",
                "confirmed_mandate",
                {"source": "dynamic_wallet_policy", "revision": self.policy_snapshot["revision"]},
                "merchant_history",
            ),
            run_id=MOCK_RUN_ID,
            request_id=self.event["request_id"],
            received_at=self.event["runtime"]["received_at"],
            evaluated_at=_iso_time(evaluated_at),
            deadline_at=self.event["deadline_at"],
            deadline_remaining_ms=_deadline_remaining_ms(self.event["deadline_at"], evaluated_at),
        )
        self.telemetry.event(
            "decision.context_resolved",
            trace=self.trace,
            labels={"component": "viseca_mock", "status": "ok"},
            attributes={"policy_version": f"policy_{self.policy_snapshot['revision']}"},
        )
        self.telemetry.event(
            "decision.evaluated",
            trace=self.trace,
            labels={"component": "viseca_mock", "outcome": result["recommended_decision"]},
            attributes={
                "engine_version": result["engine_version"],
                "receipt_hash": receipt["receipt_hash"],
            },
        )
        self.telemetry.record_decision(
            result["recommended_decision"],
            reason_codes=result["reason_codes"],
            trace=self.trace,
            duration_ms=duration_ms,
            labels={"component": "viseca_mock"},
            attributes={
                "engine_version": result["engine_version"],
                "receipt_hash": receipt["receipt_hash"],
            },
        )
        self.evaluation = result
        return result

    def record_decision(
        self,
        authorization_id: str,
        body: Any,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if authorization_id != MOCK_AUTHORIZATION_ID:
            raise ValueError("unknown_authorization")
        if not self.delivered:
            raise ValueError("request_not_delivered")
        if not isinstance(body, dict) or body.get("authorization_id") != authorization_id:
            raise ValueError("authorization_id_mismatch")
        if body.get("decision") not in ("approve", "decline", "step_up"):
            raise ValueError("invalid_decision")
        if self.decision is not None:
            if self.decision != body:
                raise ValueError("decision_conflict")
            receipt = self.receipt_ledger.get(self._receipt_key("decision"))
            return {
                "authorization_id": authorization_id,
                "status": "already_recorded",
                **({"decision_receipt_hash": receipt["receipt_hash"]} if receipt else {}),
            }
        if self.event is None or self.policy_snapshot is None:
            raise ValueError("request_not_delivered")
        recorded_at = now or _utc_now()
        if recorded_at > _parse_time(self.event["deadline_at"]):
            self.telemetry.event(
                "decision.deadline_missed",
                trace=self.trace,
                labels={"component": "viseca_mock", "status": "error"},
                attributes={"deadline_missed": True},
            )
            raise ValueError("decision_deadline_exceeded")
        reason_codes = body.get("reason_codes", [])
        if (
            isinstance(reason_codes, str)
            or not isinstance(reason_codes, (list, tuple))
            or not all(isinstance(reason_code, str) and reason_code for reason_code in reason_codes)
        ):
            raise ValueError("invalid_reason_codes")
        evaluation = self.evaluate()
        with self.telemetry.span(
            "decision.record",
            trace=self.trace,
            labels={"component": "viseca_mock"},
        ):
            receipt = self.receipt_ledger.append(
                authorization_id=authorization_id,
                idempotency_key=self._receipt_key("decision"),
                decision=body["decision"],
                policy_hash=_policy_hash(self.policy_snapshot),
                policy_version=self.policy_snapshot["revision"],
                engine_version=evaluation["engine_version"],
                reason_codes=reason_codes,
                checks=evaluation["checks"],
                evidence_refs=(
                    "authorization_event",
                    "confirmed_mandate",
                    {"source": "dynamic_wallet_policy", "revision": self.policy_snapshot["revision"]},
                    "merchant_history",
                ),
                run_id=MOCK_RUN_ID,
                request_id=self.event["request_id"],
                received_at=self.event["runtime"]["received_at"],
                evaluated_at=_iso_time(recorded_at),
                deadline_at=self.event["deadline_at"],
                deadline_remaining_ms=_deadline_remaining_ms(self.event["deadline_at"], recorded_at),
            )
        self.decision = body
        if body["decision"] == "step_up":
            self.step_up_recorded_at = recorded_at
            self.telemetry.event(
                "decision.step_up",
                trace=self.trace,
                labels={"component": "viseca_mock", "status": "recorded"},
            )
        self.telemetry.event(
            "decision.recorded",
            trace=self.trace,
            labels={
                "component": "viseca_mock",
                "outcome": body["decision"],
                "status": "recorded",
            },
            attributes={
                "deadline_headroom_ms": _deadline_remaining_ms(self.event["deadline_at"], recorded_at),
                "receipt_hash": receipt["receipt_hash"],
                "idempotency_result": "recorded",
            },
        )
        return {
            "authorization_id": authorization_id,
            "status": "recorded",
            "decision": body["decision"],
            "decision_receipt_hash": receipt["receipt_hash"],
        }

    def resolve_decision(
        self,
        authorization_id: str,
        body: Any,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if authorization_id != MOCK_AUTHORIZATION_ID:
            raise ValueError("unknown_authorization")
        if self.decision is None or self.decision.get("decision") != "step_up":
            raise ValueError("resolution_not_available")
        if not isinstance(body, dict) or body.get("authorization_id") != authorization_id:
            raise ValueError("authorization_id_mismatch")
        if body.get("decision") not in ("approve", "decline"):
            raise ValueError("invalid_resolution_decision")
        if self.resolution is not None:
            if self.resolution != body:
                raise ValueError("resolution_conflict")
            receipt = self.receipt_ledger.get(self._receipt_key("resolution"))
            return {
                "authorization_id": authorization_id,
                "status": "already_resolved",
                **({"decision_receipt_hash": receipt["receipt_hash"]} if receipt else {}),
            }
        if self.event is None or self.policy_snapshot is None:
            raise ValueError("request_not_delivered")
        resolved_at = now or _utc_now()
        if self.step_up_recorded_at is not None and resolved_at > self.step_up_recorded_at + timedelta(seconds=120):
            self.telemetry.event(
                "decision.deadline_missed",
                trace=self.trace,
                labels={"component": "viseca_mock", "status": "error"},
                attributes={"deadline_missed": True},
            )
            raise ValueError("resolution_deadline_exceeded")
        evaluation = self.evaluate()
        final_resolution = {
            "decision": body["decision"],
            "resolved_at": _iso_time(resolved_at),
            "spend_effect": "approved" if body["decision"] == "approve" else "declined",
        }
        with self.telemetry.span(
            "decision.resolve",
            trace=self.trace,
            labels={"component": "viseca_mock"},
        ):
            receipt = self.receipt_ledger.append(
                authorization_id=authorization_id,
                idempotency_key=self._receipt_key("resolution"),
                decision=body["decision"],
                policy_hash=_policy_hash(self.policy_snapshot),
                policy_version=self.policy_snapshot["revision"],
                engine_version=evaluation["engine_version"],
                reason_codes=("customer_confirmation",),
                checks=evaluation["checks"],
                evidence_refs=(
                    "authorization_event",
                    "confirmed_mandate",
                    {"source": "dynamic_wallet_policy", "revision": self.policy_snapshot["revision"]},
                    "customer_resolution",
                ),
                run_id=MOCK_RUN_ID,
                request_id=self.event["request_id"],
                received_at=self.event["runtime"]["received_at"],
                evaluated_at=_iso_time(resolved_at),
                deadline_at=self.event["deadline_at"],
                deadline_remaining_ms=_deadline_remaining_ms(self.event["deadline_at"], resolved_at),
                final_resolution=final_resolution,
            )
        self.resolution = body
        self.telemetry.event(
            "decision.resolved",
            trace=self.trace,
            labels={
                "component": "viseca_mock",
                "outcome": body["decision"],
                "status": "resolved",
            },
            attributes={"receipt_hash": receipt["receipt_hash"]},
        )
        return {
            "authorization_id": authorization_id,
            "status": "resolved",
            "decision": body["decision"],
            "decision_receipt_hash": receipt["receipt_hash"],
        }


def make_handler(state: MockVisecaState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self.send_static_file(DIST_DIR / "index.html")
                return
            if path == "/healthz":
                self.send_json(200, {"status": "ok", "service": "local-viseca-mock",
                                     "pack_version": "saw26"})
                return
            if path.startswith("/assets/"):
                self.send_static_file(DIST_DIR / path.lstrip("/"))
                return
            if not self.authorized():
                return
            if path == "/v1/bootstrap":
                self.send_json(200, {"mock": True, "pack_version": "saw26",
                                     "decision_timeout_seconds": 8,
                                     "scenarios": [{"scenario_id": "SCEN0000", "event_count": 1}]})
            elif path == "/v1/reference-data":
                self.send_json(200, {"mock": True, "pack_version": "saw26",
                                     "source": "viseca-2026/data", "scenario_id": "SCEN0000",
                                     "source_authorization_id": "AU0001"})
            elif path == "/mock/policy":
                self.send_json(200, state.policy_store.get())
            elif path == "/mock/observability":
                self.send_json(200, state.telemetry.metrics_snapshot())
            elif path == "/v1/decision-requests/next":
                event = state.next_request()
                self.send_json(200, event) if event else self.send_response_only_204()
            else:
                self.send_json(404, {"error": "not_found"})

        def do_POST(self):
            if not self.authorized():
                return
            path = urlparse(self.path).path
            if path == "/mock/reset":
                state.reset()
                self.send_json(200, {"status": "reset", "run_id": MOCK_RUN_ID})
                return
            if path == "/mock/evaluate":
                try:
                    self.send_json(200, state.evaluate())
                except ValueError as exc:
                    self.send_json(409, {"error": str(exc)})
                return
            prefix = "/v1/authorizations/"
            if not path.startswith(prefix):
                self.send_json(404, {"error": "not_found"})
                return
            if path.endswith("/decision"):
                authorization_id = path[len(prefix):-len("/decision")]
                operation = state.record_decision
            elif path.endswith("/resolve"):
                authorization_id = path[len(prefix):-len("/resolve")]
                operation = state.resolve_decision
            else:
                self.send_json(404, {"error": "not_found"})
                return
            try:
                self.send_json(200, operation(authorization_id, self.read_json_body()))
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": str(exc)})

        def do_PATCH(self):
            if not self.authorized():
                return
            path = urlparse(self.path).path
            if path != "/mock/policy":
                self.send_json(404, {"error": "not_found"})
                return
            try:
                body = self.read_json_body()
                self.send_json(200, state.policy_store.update(body))
            except PolicyConflictError as exc:
                self.send_json(409, {"error": str(exc)})
            except (PolicyValidationError, ValueError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": str(exc)})

        def authorized(self) -> bool:
            if self.headers.get("Authorization") == f"Bearer {MOCK_KEY}":
                return True
            self.send_json(401, {"error": "unauthorized"})
            return False

        def send_json(self, status: int, body: dict[str, Any]):
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def read_json_body(self) -> Any:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 65536:
                raise ValueError("invalid_body_size")
            return json.loads(self.rfile.read(length))

        def send_static_file(self, file_path: Path):
            resolved = file_path.resolve()
            if DIST_DIR.resolve() not in resolved.parents and resolved != DIST_DIR.resolve():
                self.send_json(404, {"error": "not_found"})
                return
            if not resolved.is_file():
                self.send_json(404, {"error": "not_found",
                                     "hint": "Run 'npm run build' in live_layer/decision-lab first."})
                return
            content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
            payload = resolved.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def send_response_only_204(self):
            self.send_response(204)
            self.end_headers()

    return Handler


if __name__ == "__main__":
    receipt_path = os.environ.get("DECISION_RECEIPTS_PATH", ":memory:")
    state = MockVisecaState(receipt_ledger=DecisionReceiptLedger(receipt_path))
    server = HTTPServer(("127.0.0.1", 8082), make_handler(state))
    print("Local Viseca mock: http://127.0.0.1:8082")
    server.serve_forever()
