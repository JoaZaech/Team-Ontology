import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from viseca_client import VisecaAPIError, VisecaClient


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class VisecaClientTests(unittest.TestCase):
    def test_health_uses_no_key(self):
        with patch("viseca_client.urlopen", return_value=FakeResponse({"ok": True})) as call:
            result = VisecaClient("https://example.test").health()
        self.assertEqual(result, {"ok": True})
        self.assertNotIn("Authorization", call.call_args.args[0].headers)

    def test_bootstrap_uses_bearer_key(self):
        with patch("viseca_client.urlopen", return_value=FakeResponse({"version": "test"})) as call:
            result = VisecaClient("https://example.test", "secret").bootstrap()
        self.assertEqual(result["version"], "test")
        self.assertEqual(call.call_args.args[0].get_header("Authorization"), "Bearer secret")

    def test_key_is_required_for_private_endpoint(self):
        with self.assertRaises(VisecaAPIError):
            VisecaClient("https://example.test").reference_data()

    def test_local_mock_url_is_allowed(self):
        client = VisecaClient("http://127.0.0.1:8082", "mock-team-key")
        with patch("viseca_client.urlopen", return_value=FakeResponse({"data": {}})) as call:
            client.next_request()
        self.assertEqual(call.call_args.args[0].full_url,
                         "http://127.0.0.1:8082/v1/decision-requests/next?wait=0")

    def test_remote_plain_http_is_rejected(self):
        with self.assertRaises(ValueError):
            VisecaClient("http://example.test", "secret")

    def test_http_error_does_not_echo_credentials(self):
        failure = HTTPError("https://example.test/v1/bootstrap", 401, "unauthorized", {}, io.BytesIO())
        with patch("viseca_client.urlopen", side_effect=failure):
            with self.assertRaisesRegex(VisecaAPIError, "HTTP 401") as error:
                VisecaClient("https://example.test", "secret").bootstrap()
        self.assertNotIn("secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
