"""Outbound voice approval requests for step-up decisions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
import re
import threading
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ELEVENLABS_TWILIO_OUTBOUND_URL = "https://api.elevenlabs.io/v1/convai/twilio/outbound-call"
_E164_NUMBER = re.compile(r"^\+[1-9][0-9]{7,14}$")


class ApprovalCallNotifier(Protocol):
    def notify(self, event: Mapping[str, Any], evaluation: Mapping[str, Any]) -> None: ...

    def snapshot(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class NullApprovalCallNotifier:
    """Leaves step-up requests pending when voice approval is not configured."""

    def notify(self, event: Mapping[str, Any], evaluation: Mapping[str, Any]) -> None:
        return

    def snapshot(self) -> dict[str, Any]:
        return {"status": "disabled"}

    def close(self) -> None:
        return


class ElevenLabsApprovalCallNotifier:
    """Starts at most one non-blocking ElevenLabs call per authorization."""

    def __init__(
        self,
        api_key: str,
        agent_id: str,
        agent_phone_number_id: str,
        to_number: str,
        *,
        timeout: float = 5,
        endpoint: str = ELEVENLABS_TWILIO_OUTBOUND_URL,
    ) -> None:
        if not all(isinstance(value, str) and value for value in (api_key, agent_id, agent_phone_number_id)):
            raise ValueError("ElevenLabs API key, agent ID, and phone-number ID are required")
        if not _E164_NUMBER.fullmatch(to_number):
            raise ValueError("VOICE_APPROVAL_TO_NUMBER must use E.164 format, for example +41791234567")
        if timeout <= 0:
            raise ValueError("approval call timeout must be positive")
        self._api_key = api_key
        self._agent_id = agent_id
        self._agent_phone_number_id = agent_phone_number_id
        self._to_number = to_number
        self._timeout = timeout
        self._endpoint = endpoint
        self._lock = threading.Lock()
        self._requested: set[str] = set()
        self._status: dict[str, Any] = {"status": "ready"}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-approval")
        self._closed = False

    def notify(self, event: Mapping[str, Any], evaluation: Mapping[str, Any]) -> None:
        authorization = event["authorization"]
        authorization_id = authorization["authorization_id"]
        with self._lock:
            if self._closed or authorization_id in self._requested:
                return
            self._requested.add(authorization_id)
            self._status = {"status": "queued", "authorization_id": authorization_id}
        payload = self._payload(event, evaluation)
        self._executor.submit(self._place_call, authorization_id, payload)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._status)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True)

    def _payload(self, event: Mapping[str, Any], evaluation: Mapping[str, Any]) -> dict[str, Any]:
        authorization = event["authorization"]
        merchant = authorization["merchant"]
        return {
            "agent_id": self._agent_id,
            "agent_phone_number_id": self._agent_phone_number_id,
            "to_number": self._to_number,
            "conversation_initiation_client_data": {
                "dynamic_variables": {
                    "authorization_id": authorization["authorization_id"],
                    "purchase_description": authorization["purchase_description"],
                    "merchant_name": merchant["merchant_name"],
                    "amount": str(authorization["billing_amount_chf"]),
                    "currency": authorization["currency"],
                    "reason_codes": ", ".join(evaluation["reason_codes"]),
                    "approval_window_seconds": 120,
                }
            },
        }

    def _place_call(self, authorization_id: str, payload: dict[str, Any]) -> None:
        request = Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "xi-api-key": self._api_key},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read() or b"{}")
                if response.status != 200 or body.get("success") is not True:
                    raise ValueError(f"elevenlabs_call_http_{response.status}")
            status = {
                "status": "initiated",
                "authorization_id": authorization_id,
                "conversation_id": body.get("conversation_id"),
                "call_sid": body.get("callSid"),
            }
        except HTTPError as exc:
            status = {"status": "failed", "authorization_id": authorization_id, "error": f"elevenlabs_call_http_{exc.code}"}
        except (URLError, TimeoutError):
            status = {"status": "failed", "authorization_id": authorization_id, "error": "elevenlabs_call_unavailable"}
        except (json.JSONDecodeError, ValueError, OSError):
            status = {"status": "failed", "authorization_id": authorization_id, "error": "elevenlabs_call_invalid_response"}
        with self._lock:
            self._status = status


def approval_call_notifier_from_environment(
    environment: Mapping[str, str] | None = None,
) -> tuple[ApprovalCallNotifier, str | None]:
    """Build the optional notifier and its independently scoped callback token."""

    source = environment if environment is not None else os.environ
    values = {
        "api_key": source.get("ELEVENLABS_API_KEY"),
        "agent_id": source.get("ELEVENLABS_AGENT_ID"),
        "agent_phone_number_id": source.get("ELEVENLABS_PHONE_NUMBER_ID"),
        "to_number": source.get("VOICE_APPROVAL_TO_NUMBER"),
    }
    voice_approval_token = source.get("VOICE_APPROVAL_API_TOKEN")
    if not any(values.values()):
        return NullApprovalCallNotifier(), voice_approval_token
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"incomplete ElevenLabs voice approval configuration: {', '.join(missing)}")
    if not isinstance(voice_approval_token, str) or len(voice_approval_token) < 32:
        raise ValueError("VOICE_APPROVAL_API_TOKEN must be at least 32 characters when voice approval is enabled")
    return ElevenLabsApprovalCallNotifier(**values), voice_approval_token
