import unittest
from datetime import datetime, timezone

from viseca_benchmark import BenchmarkDataError, VisecaBenchmark


def policy_for(scenario_id, customer_id, card_id):
    return {
        "policyId": f"benchmark-policy_{scenario_id}",
        "scenarioId": scenario_id,
        "subject": {"customerId": customer_id, "cardId": card_id},
        "mandate": {
            "mandateId": f"TM_BENCHMARK_{scenario_id}",
            "profileId": f"PROFILE_BENCHMARK_{scenario_id}",
            "instruction": "Customer-confirmed benchmark policy.",
            "hardRules": [],
            "uncertaintyPolicy": "ask",
        },
    }


class VisecaBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.benchmark = VisecaBenchmark()

    def test_flattened_benchmark_matches_all_canonical_source_attempts(self):
        counts = {
            scenario_id: len(self.benchmark.attempts(scenario_id))
            for scenario_id in self.benchmark.scenario_ids()
        }
        self.assertEqual(counts, {
            "SCEN0000": 1,
            "SCEN0001": 10,
            "SCEN0002": 12,
            "SCEN0003": 11,
            "SCEN0004": 11,
        })
        self.assertEqual(sum(counts.values()), 45)
        self.assertEqual(len(self.benchmark.flattened_rows_by_source_id), 45)

    def test_event_builder_uses_trusted_catalogue_facts_and_policy_binding(self):
        policy = policy_for("SCEN0001", "CU0001", "CA0001")
        binding = self.benchmark.binding_for_scenario("SCEN0001", policy)
        event = self.benchmark.build_event(
            "AU0002",
            binding,
            authorization_id="MOCK_RUN_AU0002",
            request_id="req_run_au0002",
            received_at=datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc),
        )
        authorization = event["authorization"]
        self.assertEqual(authorization["source_authorization_id"], "AU0002")
        self.assertEqual(authorization["authorization_id"], "MOCK_RUN_AU0002")
        self.assertEqual(authorization["merchant"]["merchant_id"], "ME0001")
        self.assertEqual(authorization["merchant"]["merchant_mcc"], "5411")
        self.assertEqual(authorization["items"][0]["item_id"], "IT0001")
        self.assertIsInstance(authorization["billing_amount_chf"], float)
        self.assertEqual(event["mandate"]["mandate_id"], "TM_BENCHMARK_SCEN0001")
        self.assertEqual(event["deadline_at"], "2026-09-19T12:00:08Z")
        self.assertEqual(event["runtime"]["context_basis"], "run_decisions_and_scenario_timestamps")

    def test_event_builder_preserves_run_sequence_context_and_related_live_ids(self):
        policy = policy_for("SCEN0004", "CU0019", "CA0039")
        binding = self.benchmark.binding_for_scenario("SCEN0004", policy)
        prior = [{
            "authorization_id": "MOCK_RUN_AU0037",
            "timestamp": "2026-08-12T14:05:00Z",
            "merchant_id": "ME0022",
            "billing_amount_chf": 520.0,
            "status": "declined",
        }]
        event = self.benchmark.build_event(
            "AU0042",
            binding,
            recent_authorizations=prior,
            live_authorization_ids={"AU0037": "MOCK_RUN_AU0037"},
        )
        self.assertEqual(event["authorization"]["related_authorization_id"], "MOCK_RUN_AU0037")
        self.assertEqual(event["authorization"]["related_authorization_status"], "declined")
        self.assertEqual(event["context"]["recent_authorizations"], prior)

    def test_policy_binding_rejects_a_cross_scenario_or_cross_card_policy(self):
        with self.assertRaisesRegex(BenchmarkDataError, "policy scenario"):
            self.benchmark.binding_for_scenario(
                "SCEN0001", policy_for("SCEN0004", "CU0001", "CA0001")
            )
        with self.assertRaisesRegex(BenchmarkDataError, "policy subject"):
            self.benchmark.binding_for_scenario(
                "SCEN0001", policy_for("SCEN0001", "CU0001", "CA9999")
            )


if __name__ == "__main__":
    unittest.main()
