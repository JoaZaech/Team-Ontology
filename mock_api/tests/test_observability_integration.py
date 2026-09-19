import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from decision_receipts import DecisionReceiptLedger
from mock_api import MockAgentService
from observability import Telemetry
from rule_client import RuleServiceClient
from rule_service_fixture import running_rule_service
from viseca_mock import MOCK_AUTHORIZATION_ID, MockVisecaState


class ObservabilityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = DecisionReceiptLedger(Path(self.directory.name) / "receipts.sqlite3")
        self.telemetry = Telemetry(secret="integration-test-secret")
        self._rule_service = running_rule_service()
        base_url = self._rule_service.__enter__()
        self.addCleanup(self._rule_service.__exit__, None, None, None)
        self.rule_client = RuleServiceClient(base_url)

    def tearDown(self):
        self.ledger.close()
        self.directory.cleanup()

    def test_viseca_flow_records_a_replayable_resolution_chain(self):
        policy = self.rule_client.get_policy()
        self.rule_client.update_policy({
            "policyId": policy["policyId"],
            "expectedRevision": policy["revision"],
            "patch": {"reviewTriggers": ["online_purchase"]},
        })
        state = MockVisecaState(receipt_ledger=self.ledger, telemetry=self.telemetry, rule_client=self.rule_client)
        received_at = datetime.now(timezone.utc)
        try:
            state.next_request(now=received_at)
            evaluation = state.evaluate()
            recorded = state.record_decision(
                MOCK_AUTHORIZATION_ID,
                {
                    "authorization_id": MOCK_AUTHORIZATION_ID,
                    "decision": "step_up",
                    "reason_codes": evaluation["reason_codes"],
                },
                now=received_at + timedelta(seconds=1),
            )
            resolved = state.resolve_decision(
                MOCK_AUTHORIZATION_ID,
                {
                    "authorization_id": MOCK_AUTHORIZATION_ID,
                    "decision": "approve",
                },
                now=received_at + timedelta(seconds=2),
            )
            receipts = list(self.ledger.iter_receipts())
            self.assertEqual(evaluation["recommended_decision"], "step_up")
            self.assertEqual([receipt["decision"] for receipt in receipts], ["step_up", "step_up", "approve"])
            self.assertEqual(receipts[-1]["final_resolution"]["spend_effect"], "approved")
            self.assertEqual(recorded["decision_receipt_hash"], receipts[1]["receipt_hash"])
            self.assertEqual(resolved["decision_receipt_hash"], receipts[2]["receipt_hash"])
            self.ledger.verify_chain()
            telemetry_text = json.dumps(self.telemetry.snapshot())
            self.assertNotIn("CA0001", telemetry_text)
            self.assertNotIn("CU0001", telemetry_text)
            self.assertIn("decision.resolved", telemetry_text)
        finally:
            state.close()

    def test_deadline_rejection_is_observable_and_does_not_record_a_submission(self):
        state = MockVisecaState(receipt_ledger=self.ledger, telemetry=self.telemetry, rule_client=self.rule_client)
        received_at = datetime.now(timezone.utc)
        try:
            state.next_request(now=received_at)
            with self.assertRaisesRegex(ValueError, "decision_deadline_exceeded"):
                state.record_decision(
                    MOCK_AUTHORIZATION_ID,
                    {"authorization_id": MOCK_AUTHORIZATION_ID, "decision": "approve"},
                    now=received_at + timedelta(seconds=9),
                )
            receipts = list(self.ledger.iter_receipts())
            self.assertEqual([receipt["decision"] for receipt in receipts], ["approve"])
            self.assertIsNone(state.decision)
            names = [event["name"] for event in self.telemetry.snapshot()["events"]]
            self.assertIn("decision.deadline_missed", names)
        finally:
            state.close()

    def test_mock_agent_emits_a_redacted_receipt_and_reuses_it_on_retry(self):
        service = MockAgentService(receipt_ledger=self.ledger, telemetry=self.telemetry, rule_client=self.rule_client)
        body = {
            "request_id": "obs-request-1",
            "buyer": {"card_id": "CA0001", "mandate_id": "TM_DEMO_GROCERY"},
            "merchant_id": "ME0001",
            "order": {
                "billing_amount_chf": "20.00",
                "delivery_fee_chf": "0.00",
                "items": [{"item_id": "IT0001", "quantity": 1, "unit_price_chf": "20.00"}],
            },
        }
        try:
            first = service.evaluate(body, now=1000)
            replay = service.evaluate(body, now=1001)
            receipts = list(self.ledger.iter_receipts())
            self.assertEqual(first, replay)
            self.assertEqual(len(receipts), 1)
            self.assertEqual(first["decision_receipt_hash"], receipts[0]["receipt_hash"])
            telemetry_text = json.dumps(self.telemetry.snapshot())
            self.assertNotIn("CA0001", telemetry_text)
            self.assertNotIn("TM_DEMO_GROCERY", telemetry_text)
            self.assertIn("decision.recorded", telemetry_text)
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
