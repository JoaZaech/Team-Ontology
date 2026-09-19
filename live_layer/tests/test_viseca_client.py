import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from viseca_client import VisecaAPIError, VisecaClient


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class VisecaClientTests(unittest.TestCase):
    def test_health_uses_no_key(self):
        with patch("viseca_client.urlopen", return_value=FakeResponse({"ok": True})) as call:
            result = VisecaClient("https://example.test").health()
        self.assertEqual(result, {"ok": True})
        self.assertNotIn("Authorization", call.call_args.args[0].headers)

    def test_bootstrap_uses_bearer_key(self):
        with patch("viseca_client.urlopen", return_value=FakeResponse({"version": "test"})) as call:
            result = VisecaClient("https://example.test", "secret").bootstrap()
        self.assertEqual(result["version"], "test")
        self.assertEqual(call.call_args.args[0].get_header("Authorization"), "Bearer secret")

    def test_key_is_required_for_private_endpoint(self):
        with self.assertRaises(VisecaAPIError):
            VisecaClient("https://example.test").reference_data()

    def test_local_mock_url_is_allowed(self):
        client = VisecaClient("http://127.0.0.1:8082", "mock-team-key")
        with patch("viseca_client.urlopen", return_value=FakeResponse({"data": {}})) as call:
            client.next_request(wait_seconds=0)
        self.assertEqual(call.call_args.args[0].full_url,
                         "http://127.0.0.1:8082/v1/decision-requests/next?wait=0")

    def test_mandate_and_run_lifecycle_use_authenticated_json_requests(self):
        client = VisecaClient("https://example.test", "secret")
        responses = [
            FakeResponse({"draft_id": "DR001"}),
            FakeResponse({"mandate_id": "TM001"}),
            FakeResponse({"mandate_id": "TM001"}),
            FakeResponse({"mandate_id": "TM001"}),
            FakeResponse({"revoked": True}),
            FakeResponse({"run_id": "RUN001"}),
            FakeResponse({"status": "pending"}),
        ]
        with patch("viseca_client.urlopen", side_effect=responses) as call:
            client.create_mandate({"instruction": "Buy groceries", "hard_rules": []})
            client.confirm_mandate("DR001")
            client.mandate("TM001")
            client.update_mandate("TM001", {"uncertainty_policy": "decline"})
            client.revoke_mandate("TM001")
            client.start_run("SCEN0000", "TM001")
            client.run_status("RUN001")

        requests = [invocation.args[0] for invocation in call.call_args_list]
        self.assertEqual(
            [(request.get_method(), request.full_url) for request in requests],
            [
                ("POST", "https://example.test/v1/mandates"),
                ("POST", "https://example.test/v1/mandates/DR001/confirm"),
                ("GET", "https://example.test/v1/mandates/TM001"),
                ("PATCH", "https://example.test/v1/mandates/TM001"),
                ("DELETE", "https://example.test/v1/mandates/TM001"),
                ("POST", "https://example.test/v1/scenario-runs"),
                ("GET", "https://example.test/v1/scenario-runs/RUN001"),
            ],
        )
        self.assertEqual(json.loads(requests[1].data), {"confirmed": True})
        self.assertEqual(json.loads(requests[5].data), {"scenario_id": "SCEN0000", "mandate_id": "TM001"})
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer secret")
        self.assertEqual(requests[0].get_header("Content-type"), "application/json")

    def test_decision_and_resolution_payloads_follow_api_contract(self):
        client = VisecaClient("https://example.test", "secret")
        with patch("viseca_client.urlopen", side_effect=[FakeResponse({"status": "recorded"}), FakeResponse({"status": "resolved"})]) as call:
            client.submit_decision(
                "AU 001",
                "step_up",
                reason_codes=["customer_confirmation"],
                customer_message="Please review this purchase.",
                evidence=[{"source": "trusted_catalogue"}],
                engine_version="rulebook-v1",
            )
            client.resolve_decision("AU 001", "approve", customer_message="Confirmed")

        decision_request, resolution_request = [invocation.args[0] for invocation in call.call_args_list]
        self.assertEqual(decision_request.full_url, "https://example.test/v1/authorizations/AU%20001/decision")
        self.assertEqual(json.loads(decision_request.data)["decision"], "step_up")
        self.assertEqual(resolution_request.full_url, "https://example.test/v1/authorizations/AU%20001/resolve")
        self.assertEqual(json.loads(resolution_request.data), {"decision": "approve", "customer_message": "Confirmed"})

    def test_decision_and_wait_validation_reject_invalid_values(self):
        client = VisecaClient("https://example.test", "secret")
        with self.assertRaisesRegex(ValueError, "invalid decision"):
            client.submit_decision("AU001", "allow")
        with self.assertRaisesRegex(ValueError, "invalid decision"):
            client.resolve_decision("AU001", "step_up")
        with self.assertRaisesRegex(ValueError, "wait_seconds"):
            client.next_request(wait_seconds=26)
        with self.assertRaisesRegex(ValueError, "mandate ID"):
            client.mandate("")

    def test_remote_plain_http_is_rejected(self):
        with self.assertRaises(ValueError):
            VisecaClient("http://example.test", "secret")

    def test_http_error_does_not_echo_credentials(self):
        failure = HTTPError("https://example.test/v1/bootstrap", 401, "unauthorized", {}, io.BytesIO())
        with patch("viseca_client.urlopen", side_effect=failure):
            with self.assertRaisesRegex(VisecaAPIError, "HTTP 401") as error:
                VisecaClient("https://example.test", "secret").bootstrap()
        self.assertNotIn("secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
