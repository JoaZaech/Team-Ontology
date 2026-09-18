"""Small client for Viseca's hosted challenge API.

The command-line entry point is read-only. Credentials come from the process
environment and are never printed or stored in the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = (
    "https://saw26api.ashyground-364e1d07.switzerlandnorth.azurecontainerapps.io"
)


class VisecaAPIError(Exception):
    pass


class VisecaClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 30):
        if not base_url.startswith("https://"):
            raise ValueError("LEASH_BASE_URL must use HTTPS")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def get(self, path: str):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("API path must start with a single slash")
        public = path == "/healthz"
        if not public and not self.api_key:
            raise VisecaAPIError("TEAM_API_KEY is required for this endpoint")
        headers = {"Accept": "application/json"}
        if not public:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.base_url + path, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                if response.status == 204:
                    return None
                return json.loads(payload)
        except HTTPError as exc:
            raise VisecaAPIError(f"Viseca API returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise VisecaAPIError(f"Cannot reach Viseca API: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise VisecaAPIError("Viseca API returned invalid JSON") from exc

    def health(self):
        return self.get("/healthz")

    def bootstrap(self):
        return self.get("/v1/bootstrap")

    def reference_data(self):
        return self.get("/v1/reference-data")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Viseca challenge API status and setup")
    parser.add_argument("command", choices=("health", "bootstrap", "reference-data"))
    args = parser.parse_args()
    client = VisecaClient(
        os.environ.get("LEASH_BASE_URL", DEFAULT_BASE_URL),
        os.environ.get("TEAM_API_KEY"),
    )
    try:
        result = {
            "health": client.health,
            "bootstrap": client.bootstrap,
            "reference-data": client.reference_data,
        }[args.command]()
    except (VisecaAPIError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
