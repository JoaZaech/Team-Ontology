import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from guardian import GuardPolicy, MerchantHistory, evaluate_guard
from viseca_mock import DEMO_PAGE, MOCK_AUTHORIZATION_ID, MockVisecaState, build_connection_event


DATA = Path(__file__).resolve().parents[1] / "viseca-2026" / "data"


class VisecaMockTests(unittest.TestCase):
    def test_connection_request_matches_supplied_event_contract(self):
        event = build_connection_event(
            now=datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
        )
        schema = json.loads((DATA / "schemas" / "authorization_event.schema.json").read_text())
        for field in schema["required"]:
            self.assertIn(field, event)
        for field in schema["properties"]["authorization"]["required"]:
            self.assertIn(field, event["authorization"])
        for field in schema["properties"]["mandate"]["required"]:
            self.assertIn(field, event["mandate"])
        for field in schema["properties"]["context"]["required"]:
            self.assertIn(field, event["context"])
        for field in schema["properties"]["runtime"]["required"]:
            self.assertIn(field, event["runtime"])
        self.assertEqual(event["authorization"]["source_authorization_id"], "AU0001")
        self.assertEqual(event["authorization"]["merchant"]["merchant_id"], "ME0001")
        self.assertEqual(event["authorization"]["card_id"], "CA0001")
        self.assertEqual(event["authorization"]["billing_amount_chf"], 20.0)
        self.assertEqual(event["deadline_at"], "2026-09-19T12:00:08Z")
        guard = evaluate_guard(event, MerchantHistory.from_data_dir(DATA), GuardPolicy(
            max_purchase_chf=Decimal("20.00"), require_familiar_merchant=True
        ))
        self.assertEqual(guard["decision"], "approve")
        self.assertEqual(guard["checks"][1]["evidence"]["prior_approved_purchases"], 26)

    def test_one_delivery_then_decision(self):
        state = MockVisecaState()
        envelope = state.next_request()
        self.assertEqual(envelope["authorization_id"], MOCK_AUTHORIZATION_ID)
        self.assertEqual(envelope["data"]["type"], "authorization.request")
        self.assertIsNone(state.next_request())
        body = {"authorization_id": MOCK_AUTHORIZATION_ID, "decision": "step_up",
                "reason_codes": ["customer_confirmation"]}
        self.assertEqual(state.record_decision(MOCK_AUTHORIZATION_ID, body)["status"],
                         "recorded")
        self.assertEqual(state.record_decision(MOCK_AUTHORIZATION_ID, body)["status"],
                         "already_recorded")
        state.reset()
        self.assertIsNone(state.decision)
        self.assertIsNotNone(state.next_request())

    def test_root_page_explains_the_local_demo(self):
        self.assertIn("Viseca purchase request rehearsal", DEMO_PAGE)
        self.assertIn("/v1/decision-requests/next?wait=0", DEMO_PAGE)
        self.assertIn("/mock/reset", DEMO_PAGE)


if __name__ == "__main__":
    unittest.main()
