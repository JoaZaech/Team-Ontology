import unittest
from copy import deepcopy
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from fixtures import DATA_DIR, build_connection_event
from guardian import MerchantHistory
from rulebook import evaluate_request
from testing_support import check_named
from wallet_policy import (
    PolicyConflictError,
    PolicyIntegrityError,
    PolicyValidationError,
    SQLiteWalletPolicyStore,
    WalletPolicyStore,
    default_wallet_policy_document,
)


class WalletPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = MerchantHistory.from_data_dir(DATA_DIR)

    def test_default_dynamic_policy_allows_connection_check(self):
        result = evaluate_request(
            build_connection_event(),
            self.history,
            wallet_policy=default_wallet_policy_document(),
        )

        self.assertEqual(result["recommended_decision"], "approve")
        self.assertEqual(result["reason_codes"], [])
        self.assertEqual(result["engine_version"], "viseca-mock-rulebook-v2")
        self.assertEqual(
            check_named(result, "Category maximum")["reason_code"],
            "category_limit_within_limit",
        )

    def test_category_maximum_declines_purchase(self):
        policy = default_wallet_policy_document()
        policy["adaptiveSpendProfiles"]["Groceries"]["maximumChf"] = 19.99

        result = evaluate_request(
            build_connection_event(), self.history, wallet_policy=policy
        )

        self.assertEqual(result["recommended_decision"], "decline")
        category_check = check_named(result, "Category maximum")
        self.assertEqual(category_check["outcome"], "fail")
        self.assertEqual(category_check["reason_code"], "category_limit_exceeded")

    def test_online_purchase_trigger_steps_up(self):
        policy = default_wallet_policy_document()
        policy["reviewTriggers"] = ["new_merchant", "online_purchase"]

        result = evaluate_request(
            build_connection_event(), self.history, wallet_policy=policy
        )

        self.assertEqual(result["recommended_decision"], "step_up")
        online_check = check_named(result, "Online purchase review")
        self.assertEqual(online_check["outcome"], "review")
        self.assertEqual(
            online_check["reason_code"], "online_purchase_confirmation_required"
        )

    def test_stale_policy_revision_is_rejected(self):
        store = WalletPolicyStore()
        policy = store.get()
        request = {
            "policyId": policy["policyId"],
            "expectedRevision": policy["revision"],
            "patch": {"dailySpendingLimitChf": 1400},
        }
        updated = store.update(request)

        self.assertEqual(updated["revision"], 2)
        stale_request = deepcopy(request)
        stale_request["patch"] = {"dailySpendingLimitChf": 1300}
        with self.assertRaises(PolicyConflictError):
            store.update(stale_request)

    def test_sqlite_store_persists_revisions_and_detects_tampering(self):
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "rules.sqlite3"
            store = SQLiteWalletPolicyStore(database_path)
            policy = store.get()
            updated = store.update({
                "policyId": policy["policyId"],
                "expectedRevision": policy["revision"],
                "patch": {"dailySpendingLimitChf": 1400},
            })
            self.assertEqual(updated["revision"], 2)
            self.assertEqual(len(store.revisions(policy["policyId"])), 2)
            self.assertEqual(database_path.stat().st_mode & 0o777, 0o600)
            store.close()

            reopened = SQLiteWalletPolicyStore(database_path)
            self.assertEqual(reopened.get()["revision"], 2)
            reopened.close()

            connection = sqlite3.connect(database_path)
            connection.execute("UPDATE policies SET document_json = '{}' ")
            connection.commit()
            connection.close()

            tampered = SQLiteWalletPolicyStore(database_path)
            with self.assertRaises(PolicyIntegrityError):
                tampered.get()
            tampered.close()

    def test_sqlite_store_rejects_revision_chain_and_card_binding_tampering(self):
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "rules.sqlite3"
            store = SQLiteWalletPolicyStore(database_path)
            policy = store.get()
            store.update({
                "policyId": policy["policyId"],
                "expectedRevision": policy["revision"],
                "patch": {"dailySpendingLimitChf": 1400},
            })
            store.close()

            connection = sqlite3.connect(database_path)
            connection.execute(
                "UPDATE policy_revisions SET previous_digest = 'sha256:forged' WHERE revision = 2"
            )
            connection.commit()
            connection.close()

            tampered = SQLiteWalletPolicyStore(database_path)
            with self.assertRaises(PolicyIntegrityError):
                tampered.get()
            tampered.close()

            connection = sqlite3.connect(database_path)
            previous_digest = connection.execute(
                "SELECT document_digest FROM policy_revisions WHERE revision = 1"
            ).fetchone()[0]
            connection.execute(
                "UPDATE policy_revisions SET previous_digest = ? WHERE revision = 2",
                (previous_digest,),
            )
            connection.execute("UPDATE policies SET card_id = 'CA9999'")
            connection.commit()
            connection.close()

            rebound = SQLiteWalletPolicyStore(database_path)
            with self.assertRaises(PolicyIntegrityError):
                rebound.get()
            rebound.close()

    def test_sqlite_store_owns_creation_audit_fields_and_requires_revision_one(self):
        with TemporaryDirectory() as directory:
            store = SQLiteWalletPolicyStore(Path(directory) / "rules.sqlite3")
            policy = default_wallet_policy_document()
            policy["policyId"] = "wallet-policy_CA0002_default"
            policy["subject"] = {"customerId": "CU0002", "cardId": "CA0002"}
            policy["updatedBy"] = "forged-user"
            created = store.create(policy)
            self.assertEqual(created["updatedBy"], "policy-api")

            policy["policyId"] = "wallet-policy_CA0003_default"
            policy["subject"] = {"customerId": "CU0003", "cardId": "CA0003"}
            policy["revision"] = 2
            with self.assertRaises(PolicyValidationError):
                store.create(policy)
            store.close()

    def test_sqlite_store_persists_graph_derived_policy_provenance(self):
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "rules.sqlite3"
            store = SQLiteWalletPolicyStore(database_path)
            policy = store.get()
            self.assertEqual(policy["updatedBy"], "policy-api")
            self.assertEqual(policy["knowledgeGraph"]["graphVersion"], "kg-v1")
            self.assertTrue(policy["knowledgeGraph"]["evidenceIds"])
            store.close()

            reopened = SQLiteWalletPolicyStore(database_path)
            persisted = reopened.get()
            self.assertEqual(persisted["knowledgeGraph"], policy["knowledgeGraph"])
            generated = reopened.create_from_knowledge_graph("CA0002")
            self.assertEqual(generated["subject"]["cardId"], "CA0002")
            self.assertEqual(generated["knowledgeGraph"]["graphVersion"], "kg-v1")
            reopened.close()

    def test_sqlite_store_migrates_only_the_untouched_legacy_default(self):
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "rules.sqlite3"
            legacy = default_wallet_policy_document()
            legacy.pop("knowledgeGraph")
            store = SQLiteWalletPolicyStore(database_path, initial=legacy)
            self.assertNotIn("knowledgeGraph", store.get())
            store.close()

            migrated = SQLiteWalletPolicyStore(database_path)
            self.assertEqual(migrated.get()["knowledgeGraph"]["graphVersion"], "kg-v1")
            migrated.close()


if __name__ == "__main__":
    unittest.main()
