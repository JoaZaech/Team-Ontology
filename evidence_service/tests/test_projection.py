import tempfile
import unittest
from pathlib import Path

from evidence_service.projection import EvidenceProjection


def receipt_event(event_id: str, *, authorization_id: str, effective_at: str, decision: str = "approve"):
    return {
        "event_id": event_id,
        "event_type": "decision.receipt-recorded.v1",
        "occurred_at": effective_at,
        "authorization": {
            "authorization_id": authorization_id,
            "card_id": "CA0001",
            "customer_id": "CU0001",
            "merchant_id": "ME0001",
            "merchant_category": "groceries",
            "device_id": "DV0001",
            "billing_amount_minor": 12000,
            "currency": "CHF",
            "requested_at": effective_at,
        },
        "outcome": {
            "phase": "agent_decision",
            "decision": decision,
            "effective_at": effective_at,
            "spend_eligibility": "authorization_approved" if decision == "approve" else "none",
        },
        "provenance": {
            "receipt_hash": event_id,
            "policy_version": "3",
            "engine_version": "guardian-v1",
        },
    }


class EvidenceProjectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.projection = EvidenceProjection(Path(self.directory.name) / "evidence.sqlite3")

    def tearDown(self):
        self.projection.close()
        self.directory.cleanup()

    def test_ingestion_is_idempotent_and_materializes_evidence(self):
        event = receipt_event("sha256:receipt-one", authorization_id="AU0001", effective_at="2026-09-19T09:00:00Z")

        self.assertFalse(self.projection.ingest(event)["idempotent"])
        self.assertTrue(self.projection.ingest(event)["idempotent"])

        self.assertEqual(self.projection.status()["event_count"], 1)
        resolved = self.projection.resolve({
            "authorization": {
                "card_id": "CA0001",
                "timestamp": "2026-09-19T10:00:00Z",
                "merchant": {"merchant_id": "ME0001"},
            },
        })
        self.assertEqual(resolved["summary"]["prior_attempt_count"], 1)
        self.assertEqual(resolved["summary"]["prior_approved_count"], 1)

    def test_resolver_excludes_equal_and_future_evidence(self):
        self.projection.ingest(receipt_event("sha256:earlier", authorization_id="AU0001", effective_at="2026-09-19T09:00:00Z"))
        self.projection.ingest(receipt_event("sha256:equal", authorization_id="AU0002", effective_at="2026-09-19T10:00:00Z"))
        self.projection.ingest(receipt_event("sha256:later", authorization_id="AU0003", effective_at="2026-09-19T11:00:00Z"))

        resolved = self.projection.resolve({
            "authorization": {
                "card_id": "CA0001",
                "timestamp": "2026-09-19T10:00:00Z",
                "merchant": {"merchant_id": "ME0001"},
            },
        })

        self.assertEqual(resolved["summary"]["prior_attempt_count"], 1)
        self.assertEqual(resolved["evidence_refs"], [{"source": "evidence_projection", "receipt_hash": "sha256:earlier"}])