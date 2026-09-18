import unittest
from copy import deepcopy

from guardian import MerchantHistory
from rulebook import evaluate_request
from viseca_mock import DATA_DIR, build_connection_event


class RulebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = MerchantHistory.from_data_dir(DATA_DIR)

    def test_connection_check_recommends_approval_with_evidence(self):
        result = evaluate_request(build_connection_event(), self.history)
        self.assertEqual(result["recommended_decision"], "approve")
        self.assertTrue(all(check["outcome"] == "pass" for check in result["checks"]))
        self.assertEqual(len(result["checks"]), 6)

    def test_wrong_item_is_declined(self):
        event = deepcopy(build_connection_event())
        event["authorization"]["items"][0]["item_category"] = "electronics"
        result = evaluate_request(event, self.history)
        self.assertEqual(result["recommended_decision"], "decline")
        self.assertIn("basket_outside_instruction", result["reason_codes"])

    def test_price_above_mandate_is_declined(self):
        event = deepcopy(build_connection_event())
        event["authorization"]["billing_amount_chf"] = 21.0
        event["authorization"]["delivery_fee"] = 8.0
        result = evaluate_request(event, self.history)
        self.assertEqual(result["recommended_decision"], "decline")
        self.assertIn("purchase_limit_exceeded", result["reason_codes"])


if __name__ == "__main__":
    unittest.main()
