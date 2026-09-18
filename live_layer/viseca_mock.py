"""Local Viseca-shaped API for the SCEN0000 connection-check fixture.

This is a contract rehearsal, not Viseca's hosted simulator. It serves one
synthetic request and records one local decision; nothing is sent externally.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DATA_DIR = Path(__file__).resolve().parents[1] / "viseca-2026" / "data"
MOCK_KEY = "mock-team-key"  # Public dummy value, only for local contract rehearsal.
MOCK_RUN_ID = "RUN_MOCK_0001"
MOCK_AUTHORIZATION_ID = "MOCK_AU0001"

DEMO_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Viseca local API mock</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, sans-serif; background: #f4f6fa; color: #16243a; }
    body { margin: 0; padding: 32px 20px; }
    main { max-width: 760px; margin: 0 auto; }
    .card { background: white; border: 1px solid #dce3eb; border-radius: 16px; padding: 26px; box-shadow: 0 8px 30px #16304a0b; }
    h1 { margin: 0 0 8px; font-size: 1.8rem; }
    p { line-height: 1.5; color: #46566c; }
    .tag { display: inline-block; padding: 5px 10px; border-radius: 100px; background: #e5f5ed; color: #166343; font-size: .8rem; font-weight: 700; margin-bottom: 18px; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin: 22px 0; }
    button { border: 0; border-radius: 9px; padding: 11px 15px; font: inherit; font-weight: 650; cursor: pointer; background: #174ea6; color: white; }
    button.secondary { background: #e9eef5; color: #20344d; }
    button:disabled { opacity: .5; cursor: wait; }
    #status { min-height: 24px; font-weight: 600; color: #244467; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #101c2f; color: #e7f0ff; padding: 18px; border-radius: 10px; max-height: 480px; overflow: auto; font-size: .84rem; }
    small { color: #66758a; }
  </style>
</head>
<body><main><div class="card">
  <span class="tag">LOCAL MOCK · NO REAL PAYMENT</span>
  <h1>Viseca purchase request rehearsal</h1>
  <p>This page serves one synthetic purchase from the company's SCEN0000 connection check. Load the request, inspect its buyer and merchant details, and record a sample customer-review decision.</p>
  <div class="actions">
    <button id="load">Load mock request</button>
    <button id="decide" class="secondary">Record step-up</button>
    <button id="reset" class="secondary">Reset demo</button>
  </div>
  <div id="status" role="status" aria-live="polite">Ready.</div>
  <pre id="output">The request will appear here.</pre>
  <small>API base: http://127.0.0.1:8082 · Dummy key: mock-team-key</small>
</div></main>
<script>
const headers = {Authorization: 'Bearer mock-team-key'};
const status = document.getElementById('status');
const output = document.getElementById('output');
async function show(response) {
  if (response.status === 204) { status.textContent = 'Request already delivered. Use Reset demo to replay it.'; return; }
  const data = await response.json();
  output.textContent = JSON.stringify(data, null, 2);
  status.textContent = response.ok ? 'Request completed.' : `API error: ${response.status}`;
}
document.getElementById('load').onclick = async () => {
  try { status.textContent = 'Loading…'; await show(await fetch('/v1/decision-requests/next?wait=0', {headers})); }
  catch (error) { status.textContent = `Connection failed: ${error.message}`; }
};
document.getElementById('decide').onclick = async () => {
  try {
    status.textContent = 'Recording…';
    await show(await fetch('/v1/authorizations/MOCK_AU0001/decision', {
      method: 'POST', headers: {...headers, 'Content-Type': 'application/json'},
      body: JSON.stringify({authorization_id: 'MOCK_AU0001', decision: 'step_up', reason_codes: ['customer_confirmation']})
    }));
  } catch (error) { status.textContent = `Connection failed: ${error.message}`; }
};
document.getElementById('reset').onclick = async () => {
  try { status.textContent = 'Resetting…'; await show(await fetch('/mock/reset', {method: 'POST', headers})); }
  catch (error) { status.textContent = `Connection failed: ${error.message}`; }
};
</script></body></html>"""


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
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.delivered = False
        self.decision: dict[str, Any] | None = None

    def reset(self) -> None:
        self.delivered = False
        self.decision = None

    def next_request(self) -> dict[str, Any] | None:
        if self.delivered:
            return None
        self.delivered = True
        event = build_connection_event(self.data_dir)
        return {
            "run_id": MOCK_RUN_ID,
            "event_id": "EVT_MOCK_0001",
            "type": "authorization.request",
            "authorization_id": MOCK_AUTHORIZATION_ID,
            "status": "pending",
            "occurred_at": event["runtime"]["received_at"],
            "data": event,
        }

    def record_decision(self, authorization_id: str, body: Any) -> dict[str, Any]:
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
            return {"authorization_id": authorization_id, "status": "already_recorded"}
        self.decision = body
        return {"authorization_id": authorization_id, "status": "recorded",
                "decision": body["decision"]}


def make_handler(state: MockVisecaState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self.send_html(200, DEMO_PAGE)
                return
            if path == "/healthz":
                self.send_json(200, {"status": "ok", "service": "local-viseca-mock",
                                     "pack_version": "saw26"})
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
            prefix, suffix = "/v1/authorizations/", "/decision"
            if not path.startswith(prefix) or not path.endswith(suffix):
                self.send_json(404, {"error": "not_found"})
                return
            authorization_id = path[len(prefix):-len(suffix)]
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 65536:
                    raise ValueError("invalid_body_size")
                body = json.loads(self.rfile.read(length))
                self.send_json(200, state.record_decision(authorization_id, body))
            except (ValueError, json.JSONDecodeError) as exc:
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

        def send_html(self, status: int, html: str):
            payload = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def send_response_only_204(self):
            self.send_response(204)
            self.end_headers()

    return Handler


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 8082), make_handler(MockVisecaState()))
    print("Local Viseca mock: http://127.0.0.1:8082")
    server.serve_forever()
