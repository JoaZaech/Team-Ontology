"""Standalone HTTP service wrapping the deterministic rule engine.

This is the only supported way for another process to reach the rulebook,
the guard checks, and the customer wallet policy: over HTTP, not by importing
this package's modules directly. ``guardian.py``, ``wallet_policy.py``, and
``rulebook.py`` remain pure and network-free; this module is the network
boundary around them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from secrets import compare_digest
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Mapping
from urllib.parse import urlparse

from guardian import GuardPolicy, MerchantHistory, evaluate_guard
from rulebook import evaluate_request
from scenario_rulebook import evaluate_scenario_request
from wallet_policy import (
    PolicyConflictError,
    PolicyIntegrityError,
    PolicyValidationError,
    SQLiteWalletPolicyStore,
    WalletPolicyStore,
)


DATA_DIR = Path(__file__).resolve().parents[1] / "viseca-2026" / "data"
DEFAULT_POLICY_DB_PATH = Path(
    os.environ.get("RULE_SERVICE_DB_PATH", Path(__file__).resolve().parent / "var" / "rules.sqlite3")
)
DEFAULT_PORT = 8083
MAX_BODY_BYTES = 64 * 1024
REQUEST_TIMEOUT_SECONDS = 5


class RuleEngineState:
    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        policy_store: WalletPolicyStore | SQLiteWalletPolicyStore | None = None,
        policy_db_path: Path = DEFAULT_POLICY_DB_PATH,
        api_token: str | None = None,
    ):
        token = api_token if api_token is not None else os.environ.get("RULE_SERVICE_API_TOKEN")
        if not isinstance(token, str) or len(token) < 32:
            raise ValueError("RULE_SERVICE_API_TOKEN must be at least 32 characters")
        self.history = MerchantHistory.from_data_dir(data_dir)
        self.policy_store = policy_store or SQLiteWalletPolicyStore(policy_db_path)
        self.api_token = token


class RuleEngineHTTPServer(HTTPServer):
    def __init__(self, address: tuple[str, int], handler, state: RuleEngineState):
        super().__init__(address, handler)
        self.rule_engine_state = state

    def get_request(self):
        request, client_address = super().get_request()
        request.settimeout(REQUEST_TIMEOUT_SECONDS)
        return request, client_address

    def server_close(self):
        try:
            close = getattr(self.rule_engine_state.policy_store, "close", None)
            if close is not None:
                close()
        finally:
            super().server_close()


def _decode_guard_policy(payload: Any) -> GuardPolicy:
    if not isinstance(payload, Mapping):
        raise ValueError("policy must be an object")

    def money(key: str) -> Decimal | None:
        value = payload.get(key)
        return None if value is None else Decimal(str(value))

    familiar = payload.get("require_familiar_merchant", False)
    attempts = payload.get("max_recent_attempts_10m", 3)
    if not isinstance(familiar, bool):
        raise ValueError("require_familiar_merchant must be a boolean")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or not 0 <= attempts <= 100:
        raise ValueError("max_recent_attempts_10m must be an integer from 0 to 100")

    return GuardPolicy(
        max_purchase_chf=money("max_purchase_chf"),
        max_period_chf=money("max_period_chf"),
        approved_spend_in_period_chf=money("approved_spend_in_period_chf"),
        require_familiar_merchant=familiar,
        max_recent_attempts_10m=attempts,
    )


def make_handler(state: RuleEngineState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RuleService"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/healthz":
                self._json(200, {"status": "ok", "service": "rule-service"})
                return
            if not self._can_access_service():
                return
            if path.startswith("/v1/rules/runs/"):
                self._read_run(path.removeprefix("/v1/rules/runs/"))
                return
            if path == "/v1/rules/policy":
                self._read_policy()
                return
            if path == "/v1/rules/policies":
                try:
                    self._json(200, {"policies": state.policy_store.list()})
                except PolicyIntegrityError as exc:
                    self._json(503, {"error": str(exc)})
                return
            if path.startswith("/v1/rules/policies/") and path.endswith("/revisions"):
                self._read_revisions(path.removeprefix("/v1/rules/policies/").removesuffix("/revisions"))
                return
            if path.startswith("/v1/rules/policies/"):
                self._read_policy(path.rsplit("/", 1)[1])
                return
            self._json(404, {"error": "not_found"})

        def do_PATCH(self):
            if urlparse(self.path).path != "/v1/rules/policy":
                self._json(404, {"error": "not_found"})
                return
            if not self._can_access_service():
                return
            try:
                self._json(200, state.policy_store.update(self._read_json_body()))
            except PolicyConflictError as exc:
                self._json(409, {"error": str(exc)})
            except PolicyIntegrityError as exc:
                self._json(503, {"error": str(exc)})
            except (PolicyValidationError, ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})

        def do_POST(self):
            path = urlparse(self.path).path
            if not self._can_access_service():
                return
            try:
                body = self._read_json_body()
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "invalid_json"})
                return
            if path == "/v1/rules/runs":
                self._start_run(body)
            elif path.startswith("/v1/rules/runs/") and path.endswith("/evaluate"):
                self._evaluate_run(path.removeprefix("/v1/rules/runs/").removesuffix("/evaluate"), body)
            elif path.startswith("/v1/rules/runs/") and path.endswith("/decisions"):
                self._record_run_decision(path.removeprefix("/v1/rules/runs/").removesuffix("/decisions"), body)
            elif path == "/v1/rules/evaluate":
                self._evaluate(body)
            elif path == "/v1/rules/guard":
                self._guard(body)
            elif path == "/v1/rules/policies":
                self._create_policy(body)
            else:
                self._json(404, {"error": "not_found"})

        def _read_policy(self, policy_id: str | None = None):
            try:
                self._json(200, state.policy_store.get(policy_id))
            except PolicyIntegrityError as exc:
                self._json(503, {"error": str(exc)})
            except PolicyValidationError as exc:
                self._json(404, {"error": str(exc)})

        def _read_run(self, run_id: str):
            try:
                self._json(200, state.policy_store.get_run_status(run_id))
            except PolicyValidationError as exc:
                self._json(404, {"error": str(exc)})
            except PolicyIntegrityError as exc:
                self._json(503, {"error": str(exc)})

        def _start_run(self, body: Any):
            try:
                if not isinstance(body, Mapping) or set(body) != {"scenarioId", "cardId"}:
                    raise PolicyValidationError("run request is invalid")
                self._json(201, state.policy_store.start_run(body["scenarioId"], body["cardId"]))
            except PolicyConflictError as exc:
                self._json(409, {"error": str(exc)})
            except (PolicyValidationError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
            except PolicyIntegrityError as exc:
                self._json(503, {"error": str(exc)})

        def _evaluate_run(self, run_id: str, body: Any):
            try:
                if not isinstance(body, Mapping) or set(body) != {"event"}:
                    raise PolicyValidationError("run evaluation request is invalid")
                event = body["event"]
                evaluation, snapshot = state.policy_store.evaluate_run_event(
                    run_id,
                    event,
                    lambda scenario_policy, wallet_policy, prior_approved_events: evaluate_scenario_request(
                        event,
                        state.history,
                        scenario_policy,
                        wallet_policy,
                        prior_approved_events,
                    ),
                )
                self._json(200, {"evaluation": evaluation, "policySnapshot": snapshot})
            except PolicyConflictError as exc:
                self._json(409, {"error": str(exc)})
            except (PolicyValidationError, ValueError, TypeError) as exc:
                self._json(400, {"error": str(exc)})
            except PolicyIntegrityError as exc:
                self._json(503, {"error": str(exc)})

        def _record_run_decision(self, run_id: str, body: Any):
            try:
                if not isinstance(body, Mapping) or set(body) != {
                    "authorizationId", "decision", "customerConfirmed"
                }:
                    raise PolicyValidationError("run decision request is invalid")
                self._json(200, state.policy_store.record_run_decision(
                    run_id,
                    body["authorizationId"],
                    body["decision"],
                    body["customerConfirmed"],
                ))
            except PolicyConflictError as exc:
                self._json(409, {"error": str(exc)})
            except (PolicyValidationError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
            except PolicyIntegrityError as exc:
                self._json(503, {"error": str(exc)})

        def _create_policy(self, body: Any):
            try:
                self._json(201, state.policy_store.create(body))
            except PolicyConflictError as exc:
                self._json(409, {"error": str(exc)})
            except (PolicyValidationError, ValueError) as exc:
                self._json(400, {"error": str(exc)})

        def _read_revisions(self, policy_id: str):
            try:
                self._json(200, {"policyId": policy_id, "revisions": state.policy_store.revisions(policy_id)})
            except PolicyIntegrityError as exc:
                self._json(503, {"error": str(exc)})
            except PolicyValidationError as exc:
                self._json(404, {"error": str(exc)})

        def _can_access_service(self) -> bool:
            token = state.api_token
            supplied_values = self.headers.get_all("X-Rule-Service-Token") or []
            if len(supplied_values) != 1:
                self._json(401, {"error": "service_unauthorized"})
                return False
            supplied = supplied_values[0]
            if compare_digest(supplied, token):
                return True
            self._json(401, {"error": "service_unauthorized"})
            return False

        def _evaluate(self, body: Any):
            if not isinstance(body, Mapping) or "event" not in body:
                self._json(400, {"error": "invalid_request"})
                return
            if "wallet_policy" in body:
                self._json(400, {"error": "untrusted_policy_snapshot"})
                return
            try:
                card_id = body["event"]["authorization"]["card_id"]
                get_for_card = getattr(state.policy_store, "get_for_card", None)
                policy_snapshot = get_for_card(card_id) if get_for_card else state.policy_store.get()
                evaluation = evaluate_request(body["event"], state.history, wallet_policy=policy_snapshot)
            except PolicyIntegrityError as exc:
                self._json(503, {"error": str(exc)})
                return
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
            content_lengths = self.headers.get_all("Content-Length") or []
            if len(content_lengths) != 1 or not content_lengths[0].isdigit():
                raise ValueError("invalid_body_size")
            length = int(content_lengths[0])
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise ValueError("invalid_content_type")
            if length < 1 or length > MAX_BODY_BYTES:
                raise ValueError("invalid_body_size")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete_body")
            return json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)

        def _json(self, status: int, body: dict[str, Any]):
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def build_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT, state: RuleEngineState | None = None) -> HTTPServer:
    if host != "127.0.0.1":
        raise ValueError("rule service may only bind to 127.0.0.1; use an authenticated TLS reverse proxy")
    engine_state = state or RuleEngineState()
    return RuleEngineHTTPServer((host, port), make_handler(engine_state), engine_state)


if __name__ == "__main__":
    server = build_server()
    host, port = server.server_address
    print(f"Rule service: http://{host}:{port}")
    server.serve_forever()
