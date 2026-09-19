import json
import threading
import unittest
from contextlib import contextmanager
from http.client import HTTPConnection

from fixtures import build_connection_event
from server import RuleEngineState, build_server


@contextmanager
def running_server():
    httpd = build_server(port=0, state=RuleEngineState())
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address
        yield host, port
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


class RuleServiceHTTPTests(unittest.TestCase):
    def request(self, host, port, method, path, body=None):
        connection = HTTPConnection(host, port, timeout=5)
        try:
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            headers = {"Content-Type": "application/json"} if payload is not None else {}
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            data = response.read()
            return response.status, (json.loads(data) if data else None)
        finally:
            connection.close()

    def test_healthz(self):
        with running_server() as (host, port):
            status, body = self.request(host, port, "GET", "/healthz")
            self.assertEqual(status, 200)
            self.assertEqual(body["status"], "ok")

    def test_evaluate_the_connection_check_event(self):
        with running_server() as (host, port):
            event = build_connection_event()
            status, body = self.request(host, port, "POST", "/v1/rules/evaluate", {"event": event})
            self.assertEqual(status, 200)
            self.assertEqual(body["evaluation"]["recommended_decision"], "approve")
            self.assertIn("policy_snapshot", body)

    def test_guard_endpoint_enforces_the_supplied_limit(self):
        with running_server() as (host, port):
            event = build_connection_event()
            status, body = self.request(host, port, "POST", "/v1/rules/guard", {
                "event": event,
                "policy": {"max_purchase_chf": "1.00", "require_familiar_merchant": True},
            })
            self.assertEqual(status, 200)
            self.assertEqual(body["decision"], "decline")
            self.assertIn("purchase_limit_exceeded", body["reason_codes"])

    def test_policy_read_update_and_conflict(self):
        with running_server() as (host, port):
            status, policy = self.request(host, port, "GET", "/v1/rules/policy")
            self.assertEqual(status, 200)

            status, updated = self.request(host, port, "PATCH", "/v1/rules/policy", {
                "policyId": policy["policyId"],
                "expectedRevision": policy["revision"],
                "patch": {"dailySpendingLimitChf": 42},
            })
            self.assertEqual(status, 200)
            self.assertEqual(updated["dailySpendingLimitChf"], 42)

            status, conflict = self.request(host, port, "PATCH", "/v1/rules/policy", {
                "policyId": policy["policyId"],
                "expectedRevision": policy["revision"],
                "patch": {"dailySpendingLimitChf": 99},
            })
            self.assertEqual(status, 409)


if __name__ == "__main__":
    unittest.main()
