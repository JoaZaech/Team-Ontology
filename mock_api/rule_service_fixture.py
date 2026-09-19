"""Test-only helper: run the sibling rule_service in-process on an ephemeral port.

mock_api.py and viseca_mock.py are HTTP clients of rule_service, never
importers of its modules. Tests exercise that same seam instead of stubbing it
out, by starting a real rule_service HTTPServer for the duration of the test.
"""

from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
import os
from pathlib import Path
from tempfile import TemporaryDirectory


_RULE_SERVICE_DIR = Path(__file__).resolve().parents[1] / "rule_service"
if str(_RULE_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_RULE_SERVICE_DIR))

from server import RuleEngineState, build_server  # noqa: E402


TEST_RULE_SERVICE_TOKEN = "test-rule-service-token-for-fixture-12345"


@contextmanager
def running_rule_service():
    with TemporaryDirectory() as directory:
        previous_token = os.environ.get("RULE_SERVICE_API_TOKEN")
        os.environ["RULE_SERVICE_API_TOKEN"] = TEST_RULE_SERVICE_TOKEN
        httpd = build_server(
            port=0,
            state=RuleEngineState(
                policy_db_path=Path(directory) / "rules.sqlite3",
                api_token=TEST_RULE_SERVICE_TOKEN,
            ),
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = httpd.server_address
            yield f"http://{host}:{port}"
        finally:
            httpd.shutdown()
            thread.join()
            httpd.server_close()
            if previous_token is None:
                os.environ.pop("RULE_SERVICE_API_TOKEN", None)
            else:
                os.environ["RULE_SERVICE_API_TOKEN"] = previous_token
