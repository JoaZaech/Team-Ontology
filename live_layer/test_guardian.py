import json
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from guardian import GuardPolicy, MerchantHistory, evaluate_guard
from testing_support import outcomes_by_name


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "viseca-2026" / "data"


class GuardianTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = MerchantHistory.from_data_dir(DATA)
        cls.example = json.loads(
            (DATA / "scenario_fixtures" / "example_authorization_request.json").read_text()
        )

    def event(self):
        event = deepcopy(self.example)
        event["authorization"]["merchant"] = {
            key: self.history.merchants["ME0001"][key]
            for key in ("merchant_id", "merchant_name", "merchant_category",
                        "merchant_mcc", "merchant_country", "merchant_city",
                        "availability", "recurring_capable")
        }
        return event

    def test_three_checks_pass_for_known_merchant(self):
        result = evaluate_guard(self.event(), self.history,
                                GuardPolicy(max_purchase_chf=Decimal("20")))
        self.assertEqual(result["decision"], "approve")
        self.assertEqual(outcomes_by_name(result),
                         {"spend_cap": "pass", "merchant_trust": "pass",
                          "rate_anomaly": "pass"})

    def test_hard_spend_cap_declines(self):
        result = evaluate_guard(self.event(), self.history,
                                GuardPolicy(max_purchase_chf=Decimal("19.99")))
        self.assertEqual(result["decision"], "decline")
        self.assertIn("purchase_limit_exceeded", result["reason_codes"])

    def test_unfamiliar_merchant_steps_up_when_required(self):
        result = evaluate_guard(self.event(), self.history,
                                GuardPolicy(max_purchase_chf=Decimal("20"),
                                            require_familiar_merchant=True))
        self.assertEqual(result["decision"], "step_up")
        self.assertIn("merchant_unfamiliar_to_card", result["reason_codes"])

    def test_high_velocity_steps_up_without_false_spend_debit(self):
        event = self.event()
        event["authorization"]["recent_attempt_count_10m"] = 3
        policy = GuardPolicy(max_purchase_chf=Decimal("20"))
        first = evaluate_guard(event, self.history, policy)
        second = evaluate_guard(event, self.history, policy)
        self.assertEqual(first, second)
        self.assertEqual(first["decision"], "step_up")

    def test_period_cap_needs_explicit_current_spend(self):
        policy = GuardPolicy(max_purchase_chf=Decimal("20"),
                             max_period_chf=Decimal("300"))
        result = evaluate_guard(self.event(), self.history, policy)
        self.assertEqual(result["decision"], "step_up")
        self.assertIn("period_spend_unavailable", result["reason_codes"])
        result = evaluate_guard(self.event(), self.history,
                                GuardPolicy(max_purchase_chf=Decimal("20"),
                                            max_period_chf=Decimal("300"),
                                            approved_spend_in_period_chf=Decimal("290")))
        self.assertEqual(result["decision"], "decline")


if __name__ == "__main__":
    unittest.main()
