"""HTTP client for the standalone rule_service.

Neither mock_api.py nor viseca_mock.py import the rule engine directly. Every
decision and every read/write of the customer wallet policy crosses this
client to the separately-run rule service, over plain HTTP.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_RULE_SERVICE_URL = "http://127.0.0.1:8083"


class RuleServiceError(Exception):
    pass


class PolicyValidationError(RuleServiceError):
    pass


class PolicyConflictError(PolicyValidationError):
    pass


class RuleServiceClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 5,
        api_token: str | None = None,
    ):
        self.base_url = (base_url or os.environ.get("RULE_SERVICE_URL", DEFAULT_RULE_SERVICE_URL)).rstrip("/")
        self.timeout = timeout
        self.api_token = api_token or os.environ.get("RULE_SERVICE_API_TOKEN")

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"X-Rule-Service-Token": self.api_token} if self.api_token else {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = response.read()
                return json.loads(data) if data else None
        except HTTPError as exc:
            try:
                error_body = json.loads(exc.read() or b"{}")
            except json.JSONDecodeError:
                error_body = {}
            message = error_body.get("error", f"rule service returned HTTP {exc.code}")
            if exc.code == 409:
                raise PolicyConflictError(message) from exc
            if exc.code == 400:
                raise PolicyValidationError(message) from exc
            raise RuleServiceError(message) from exc
        except URLError as exc:
            raise RuleServiceError(f"cannot reach rule service: {exc.reason}") from exc

    def get_policy(self) -> dict[str, Any]:
        return self._call("GET", "/v1/rules/policy")

    def update_policy(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self._call("PATCH", "/v1/rules/policy", request)

    def evaluate(self, event: Mapping[str, Any], run_id: str | None = None) -> dict[str, Any]:
        path = f"/v1/rules/runs/{run_id}/evaluate" if run_id else "/v1/rules/evaluate"
        return self._call("POST", path, {"event": event})

    def start_run(self, scenario_id: str, card_id: str) -> dict[str, Any]:
        return self._call("POST", "/v1/rules/runs", {
            "scenarioId": scenario_id,
            "cardId": card_id,
        })

    def record_decision(
        self,
        run_id: str,
        authorization_id: str,
        decision: str,
        customer_confirmed: bool,
    ) -> dict[str, Any]:
        return self._call("POST", f"/v1/rules/runs/{run_id}/decisions", {
            "authorizationId": authorization_id,
            "decision": decision,
            "customerConfirmed": customer_confirmed,
        })

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._call("GET", f"/v1/rules/runs/{run_id}")

    def guard(self, event: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/v1/rules/guard", {"event": event, "policy": policy})
