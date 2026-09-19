import json
import re
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from guardian import GuardPolicy, MerchantHistory, evaluate_guard
from testing_support import check_named
from viseca_mock import DIST_DIR, MOCK_AUTHORIZATION_ID, MockVisecaState, build_connection_event


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
        self.assertEqual(
            check_named(guard, "merchant_trust")["evidence"]["prior_approved_purchases"], 26)

    def test_one_delivery_then_decision(self):
        state = MockVisecaState()
        envelope = state.next_request()
        self.assertEqual(envelope["authorization_id"], MOCK_AUTHORIZATION_ID)
        self.assertEqual(envelope["data"]["type"], "authorization.request")
        self.assertEqual(state.evaluate()["recommended_decision"], "approve")
        self.assertIsNone(state.next_request())
        body = {"authorization_id": MOCK_AUTHORIZATION_ID, "decision": "approve",
                "reason_codes": []}
        self.assertEqual(state.record_decision(MOCK_AUTHORIZATION_ID, body)["status"],
                         "recorded")
        self.assertEqual(state.record_decision(MOCK_AUTHORIZATION_ID, body)["status"],
                         "already_recorded")
        state.reset()
        self.assertIsNone(state.decision)
        self.assertIsNotNone(state.next_request())

    def test_policy_result_cannot_be_overridden_by_the_client(self):
        state = MockVisecaState()
        policy = state.policy_store.get()
        state.policy_store.update({
            "policyId": policy["policyId"],
            "expectedRevision": policy["revision"],
            "patch": {"dailySpendingLimitChf": 10},
        })
        state.next_request()
        evaluation = state.evaluate()
        self.assertEqual(evaluation["recommended_decision"], "decline")
        with self.assertRaisesRegex(ValueError, "decision_does_not_match_policy"):
            state.record_decision(MOCK_AUTHORIZATION_ID, {
                "authorization_id": MOCK_AUTHORIZATION_ID,
                "decision": "approve",
                "reason_codes": [],
            })
        with self.assertRaisesRegex(ValueError, "reason_codes_do_not_match_policy"):
            state.record_decision(MOCK_AUTHORIZATION_ID, {
                "authorization_id": MOCK_AUTHORIZATION_ID,
                "decision": "decline",
                "reason_codes": ["client_invented_reason"],
            })
        result = state.record_decision(MOCK_AUTHORIZATION_ID, {
            "authorization_id": MOCK_AUTHORIZATION_ID,
            "decision": "decline",
            "reason_codes": evaluation["reason_codes"],
        })
        self.assertEqual(result["decision"], "decline")

    def test_step_up_requires_a_customer_resolution(self):
        state = MockVisecaState()
        policy = state.policy_store.get()
        state.policy_store.update({
            "policyId": policy["policyId"],
            "expectedRevision": policy["revision"],
            "patch": {"reviewTriggers": ["online_purchase"]},
        })
        state.next_request()
        evaluation = state.evaluate()
        self.assertEqual(evaluation["recommended_decision"], "step_up")
        recorded = state.record_decision(MOCK_AUTHORIZATION_ID, {
            "authorization_id": MOCK_AUTHORIZATION_ID,
            "decision": "step_up",
            "reason_codes": evaluation["reason_codes"],
        })
        self.assertEqual(recorded["decision"], "step_up")
        resolved = state.resolve_decision(MOCK_AUTHORIZATION_ID, {
            "authorization_id": MOCK_AUTHORIZATION_ID,
            "decision": "approve",
        })
        self.assertEqual(resolved["status"], "resolved")

    def test_root_page_serves_the_built_decision_lab_app(self):
        # The built UI is served by this mock and calls its request, evaluation,
        # and policy endpoints rather than embedding a copied decision result.
        index_path = DIST_DIR / "index.html"
        if not index_path.is_file():
            self.skipTest("Run 'npm run build' in live_layer/decision-lab first.")
        index_html = index_path.read_text(encoding="utf-8")
        self.assertIn("Viseca Decision Lab", index_html)
        script_names = re.findall(r'src="(/assets/[^"]+\.js)"', index_html)
        self.assertTrue(script_names, "expected a built module script reference in dist/index.html")
        bundle = (DIST_DIR / script_names[0].lstrip("/")).read_text(encoding="utf-8")
        self.assertIn("/v1/decision-requests/next?wait=0", bundle)
        self.assertIn("/mock/evaluate", bundle)
        self.assertIn("/mock/policy", bundle)
        self.assertIn("/resolve", bundle)


if __name__ == "__main__":
    unittest.main()
