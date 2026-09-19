"""Test-only helper: run the sibling rule_service in-process on an ephemeral port.

mock_api.py and viseca_mock.py are HTTP clients of rule_service, never
importers of its modules. Tests exercise that same seam instead of stubbing it
out, by starting a real rule_service HTTPServer for the duration of the test.
"""

from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
from pathlib import Path


_RULE_SERVICE_DIR = Path(__file__).resolve().parents[1] / "rule_service"
if str(_RULE_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_RULE_SERVICE_DIR))

from server import RuleEngineState, build_server  # noqa: E402


@contextmanager
def running_rule_service():
    httpd = build_server(port=0, state=RuleEngineState())
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()
