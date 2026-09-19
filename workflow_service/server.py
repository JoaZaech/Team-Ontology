"""HTTP boundary for the authorization workflow service."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from secrets import compare_digest
from typing import Any
from urllib.parse import urlparse

from .inference import DecisionHub, KnowledgeGraphSubsystem, PolicySubsystem
from .flywheel import EvidenceServiceOutboxPublisher
from .workflow import WorkflowState
from decision_receipts import DecisionReceiptLedger
from rule_client import RuleServiceClient


DEFAULT_PORT = int(os.environ.get("WORKFLOW_SERVICE_PORT", "8084"))
MAX_BODY_BYTES = 64 * 1024
REQUEST_TIMEOUT_SECONDS = 5
AUTHORIZATIONS_PATH = "/v1/authorizations/"


def _decision_hub(rule_client: RuleServiceClient) -> DecisionHub:
    graph_url = os.environ.get("KNOWLEDGE_GRAPH_SERVICE_URL")
    advisors = ()
    if graph_url:
        advisors = (KnowledgeGraphSubsystem(
            graph_url,
            os.environ.get("KNOWLEDGE_GRAPH_SERVICE_API_TOKEN"),
            required=os.environ.get("KNOWLEDGE_GRAPH_REQUIRED", "false").lower() == "true",
        ),)
    return DecisionHub(PolicySubsystem(rule_client), advisors)


class WorkflowServiceState(WorkflowState):
    def status(self, authorization_id: str) -> dict[str, Any]:
        if authorization_id != self.authorization_id or self.event is None:
            raise ValueError("unknown_authorization")
        state = "pending"
        if self.resolution is not None:
            state = "resolved"
        elif self.decision is not None:
            state = "step_up" if self.decision["decision"] == "step_up" else "recorded"
        return {
            "authorization_id": authorization_id,
            "status": state,
            "recommended_decision": self.evaluation.get("recommended_decision") if self.evaluation else None,
            "decision": self.decision,
            "resolution": self.resolution,
        }


class WorkflowHTTPServer(HTTPServer):
    def __init__(self, address: tuple[str, int], handler, state: WorkflowServiceState, api_token: str):
        super().__init__(address, handler)
        self.workflow_state = state
        self.workflow_api_token = api_token

    def get_request(self):
        request, client_address = super().get_request()
        request.settimeout(REQUEST_TIMEOUT_SECONDS)
        return request, client_address

    def server_close(self):
        try:
            self.workflow_state.close()
        finally:
            super().server_close()


class WorkflowRequestHandler(BaseHTTPRequestHandler):
    server_version = "WorkflowService"
    sys_version = ""

    @property
    def state(self) -> WorkflowServiceState:
        return self.server.workflow_state

    @property
    def api_token(self) -> str:
        return self.server.workflow_api_token

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/healthz":
            self._json(200, {"status": "ok", "service": "workflow-service"})
        elif not self._authorized():
            return
        elif path == "/v1/activity":
            self._json(200, self.state.activity_snapshot())
        elif path == "/v1/observability":
            self._json(200, self.state.telemetry.metrics_snapshot())
        elif path == "/v1/flywheel":
            self._json(200, self.state.flywheel_status())
        elif path.startswith(AUTHORIZATIONS_PATH) and "/" not in path.removeprefix(AUTHORIZATIONS_PATH):
            self._status(path.removeprefix(AUTHORIZATIONS_PATH))
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self):
        if not self._authorized():
            return
        try:
            body = self._read_json_body()
        except ValueError:
            self._json(400, {"error": "invalid_json"})
            return
        path = urlparse(self.path).path
        if path == "/v1/authorizations":
            self._start(body)
        elif path == "/v1/workflows/reset":
            self._reset(body)
        elif path.startswith(AUTHORIZATIONS_PATH):
            self._authorization_action(path.removeprefix(AUTHORIZATIONS_PATH), body)
        else:
            self._json(404, {"error": "not_found"})

    def _start(self, body: Any) -> None:
        if not isinstance(body, dict) or set(body) not in ({"event", "runId"}, {"event", "runId", "eventId"}):
            self._json(400, {"error": "invalid_authorization_request"})
            return
        if not isinstance(body["runId"], str) or not body["runId"]:
            self._json(400, {"error": "invalid_run_id"})
            return
        event_id = body.get("eventId")
        if event_id is not None and (not isinstance(event_id, str) or not event_id):
            self._json(400, {"error": "invalid_event_id"})
            return
        try:
            self._json(201, self.state.start(body["event"], body["runId"], event_id))
        except ValueError as exc:
            self._json(409, {"error": str(exc)})

    def _reset(self, body: Any) -> None:
        if body not in ({}, None):
            self._json(400, {"error": "invalid_reset_request"})
            return
        self.state.reset()
        self._json(200, {"status": "reset"})

    def _authorization_action(self, path: str, body: Any) -> None:
        authorization_id, separator, operation = path.partition("/")
        if not separator:
            self._json(404, {"error": "not_found"})
            return
        try:
            response = self._operation(authorization_id, operation, body)
            self._json(200, response)
        except ValueError as exc:
            self.state.record_activity_failure("workflow_request", str(exc))
            self._json(409, {"error": str(exc)})

    def _operation(self, authorization_id: str, operation: str, body: Any) -> dict[str, Any]:
        if operation == "evaluate" and body in ({}, None):
            return self.state.evaluate()
        if operation == "decision":
            return self.state.record_decision(authorization_id, body)
        if operation == "resolution":
            return self.state.resolve_decision(authorization_id, body)
        raise ValueError("not_found")

    def _status(self, authorization_id: str) -> None:
        try:
            self._json(200, self.state.status(authorization_id))
        except ValueError as exc:
            self._json(404, {"error": str(exc)})

    def _authorized(self) -> bool:
        supplied = self.headers.get_all("X-Workflow-Service-Token") or []
        if len(supplied) == 1 and compare_digest(supplied[0], self.api_token):
            return True
        self._json(401, {"error": "service_unauthorized"})
        return False

    def _read_json_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY_BYTES:
            raise ValueError("invalid_body_size")
        return json.loads(self.rfile.read(length))

    def _json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run() -> None:
    token = os.environ.get("WORKFLOW_SERVICE_API_TOKEN")
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("WORKFLOW_SERVICE_API_TOKEN must be at least 32 characters")
    receipt_path = Path(os.environ.get("DECISION_RECEIPTS_PATH", "var/workflow-receipts.sqlite3"))
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    rule_client = RuleServiceClient()
    receipt_ledger = DecisionReceiptLedger(receipt_path)
    evidence_url = os.environ.get("EVIDENCE_SERVICE_URL")
    evidence_token = os.environ.get("EVIDENCE_SERVICE_API_TOKEN")
    publisher = None
    if evidence_url:
        if not isinstance(evidence_token, str) or len(evidence_token) < 32:
            raise ValueError("EVIDENCE_SERVICE_API_TOKEN must be at least 32 characters when EVIDENCE_SERVICE_URL is set")
        publisher = EvidenceServiceOutboxPublisher(receipt_ledger, evidence_url, evidence_token)
    state = WorkflowServiceState(
        rule_client=rule_client,
        decision_hub=_decision_hub(rule_client),
        receipt_ledger=receipt_ledger,
        flywheel_publisher=publisher,
    )
    if publisher is not None:
        publisher.start()
    server = WorkflowHTTPServer(("127.0.0.1", DEFAULT_PORT), WorkflowRequestHandler, state, token)
    print(f"Workflow service: http://127.0.0.1:{DEFAULT_PORT}")
    getattr(server, "serve_forever")()


if __name__ == "__main__":
    run()
