"""Authenticated HTTP client for the authorization workflow service."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class WorkflowServiceError(ValueError):
    pass


class WorkflowServiceClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_token: str | None = None,
        timeout: float = 5,
    ):
        self.base_url = (base_url or os.environ.get("WORKFLOW_SERVICE_URL", "http://127.0.0.1:8084")).rstrip("/")
        self.api_token = api_token or os.environ.get("WORKFLOW_SERVICE_API_TOKEN")
        self.timeout = timeout

    def start(self, event: Mapping[str, Any], run_id: str, event_id: str) -> dict[str, Any]:
        return self._call("POST", "/v1/authorizations", {"event": event, "runId": run_id, "eventId": event_id})

    def reset(self) -> dict[str, Any]:
        return self._call("POST", "/v1/workflows/reset", {})

    def evaluate(self, authorization_id: str) -> dict[str, Any]:
        return self._call("POST", f"/v1/authorizations/{authorization_id}/evaluate", {})

    def record_decision(self, authorization_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        return self._call("POST", f"/v1/authorizations/{authorization_id}/decision", body)

    def resolve_decision(self, authorization_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        return self._call("POST", f"/v1/authorizations/{authorization_id}/resolution", body)

    def activity(self) -> dict[str, Any]:
        return self._call("GET", "/v1/activity")

    def observability(self) -> dict[str, Any]:
        return self._call("GET", "/v1/observability")

    def flywheel(self) -> dict[str, Any]:
        return self._call("GET", "/v1/flywheel")

    def _call(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"X-Workflow-Service-Token": self.api_token} if self.api_token else {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            try:
                response = json.loads(exc.read() or b"{}")
            except json.JSONDecodeError:
                response = {}
            raise WorkflowServiceError(response.get("error", f"workflow service returned HTTP {exc.code}")) from exc
        except URLError as exc:
            raise WorkflowServiceError(f"cannot reach workflow service: {exc.reason}") from exc
