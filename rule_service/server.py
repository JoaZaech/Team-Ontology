"""Standalone HTTP service wrapping the deterministic rule engine.

This is the only supported way for another process to reach the rulebook,
the guard checks, and the customer wallet policy: over HTTP, not by importing
this package's modules directly. ``guardian.py``, ``wallet_policy.py``, and
``rulebook.py`` remain pure and network-free; this module is the network
boundary around them.
"""

from __future__ import annotations

import json
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from guardian import GuardPolicy, MerchantHistory, evaluate_guard
from rulebook import evaluate_request
from wallet_policy import PolicyConflictError, PolicyValidationError, WalletPolicyStore


DATA_DIR = Path(__file__).resolve().parents[1] / "viseca-2026" / "data"
DEFAULT_PORT = 8083


class RuleEngineState:
    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        policy_store: WalletPolicyStore | None = None,
    ):
        self.history = MerchantHistory.from_data_dir(data_dir)
        self.policy_store = policy_store or WalletPolicyStore()


def _decode_guard_policy(payload: Any) -> GuardPolicy:
    if not isinstance(payload, Mapping):
        raise ValueError("policy must be an object")

    def money(key: str) -> Decimal | None:
        value = payload.get(key)
        return None if value is None else Decimal(str(value))

    return GuardPolicy(
        max_purchase_chf=money("max_purchase_chf"),
        max_period_chf=money("max_period_chf"),
        approved_spend_in_period_chf=money("approved_spend_in_period_chf"),
        require_familiar_merchant=bool(payload.get("require_familiar_merchant", False)),
        max_recent_attempts_10m=int(payload.get("max_recent_attempts_10m", 3)),
    )


def make_handler(state: RuleEngineState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/healthz":
                self._json(200, {"status": "ok", "service": "rule-service"})
                return
            if path == "/v1/rules/policy":
                self._json(200, state.policy_store.get())
                return
            self._json(404, {"error": "not_found"})

        def do_PATCH(self):
            if urlparse(self.path).path != "/v1/rules/policy":
                self._json(404, {"error": "not_found"})
                return
            try:
                self._json(200, state.policy_store.update(self._read_json_body()))
            except PolicyConflictError as exc:
                self._json(409, {"error": str(exc)})
            except (PolicyValidationError, ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = self._read_json_body()
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "invalid_json"})
                return
            if path == "/v1/rules/evaluate":
                self._evaluate(body)
            elif path == "/v1/rules/guard":
                self._guard(body)
            else:
                self._json(404, {"error": "not_found"})

        def _evaluate(self, body: Any):
            if not isinstance(body, Mapping) or "event" not in body:
                self._json(400, {"error": "invalid_request"})
                return
            try:
                policy_snapshot = state.policy_store.get()
                evaluation = evaluate_request(body["event"], state.history, wallet_policy=policy_snapshot)
            except (KeyError, ValueError, TypeError):
                self._json(400, {"error": "invalid_event"})
                return
            self._json(200, {"evaluation": evaluation, "policy_snapshot": policy_snapshot})

        def _guard(self, body: Any):
            if not isinstance(body, Mapping) or "event" not in body or "policy" not in body:
                self._json(400, {"error": "invalid_request"})
                return
            try:
                policy = _decode_guard_policy(body["policy"])
                guard = evaluate_guard(body["event"], state.history, policy)
            except (KeyError, ValueError, TypeError):
                self._json(400, {"error": "invalid_request"})
                return
            self._json(200, guard)

        def _read_json_body(self) -> Any:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 65536:
                raise ValueError("invalid_body_size")
            return json.loads(self.rfile.read(length))

        def _json(self, status: int, body: dict[str, Any]):
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def build_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT, state: RuleEngineState | None = None) -> HTTPServer:
    return HTTPServer((host, port), make_handler(state or RuleEngineState()))


if __name__ == "__main__":
    server = build_server()
    host, port = server.server_address
    print(f"Rule service: http://{host}:{port}")
    server.serve_forever()
