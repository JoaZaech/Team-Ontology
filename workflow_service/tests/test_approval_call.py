import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

MOCK_API_ROOT = Path(__file__).resolve().parents[2] / "mock_api"
if str(MOCK_API_ROOT) not in sys.path:
    sys.path.insert(0, str(MOCK_API_ROOT))

from viseca_mock import build_connection_event
from workflow_service.approval_call import ElevenLabsApprovalCallNotifier


class CapturingHandler(BaseHTTPRequestHandler):
    request_body = None
    request_headers = None

    def log_message(self, format, *args):
        return

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        type(self).request_body = json.loads(self.rfile.read(length))
        type(self).request_headers = dict(self.headers)
        payload = json.dumps({
            "success": True,
            "message": "queued",
            "conversation_id": "conv_test",
            "callSid": "CA_test",
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class ElevenLabsApprovalCallNotifierTests(unittest.TestCase):
    def test_places_call_with_transaction_context_and_keeps_key_in_header(self):
        server = HTTPServer(("127.0.0.1", 0), CapturingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        notifier = ElevenLabsApprovalCallNotifier(
            "secret-api-key",
            "agent_test",
            "phone_test",
            "+41791234567",
            endpoint=f"http://{host}:{port}/outbound-call",
        )
        try:
            event = build_connection_event()
            notifier.notify(event, {"reason_codes": ["customer_review_required"]})
            notifier.close()

            body = CapturingHandler.request_body
            self.assertEqual(body["agent_id"], "agent_test")
            self.assertEqual(body["agent_phone_number_id"], "phone_test")
            self.assertEqual(body["to_number"], "+41791234567")
            variables = body["conversation_initiation_client_data"]["dynamic_variables"]
            self.assertEqual(variables["authorization_id"], event["authorization"]["authorization_id"])
            self.assertEqual(variables["merchant_name"], event["authorization"]["merchant"]["merchant_name"])
            self.assertEqual(CapturingHandler.request_headers["Xi-Api-Key"], "secret-api-key")
            self.assertNotIn("secret-api-key", json.dumps(body))
            self.assertEqual(notifier.snapshot()["status"], "initiated")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_rejects_non_e164_destination_number(self):
        with self.assertRaisesRegex(ValueError, "E.164"):
            ElevenLabsApprovalCallNotifier("key", "agent", "phone", "0791234567")


if __name__ == "__main__":
    unittest.main()
