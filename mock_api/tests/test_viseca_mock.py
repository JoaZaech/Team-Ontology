import json
import re
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from decision_receipts import DecisionReceiptLedger
from rule_client import RuleServiceClient
from rule_service_fixture import running_rule_service
from testing_support import check_named
from viseca_mock import DIST_DIR, MOCK_AUTHORIZATION_ID, MockVisecaState, build_connection_event


DATA = Path(__file__).resolve().parents[2] / "viseca-2026" / "data"


class VisecaMockTests(unittest.TestCase):
    def make_state(self) -> MockVisecaState:
        rule_service = running_rule_service()
        base_url = rule_service.__enter__()
        self.addCleanup(rule_service.__exit__, None, None, None)
        return MockVisecaState(rule_client=RuleServiceClient(base_url))

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
        rule_service = running_rule_service()
        base_url = rule_service.__enter__()
        self.addCleanup(rule_service.__exit__, None, None, None)
        guard = RuleServiceClient(base_url).guard(event, {
            "max_purchase_chf": "20.00", "require_familiar_merchant": True,
        })
        self.assertEqual(guard["decision"], "approve")
        self.assertEqual(
            check_named(guard, "merchant_trust")["evidence"]["prior_approved_purchases"], 26)

    def test_one_delivery_then_decision(self):
        state = self.make_state()
        envelope = state.next_request()
        self.assertEqual(envelope["authorization_id"], MOCK_AUTHORIZATION_ID)
        self.assertEqual(envelope["data"]["type"], "authorization.request")
        self.assertEqual(envelope["data"]["agent_proposal"], {
            "summary": "Grocery delivery order",
            "merchant_name": "Alpine Basket",
            "items": envelope["data"]["authorization"]["items"],
            "items_subtotal_chf": 13.0,
            "delivery_fee_chf": 7.0,
            "total_chf": 20.0,
        })
        self.assertEqual(
            envelope["data"]["applied_policies"]["confirmed_mandate"]["hard_rules"][0],
            {"field": "authorization.billing_amount_chf", "operator": "<=", "value": 20,
             "currency": "CHF", "scope": "purchase"},
        )
        self.assertEqual(envelope["data"]["applied_policies"]["wallet_policy"]["daily_spending_limit_chf"], 1500)
        daily_rule = next(
            rule for rule in envelope["data"]["applied_policies"]["wallet_policy"]["rules"]
            if rule["id"] == "daily-spending-limit"
        )
        self.assertEqual(daily_rule["detail"], "Up to CHF 1500.00 per day.")
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
        state = self.make_state()
        policy = state.rule_client.get_policy()
        state.rule_client.update_policy({
            "policyId": policy["policyId"],
            "expectedRevision": policy["revision"],
            "patch": {"dailySpendingLimitChf": 10},
        })
        envelope = state.next_request()
        daily_rule = next(
            rule for rule in envelope["data"]["applied_policies"]["wallet_policy"]["rules"]
            if rule["id"] == "daily-spending-limit"
        )
        self.assertEqual(daily_rule["detail"], "Up to CHF 10.00 per day.")
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
        state = self.make_state()
        policy = state.rule_client.get_policy()
        state.rule_client.update_policy({
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

    def test_activity_projection_records_agent_proposal_and_final_resolution(self):
        state = self.make_state()
        try:
            policy = state.rule_client.get_policy()
            state.rule_client.update_policy({
                "policyId": policy["policyId"],
                "expectedRevision": policy["revision"],
                "patch": {"dailySpendingLimitChf": 1500, "reviewTriggers": ["online_purchase"]},
            })
            state.next_request()
            evaluation = state.evaluate()
            self.assertEqual(evaluation["recommended_decision"], "step_up")
            state.record_decision(MOCK_AUTHORIZATION_ID, {
                "authorization_id": MOCK_AUTHORIZATION_ID,
                "decision": "step_up",
                "reason_codes": evaluation["reason_codes"],
            })
            state.resolve_decision(MOCK_AUTHORIZATION_ID, {
                "authorization_id": MOCK_AUTHORIZATION_ID,
                "decision": "approve",
            })

            snapshot = state.activity_snapshot()
            self.assertFalse(snapshot["processing"])
            self.assertEqual(len(snapshot["transactions"]), 1)
            transaction = snapshot["transactions"][0]
            self.assertEqual(transaction["proposal_summary"], "Grocery delivery order")
            self.assertEqual(transaction["agent_decision"], "step_up")
            self.assertEqual(transaction["final_decision"], "approve")
            self.assertEqual(transaction["status"], "approved")
        finally:
            state.close()

    def test_activity_snapshot_uses_supplied_projection_and_receipt_ledger(self):
        ledger = DecisionReceiptLedger(":memory:")
        projection = Mock()
        projection.snapshot.return_value = {
            "updated_at": "2026-09-19T12:00:00Z",
            "processing": False,
            "transactions": [],
        }
        state = MockVisecaState(
            rule_client=Mock(),
            receipt_ledger=ledger,
            activity_projection=projection,
        )
        try:
            snapshot = state.activity_snapshot()
            self.assertEqual(snapshot["transactions"], [])
            self.assertEqual(snapshot["flywheel"], ledger.outbox_status())
            projection.snapshot.assert_called_once_with()
        finally:
            state.close()

    def test_precomputed_recommendations_are_hidden_after_matching_policy_is_saved(self):
        recommendation = {
            "recommendation_id": "category-maximum-groceries",
            "profile_category": "Groceries",
            "profile": {
                "maximumChf": 130.0,
                "typicalRange": "CHF 60.00-CHF 129.00",
                "explanation": "Based on approved graph evidence.",
            },
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "policy_recommendations.json"
            path.write_text(json.dumps({
                "recommendation_version": "policy-recommendation-v1",
                "generated_from": {"artifact": "historical_evidence_index.json"},
                "by_card": {"CA0001": [recommendation]},
            }))
            policy = {
                "subject": {"customerId": "CU0001", "cardId": "CA0001"},
                "adaptiveSpendProfiles": {"Groceries": {"maximumChf": 180.0}},
            }
            rule_client = Mock()
            rule_client.get_policy.side_effect = lambda: deepcopy(policy)
            state = MockVisecaState(rule_client=rule_client, policy_recommendations_path=path)
            self.assertEqual(state.policy_recommendations()["recommendations"], [recommendation])
            policy["adaptiveSpendProfiles"]["Groceries"] = recommendation["profile"]
            self.assertEqual(state.policy_recommendations()["recommendations"], [])

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
