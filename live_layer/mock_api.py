"""Local-only mock AI-agent entry point for the Viseca guardian."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from guardian import GuardPolicy, MerchantHistory, _money, evaluate_guard


DATA_DIR = Path(__file__).resolve().parents[1] / "viseca-2026" / "data"


class RequestError(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code


class MockAgentService:
    """Mock policy and session state; no payment or authoritative ledger."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.history = MerchantHistory.from_data_dir(data_dir)
        # This fixed mandate represents a policy confirmed outside the agent.
        self.policies = {
            "TM_DEMO_GROCERY": ("CA0001", GuardPolicy(
                max_purchase_chf=Decimal("20.00"), require_familiar_merchant=True
            ))
        }
        self.seen: dict[str, tuple[str, dict[str, Any]]] = {}
        self.attempts: dict[tuple[str, str], list[float]] = defaultdict(list)

    def evaluate(self, body: Any, now: float | None = None) -> dict[str, Any]:
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

        # The same request ID can be retried; changed content cannot reuse it.
        fingerprint = json.dumps(body, sort_keys=True, separators=(",", ":"))
        if request_id in self.seen:
            previous, response = self.seen[request_id]
            if fingerprint != previous:
                raise RequestError(409, "request_id_conflict")
            return response

        mandate_id = buyer["mandate_id"]
        configured = self.policies.get(mandate_id)
        if configured is None or configured[0] != buyer["card_id"]:
            raise RequestError(403, "buyer_policy_not_found")
        policy = configured[1]
        timestamp = time.time() if now is None else now
        key = (buyer["card_id"], merchant_id)
        recent = [t for t in self.attempts[key] if timestamp - 600 < t <= timestamp]
        self.attempts[key] = recent
        merchant = self.history.merchants.get(merchant_id)
        if merchant is None:
            merchant = {"merchant_id": merchant_id}
        event = {"authorization": {
            "authorization_id": request_id,
            "card_id": buyer["card_id"],
            "merchant": merchant,
            "billing_amount_chf": str(total),
            "recent_attempt_count_10m": len(recent),
        }}
        guard = evaluate_guard(event, self.history, policy)
        response = {
            "request_id": request_id,
            "guard": guard,
            "payment_authorized": False,
            "message": "Mock guard only; full wallet policy and customer decision are still required.",
        }
        self.attempts[key].append(timestamp)
        self.seen[request_id] = (fingerprint, response)
        return response


def make_handler(service: MockAgentService):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/v1/agent/simulate":
                self._json(404, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 65536:
                    raise RequestError(413, "invalid_body_size")
                body = json.loads(self.rfile.read(length))
                self._json(200, service.evaluate(body))
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "invalid_json"})
            except RequestError as exc:
                self._json(exc.status, {"error": exc.code})

        def _json(self, status: int, body: dict[str, Any]):
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 8081), make_handler(MockAgentService()))
    print("Mock AI entry point: http://127.0.0.1:8081/v1/agent/simulate")
    server.serve_forever()
