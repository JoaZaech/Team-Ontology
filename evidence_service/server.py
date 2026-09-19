"""HTTP boundary for the separately deployable evidence projection service."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from secrets import compare_digest
from typing import Any
from urllib.parse import urlparse

from .projection import EvidenceProjection, InvalidEvidenceEvent


DEFAULT_PORT = int(os.environ.get("EVIDENCE_SERVICE_PORT", "8085"))
MAX_BODY_BYTES = 64 * 1024


class EvidenceHTTPServer(HTTPServer):
    def __init__(self, address: tuple[str, int], handler, projection: EvidenceProjection, api_token: str):
        super().__init__(address, handler)
        self.projection = projection
        self.api_token = api_token

    def server_close(self) -> None:
        try:
            self.projection.close()
        finally:
            super().server_close()


class EvidenceRequestHandler(BaseHTTPRequestHandler):
    server_version = "EvidenceService"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self._json(200, {"status": "ok", "service": "evidence-service"})
        elif path == "/v1/evidence/status":
            if self._authorized():
                self._json(200, self.server.projection.status())
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        try:
            body = self._read_json_body()
        except ValueError:
            self._json(400, {"error": "invalid_json"})
            return
        path = urlparse(self.path).path
        try:
            if path == "/v1/evidence/events":
                self._json(202, self.server.projection.ingest(body))
            elif path == "/v1/evidence/resolve" and isinstance(body, dict):
                self._json(200, self.server.projection.resolve(body.get("event")))
            else:
                self._json(404, {"error": "not_found"})
        except (InvalidEvidenceEvent, ValueError) as exc:
            self._json(400, {"error": str(exc)})

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization")
        expected = f"Bearer {self.server.api_token}"
        if isinstance(header, str) and compare_digest(header, expected):
            return True
        self._json(401, {"error": "service_unauthorized"})
        return False

    def _read_json_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY_BYTES:
            raise ValueError("invalid_body_size")
        return json.loads(self.rfile.read(length))

    def _json(self, status: int, body: Mapping[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run() -> None:
    token = os.environ.get("EVIDENCE_SERVICE_API_TOKEN")
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("EVIDENCE_SERVICE_API_TOKEN must be at least 32 characters")
    database_path = Path(os.environ.get("EVIDENCE_SERVICE_DATABASE_PATH", "var/evidence.sqlite3"))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    server = EvidenceHTTPServer(
        ("127.0.0.1", DEFAULT_PORT),
        EvidenceRequestHandler,
        EvidenceProjection(database_path),
        token,
    )
    print(f"Evidence service: http://127.0.0.1:{DEFAULT_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()