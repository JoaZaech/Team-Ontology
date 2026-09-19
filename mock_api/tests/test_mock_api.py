import json
import unittest
from copy import deepcopy
from pathlib import Path

from mock_api import MockAgentService, RequestError
from rule_client import RuleServiceClient
from rule_service_fixture import running_rule_service


SAMPLE = Path(__file__).parents[1] / "mock_request.json"


class MockAgentServiceTests(unittest.TestCase):
    def setUp(self):
        self._rule_service = running_rule_service()
        base_url = self._rule_service.__enter__()
        self.addCleanup(self._rule_service.__exit__, None, None, None)
        self.service = MockAgentService(rule_client=RuleServiceClient(base_url))
        self.body = json.loads(SAMPLE.read_text())

    def test_sample_request_and_safe_retry(self):
        first = self.service.evaluate(self.body, now=1000)
        again = self.service.evaluate(self.body, now=1001)
        self.assertEqual(first, again)
        self.assertEqual(first["guard"]["decision"], "approve")
        self.assertFalse(first["payment_authorized"])
        self.assertEqual(len(self.service.attempts["CA0001", "ME0001"]), 1)

    def test_rate_check_is_derived_by_server(self):
        for index in range(3):
            body = deepcopy(self.body)
            body["request_id"] = f"attempt-{index}"
            self.assertEqual(self.service.evaluate(body, now=1000 + index)
                             ["guard"]["decision"], "approve")
        body = deepcopy(self.body)
        body["request_id"] = "attempt-3"
        result = self.service.evaluate(body, now=1003)
        self.assertEqual(result["guard"]["decision"], "step_up")
        self.assertIn("attempt_velocity_high", result["guard"]["reason_codes"])

    def test_untrusted_policy_and_mismatched_total_are_rejected(self):
        changed = deepcopy(self.body)
        changed["buyer"]["card_id"] = "CA0002"
        with self.assertRaises(RequestError) as error:
            self.service.evaluate(changed)
        self.assertEqual(error.exception.status, 403)

        changed = deepcopy(self.body)
        changed["order"]["billing_amount_chf"] = "19.00"
        with self.assertRaises(RequestError) as error:
            self.service.evaluate(changed)
        self.assertEqual(error.exception.code, "order_total_mismatch")

    def test_request_id_cannot_change_order(self):
        self.service.evaluate(self.body, now=1000)
        changed = deepcopy(self.body)
        changed["merchant_id"] = "ME0002"
        with self.assertRaises(RequestError) as error:
            self.service.evaluate(changed, now=1001)
        self.assertEqual(error.exception.status, 409)


if __name__ == "__main__":
    unittest.main()
