"""Small client for Viseca's hosted challenge API.

The command-line entry point is read-only. Credentials come from the process
environment and are never printed or stored in the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = (
    "https://saw26api.ashyground-364e1d07.switzerlandnorth.azurecontainerapps.io"
)


class VisecaAPIError(Exception):
    pass


class VisecaClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 30):
        parsed = urlparse(base_url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
        ):
            raise ValueError("LEASH_BASE_URL must use HTTPS or local loopback HTTP")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("LEASH_BASE_URL must be a plain API base URL")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def request(self, method: str, path: str, body: Mapping[str, object] | None = None):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("API path must start with a single slash")
        if method not in {"GET", "POST", "PATCH", "DELETE"}:
            raise ValueError("unsupported API method")
        if method in {"GET", "DELETE"} and body is not None:
            raise ValueError(f"{method} requests cannot include a JSON body")
        public = path == "/healthz"
        if not public and not self.api_key:
            raise VisecaAPIError("TEAM_API_KEY is required for this endpoint")
        headers = {"Accept": "application/json"}
        if not public:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = Request(self.base_url + path, data=payload, headers=headers, method=method)
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

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, body: Mapping[str, object]):
        return self.request("POST", path, body)

    def patch(self, path: str, body: Mapping[str, object]):
        return self.request("PATCH", path, body)

    def delete(self, path: str):
        return self.request("DELETE", path)

    @staticmethod
    def _resource_id(value: str, resource: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{resource} must be a non-empty string")
        return quote(value, safe="")

    @staticmethod
    def _decision(value: str, *, resolution: bool = False) -> str:
        allowed = {"approve", "decline"} if resolution else {"approve", "decline", "step_up"}
        if value not in allowed:
            raise ValueError("invalid decision")
        return value

    def health(self):
        return self.get("/healthz")

    def bootstrap(self):
        return self.get("/v1/bootstrap")

    def reference_data(self):
        return self.get("/v1/reference-data")

    def create_mandate(self, mandate: Mapping[str, object]):
        return self.post("/v1/mandates", mandate)

    def confirm_mandate(self, draft_id: str, confirmed: bool = True):
        return self.post(
            f"/v1/mandates/{self._resource_id(draft_id, 'draft ID')}/confirm",
            {"confirmed": confirmed},
        )

    def mandate(self, mandate_id: str):
        return self.get(f"/v1/mandates/{self._resource_id(mandate_id, 'mandate ID')}")

    def update_mandate(self, mandate_id: str, update: Mapping[str, object]):
        return self.patch(f"/v1/mandates/{self._resource_id(mandate_id, 'mandate ID')}", update)

    def revoke_mandate(self, mandate_id: str):
        return self.delete(f"/v1/mandates/{self._resource_id(mandate_id, 'mandate ID')}")

    def start_run(self, scenario_id: str, mandate_id: str):
        return self.post("/v1/scenario-runs", {
            "scenario_id": scenario_id,
            "mandate_id": mandate_id,
        })

    def run_status(self, run_id: str):
        return self.get(f"/v1/scenario-runs/{self._resource_id(run_id, 'run ID')}")

    def next_request(self, wait_seconds: int = 25):
        if not isinstance(wait_seconds, int) or isinstance(wait_seconds, bool) or not 0 <= wait_seconds <= 25:
            raise ValueError("wait_seconds must be an integer from 0 to 25")
        return self.get(f"/v1/decision-requests/next?{urlencode({'wait': wait_seconds})}")

    def submit_decision(
        self,
        authorization_id: str,
        decision: str,
        *,
        reason_codes: Sequence[str] | None = None,
        customer_message: str | None = None,
        evidence: Sequence[object] | None = None,
        engine_version: str | None = None,
    ):
        body: dict[str, object] = {
            "authorization_id": authorization_id,
            "decision": self._decision(decision),
        }
        if reason_codes is not None:
            body["reason_codes"] = list(reason_codes)
        if customer_message is not None:
            body["customer_message"] = customer_message
        if evidence is not None:
            body["evidence"] = list(evidence)
        if engine_version is not None:
            body["engine_version"] = engine_version
        authorization = self._resource_id(authorization_id, "authorization ID")
        return self.post(f"/v1/authorizations/{authorization}/decision", body)

    def resolve_decision(
        self,
        authorization_id: str,
        decision: str,
        *,
        customer_message: str | None = None,
        evidence: Sequence[object] | None = None,
    ):
        body: dict[str, object] = {"decision": self._decision(decision, resolution=True)}
        if customer_message is not None:
            body["customer_message"] = customer_message
        if evidence is not None:
            body["evidence"] = list(evidence)
        authorization = self._resource_id(authorization_id, "authorization ID")
        return self.post(f"/v1/authorizations/{authorization}/resolve", body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Viseca challenge API status and setup")
    parser.add_argument("command", choices=("health", "bootstrap", "reference-data", "next"))
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
            "next": client.next_request,
        }[args.command]()
    except (VisecaAPIError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
