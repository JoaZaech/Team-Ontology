import os
import unittest

from rule_client import RuleServiceClient
from rule_service_fixture import TEST_RULE_SERVICE_TOKEN, running_rule_service


class RuleServiceFixtureTests(unittest.TestCase):
    def test_fixture_authenticates_clients_and_restores_environment(self):
        original_token = os.environ.get("RULE_SERVICE_API_TOKEN")
        try:
            os.environ["RULE_SERVICE_API_TOKEN"] = "caller-token"
            with running_rule_service() as base_url:
                self.assertEqual(os.environ["RULE_SERVICE_API_TOKEN"], TEST_RULE_SERVICE_TOKEN)
                self.assertEqual(RuleServiceClient(base_url).get_policy()["revision"], 1)
            self.assertEqual(os.environ["RULE_SERVICE_API_TOKEN"], "caller-token")
        finally:
            if original_token is None:
                os.environ.pop("RULE_SERVICE_API_TOKEN", None)
            else:
                os.environ["RULE_SERVICE_API_TOKEN"] = original_token


if __name__ == "__main__":
    unittest.main()