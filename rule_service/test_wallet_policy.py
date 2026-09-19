import unittest
from copy import deepcopy

from fixtures import DATA_DIR, build_connection_event
from guardian import MerchantHistory
from rulebook import evaluate_request
from testing_support import check_named
from wallet_policy import (
    PolicyConflictError,
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


if __name__ == "__main__":
    unittest.main()
