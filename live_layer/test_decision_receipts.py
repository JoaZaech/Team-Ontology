import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from decision_receipts import (
    DecisionReceiptLedger,
    IdempotencyConflictError,
    InvalidReceiptError,
    ReceiptIntegrityError,
    canonical_json,
)


class DecisionReceiptLedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "receipts.sqlite3"
        self.ledger = DecisionReceiptLedger(
            self.path,
            clock=lambda: datetime(2026, 9, 19, 8, 30, tzinfo=timezone.utc),
        )

    def tearDown(self):
        self.ledger.close()
        self.directory.cleanup()

    def append(self, **changes):
        fields = {
            "authorization_id": "AU0001",
            "idempotency_key": "REQ0001",
            "decision": "step_up",
            "policy_hash": "sha256:policy-snapshot",
            "policy_version": 3,
            "engine_version": "guardian-v1",
            "reason_codes": ("merchant_unfamiliar",),
            "checks": ({"name": "merchant", "outcome": "review"},),
            "evidence_refs": ({"source": "catalogue", "ref": "merchant:ME0001"},),
            "run_id": "RUN0001",
            "request_id": "REQ0001",
            "received_at": "2026-09-19T08:29:58Z",
            "evaluated_at": "2026-09-19T08:29:59Z",
            "deadline_at": "2026-09-19T08:30:06Z",
            "deadline_remaining_ms": 7000,
            "final_resolution": None,
        }
        fields.update(changes)
        return self.ledger.append(**fields)

    def test_canonical_json_sorts_object_keys_and_rejects_nonfinite_numbers(self):
        self.assertEqual(canonical_json({"b": [2, 1], "a": "ü"}), '{"a":"ü","b":[2,1]}')
        with self.assertRaises(InvalidReceiptError):
            canonical_json({"value": float("nan")})

    def test_append_returns_full_receipt_with_a_genesis_hash(self):
        record = self.append()

        self.assertEqual(record["authorization_id"], "AU0001")
        self.assertEqual(record["decision"], "step_up")
        self.assertEqual(record["policy_hash"], "sha256:policy-snapshot")
        self.assertEqual(record["policy_version"], 3)
        self.assertEqual(record["engine_version"], "guardian-v1")
        self.assertEqual(record["reason_codes"], ["merchant_unfamiliar"])
        self.assertEqual(record["deadline_remaining_ms"], 7000)
        self.assertIsNone(record["previous_receipt_hash"])
        self.assertTrue(record["receipt_hash"].startswith("sha256:"))
        self.assertEqual(record["recorded_at"], "2026-09-19T08:30:00.000000Z")
        self.assertIsNone(record["final_resolution"])

    def test_identical_canonical_submission_returns_the_original_record(self):
        first = self.append(checks=({"outcome": "review", "name": "merchant"},))
        second = self.append(checks=({"name": "merchant", "outcome": "review"},))

        self.assertEqual(second, first)
        self.assertEqual(list(self.ledger.iter_receipts()), [first])
        self.assertEqual(self.ledger.get("REQ0001"), first)

    def test_changed_submission_for_an_existing_idempotency_key_is_rejected(self):
        self.append()

        with self.assertRaisesRegex(
            IdempotencyConflictError, "different receipt content"
        ):
            self.append(decision="approve")

        self.assertEqual(len(list(self.ledger.iter_receipts())), 1)

    def test_each_new_receipt_links_to_the_preceding_receipt(self):
        first = self.append()
        second = self.append(
            authorization_id="AU0002",
            idempotency_key="REQ0002",
            request_id="REQ0002",
            decision="approve",
            reason_codes=(),
            final_resolution={
                "decision": "approve",
                "resolved_at": "2026-09-19T08:30:01Z",
                "spend_effect": "approved",
            },
        )

        self.assertEqual(second["previous_receipt_hash"], first["receipt_hash"])
        self.assertEqual(second["final_resolution"]["spend_effect"], "approved")
        self.ledger.verify_chain()

    def test_sqlite_rejects_updates_to_the_append_only_table(self):
        self.append()

        connection = sqlite3.connect(self.path)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute(
                    "UPDATE decision_receipts SET recorded_at = ? WHERE sequence = 1",
                    ("2026-09-19T09:00:00Z",),
                )
        finally:
            connection.close()

    def test_hash_verification_detects_a_bypassed_storage_mutation(self):
        self.append()

        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TRIGGER decision_receipts_no_update")
            connection.execute(
                "UPDATE decision_receipts SET receipt_hash = ? WHERE sequence = 1",
                ("sha256:tampered",),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(ReceiptIntegrityError):
            self.ledger.verify_chain()


if __name__ == "__main__":
    unittest.main()
