"""Asynchronous delivery of receipt-safe events to the Evidence Service."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import threading
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from decision_receipts import DecisionReceiptLedger


class FlywheelPublisher(Protocol):
    def start(self) -> None: ...

    def trigger(self) -> None: ...

    def close(self) -> None: ...


class NullFlywheelPublisher:
    """Keeps standalone workflow tests and deployments free of network work."""

    def start(self) -> None:
        return

    def trigger(self) -> None:
        return

    def close(self) -> None:
        return


class EvidenceServiceOutboxPublisher:
    """Drains the receipt outbox without adding latency to authorization calls."""

    def __init__(
        self,
        ledger: DecisionReceiptLedger,
        base_url: str,
        api_token: str,
        *,
        timeout: float = 2,
        retry_interval: float = 5,
    ) -> None:
        if retry_interval <= 0:
            raise ValueError("retry_interval must be positive")
        self._ledger = ledger
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token
        self._timeout = timeout
        self._retry_interval = retry_interval
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evidence-outbox")
        self._stop_event = threading.Event()
        self._scheduler: threading.Thread | None = None
        self._running = False
        self._closed = False

    def start(self) -> None:
        with self._lock:
            if self._closed or self._scheduler is not None:
                return
            self._scheduler = threading.Thread(
                target=self._retry_pending_events,
                name="evidence-outbox-retry",
                daemon=True,
            )
            self._scheduler.start()
        self.trigger()

    def trigger(self) -> None:
        with self._lock:
            if self._closed or self._running:
                return
            self._running = True
            self._executor.submit(self._drain)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            scheduler = self._scheduler
        self._stop_event.set()
        if scheduler is not None:
            scheduler.join()
        self._executor.shutdown(wait=True)

    def _retry_pending_events(self) -> None:
        while not self._stop_event.wait(self._retry_interval):
            self.trigger()

    def _drain(self) -> None:
        try:
            while True:
                events = self._ledger.pending_outbox_events()
                if not events:
                    return
                for event in events:
                    try:
                        self._publish(event["payload"])
                    except ValueError as exc:
                        self._ledger.record_outbox_failure(event["event_id"], str(exc))
                        return
                    self._ledger.mark_outbox_published(event["event_id"])
        finally:
            with self._lock:
                self._running = False

    def _publish(self, payload: dict[str, Any]) -> None:
        request = Request(
            self._base_url + "/v1/evidence/events",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                if response.status != 202:
                    raise ValueError(f"evidence_service_http_{response.status}")
        except HTTPError as exc:
            raise ValueError(f"evidence_service_http_{exc.code}") from exc
        except URLError as exc:
            raise ValueError("evidence_service_unavailable") from exc