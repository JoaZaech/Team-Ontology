import json
import threading
import unittest
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory

from fixtures import build_connection_event
from server import RuleEngineState, build_server
from wallet_policy import WalletPolicyStore, default_wallet_policy_document

TEST_API_TOKEN = "test-api-token-with-at-least-32-characters"


@contextmanager
def running_server():
    with TemporaryDirectory() as directory:
        httpd = build_server(
            port=0,
            state=RuleEngineState(
                policy_db_path=Path(directory) / "rules.sqlite3",
                api_token=TEST_API_TOKEN,
            ),
        )
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
    def request(self, host, port, method, path, body=None, headers=None, authenticated=True):
        connection = HTTPConnection(host, port, timeout=5)
        try:
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            request_headers = {"Content-Type": "application/json"} if payload is not None else {}
            if authenticated:
                request_headers["X-Rule-Service-Token"] = TEST_API_TOKEN
            request_headers.update(headers or {})
            connection.request(method, path, body=payload, headers=request_headers)
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

    def test_evaluation_rejects_client_supplied_policy_snapshot(self):
        with running_server() as (host, port):
            status, body = self.request(host, port, "POST", "/v1/rules/evaluate", {
                "event": build_connection_event(),
                "wallet_policy": {"enabled": False},
            })
            self.assertEqual(status, 400)
            self.assertEqual(body["error"], "untrusted_policy_snapshot")

    def test_policy_catalogue_can_add_and_audit_a_policy(self):
        with running_server() as (host, port):
            policy = default_wallet_policy_document()
            policy["policyId"] = "wallet-policy_CA0002_default"
            policy["subject"] = {"customerId": "CU0002", "cardId": "CA0002"}
            status, created = self.request(
                host, port, "POST", "/v1/rules/policies", policy,
            )
            self.assertEqual(status, 201)
            self.assertEqual(created["policyId"], policy["policyId"])

            status, catalogue = self.request(host, port, "GET", "/v1/rules/policies")
            self.assertEqual(status, 200)
            self.assertEqual(len(catalogue["policies"]), 2)

            status, audit = self.request(
                host, port, "GET", f"/v1/rules/policies/{policy['policyId']}/revisions"
            )
            self.assertEqual(status, 200)
            self.assertEqual(audit["revisions"][0]["revision"], 1)

    def test_policy_catalogue_can_create_a_graph_derived_policy(self):
        with running_server() as (host, port):
            status, policy = self.request(
                host, port, "POST", "/v1/rules/policies/from-knowledge-graph", {"cardId": "CA0002"},
            )
            self.assertEqual(status, 201)
            self.assertEqual(policy["subject"]["cardId"], "CA0002")
            self.assertEqual(policy["knowledgeGraph"]["graphVersion"], "kg-v1")
            self.assertTrue(policy["knowledgeGraph"]["evidenceIds"])

    def test_api_routes_require_a_valid_token(self):
        with running_server() as (host, port):
            status, body = self.request(host, port, "GET", "/v1/rules/policy", authenticated=False)
            self.assertEqual(status, 401)
            self.assertEqual(body["error"], "service_unauthorized")

            status, body = self.request(host, port, "PATCH", "/v1/rules/policy", {
                "policyId": "wallet-policy_CA0001_default",
                "expectedRevision": 1,
                "patch": {"dailySpendingLimitChf": 42},
            }, authenticated=False)
            self.assertEqual(status, 401)
            self.assertEqual(body["error"], "service_unauthorized")

    def test_rejects_non_json_and_non_standard_json(self):
        with running_server() as (host, port):
            connection = HTTPConnection(host, port, timeout=5)
            try:
                connection.request(
                    "POST", "/v1/rules/guard", body=b'{"event": NaN}',
                    headers={
                        "Content-Type": "application/json",
                        "X-Rule-Service-Token": TEST_API_TOKEN,
                    },
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
            finally:
                connection.close()

            status, _ = self.request(
                host, port, "POST", "/v1/rules/guard", {"event": {}, "policy": {}},
                {"Content-Type": "text/plain"},
            )
            self.assertEqual(status, 400)

    def test_refuses_non_loopback_bind(self):
        with self.assertRaises(ValueError):
            build_server(
                "0.0.0.0", 0,
                RuleEngineState(
                    policy_store=WalletPolicyStore(),
                    api_token=TEST_API_TOKEN,
                ),
            )


if __name__ == "__main__":
    unittest.main()
