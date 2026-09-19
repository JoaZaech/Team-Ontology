"""Single-container Railway entrypoint for the approval-call demonstration."""

from __future__ import annotations

from http.server import HTTPServer
import os
from pathlib import Path
import sys
import threading


PROJECT_ROOT = Path(__file__).resolve().parent
for package_dir in (PROJECT_ROOT / "mock_api", PROJECT_ROOT / "rule_service"):
    if str(package_dir) not in sys.path:
        sys.path.insert(0, str(package_dir))

from decision_receipts import DecisionReceiptLedger
from rule_client import RuleServiceClient
from rule_service.server import build_server
from viseca_mock import MockVisecaState, make_handler
from workflow_service.approval_call import approval_call_notifier_from_environment


def run() -> None:
    rule_server = build_server()
    rule_thread = threading.Thread(target=rule_server.serve_forever, name="rule-service", daemon=True)
    rule_thread.start()

    notifier, voice_token = approval_call_notifier_from_environment()
    receipt_path = Path(os.environ.get("DECISION_RECEIPTS_PATH", "/tmp/decision_receipts.sqlite3"))
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    state = MockVisecaState(
        rule_client=RuleServiceClient(),
        receipt_ledger=DecisionReceiptLedger(receipt_path),
        approval_call_notifier=notifier,
    )
    port = int(os.environ.get("PORT", "8080"))
    public_server = HTTPServer(("0.0.0.0", port), make_handler(state, voice_token))
    print(f"Agent on Leash API: http://0.0.0.0:{port}")
    try:
        public_server.serve_forever()
    finally:
        public_server.server_close()
        state.close()
        rule_server.shutdown()
        rule_thread.join()
        rule_server.server_close()


if __name__ == "__main__":
    run()
