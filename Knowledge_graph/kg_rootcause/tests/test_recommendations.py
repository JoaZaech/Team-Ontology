import math
from pathlib import Path
import unittest

from kg_rootcause.ingestion import load_dataset
from kg_rootcause.precompute import EvidenceIndex
from kg_rootcause.recommendations import build_policy_recommendations


DATA = Path(__file__).resolve().parents[3] / "viseca-2026" / "data"


class PolicyRecommendationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dataset, _ = load_dataset(DATA)
        cls.history = EvidenceIndex(dataset).by_card

    def test_category_draft_uses_only_approved_purchase_evidence(self):
        recommendations = build_policy_recommendations(self.history)
        grocery = next(
            recommendation
            for recommendation in recommendations["by_card"]["CA0001"]
            if recommendation["profile_category"] == "Groceries"
        )
        rows = [
            row for row in self.history["CA0001"]
            if row["transaction_type"] == "purchase" and row["merchant_category"] == "groceries"
        ]
        approved_rows = [row for row in rows if row["status"] == "approved"]
        declined_rows = [row for row in rows if row["status"] == "declined"]
        p95 = sorted(row["billing_amount_chf"] for row in approved_rows)[math.ceil(len(approved_rows) * 0.95) - 1]

        self.assertEqual(grocery["evidence"]["approved_purchase_count"], len(approved_rows))
        self.assertEqual(grocery["evidence"]["declined_purchase_count"], len(declined_rows))
        self.assertEqual(grocery["profile"]["maximumChf"], math.ceil(p95 / 500) * 5)
        self.assertEqual(
            set(grocery["evidence"]["supporting_event_ids"]),
            {row["authorization_id"] for row in approved_rows},
        )
        self.assertTrue(
            set(grocery["evidence"]["supporting_event_ids"]).isdisjoint(
                {row["authorization_id"] for row in declined_rows}
            )
        )
        self.assertTrue(grocery["requires_customer_confirmation"])

    def test_recommendations_are_deterministic(self):
        self.assertEqual(
            build_policy_recommendations(self.history),
            build_policy_recommendations(self.history),
        )


if __name__ == "__main__":
    unittest.main()