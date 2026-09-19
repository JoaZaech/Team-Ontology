import unittest

from evaluation_harness import connection_check_report, replay_evaluation


class EvaluationHarnessTests(unittest.TestCase):
    def test_connection_check_replays_deterministically(self):
        report = connection_check_report(runs=10)

        self.assertEqual(report["runs"], 10)
        self.assertEqual(report["identical_runs"], 10)
        self.assertTrue(report["deterministic"])
        self.assertTrue(report["decision_signature"].startswith("sha256:"))
        self.assertEqual(report["benchmark_scope"], "pure_rulebook_evaluation")
        self.assertEqual(report["fixture"], "scenario_fixtures/connection_check.json")
        self.assertEqual(report["received_at"], "2026-09-19T10:00:00Z")
        self.assertEqual(report["policy_revision"], 1)
        self.assertTrue(report["fixture_content_hash"].startswith("sha256:"))
        self.assertTrue(report["event_hash"].startswith("sha256:"))
        self.assertTrue(report["policy_hash"].startswith("sha256:"))
        self.assertGreaterEqual(report["latency_ms"]["p99"], report["latency_ms"]["p50"])

    def test_replay_reports_a_divergent_evaluator(self):
        results = iter((
            {
                "authorization_id": "AU1",
                "recommended_decision": "approve",
                "reason_codes": [],
                "checks": [],
                "engine_version": "v1",
            },
            {
                "authorization_id": "AU1",
                "recommended_decision": "step_up",
                "reason_codes": ["customer_confirmation"],
                "checks": [],
                "engine_version": "v1",
            },
        ))

        report = replay_evaluation(lambda: next(results), runs=2)

        self.assertFalse(report["deterministic"])
        self.assertEqual(report["identical_runs"], 1)
        self.assertEqual(report["engine_version"], "v1")


if __name__ == "__main__":
    unittest.main()
