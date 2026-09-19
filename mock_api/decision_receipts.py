"""Append-only, hash-chained decision receipts for the local prototype.

Supply opaque evidence references only; this module never logs receipt content.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3
import threading
from typing import Any


__all__ = [
    "DecisionReceiptLedger",
    "IdempotencyConflictError",
    "InvalidReceiptError",
    "ReceiptIntegrityError",
    "ReceiptLedgerError",
    "canonical_json",
]


_DECISIONS = frozenset({"approve", "decline", "step_up"})
_SCHEMA_VERSION = "decision-receipt-v1"
_SUBMISSION_FIELDS = (
    "schema_version",
    "authorization_id",
    "run_id",
    "request_id",
    "idempotency_key",
    "decision",
    "policy_hash",
    "policy_version",
    "engine_version",
    "reason_codes",
    "checks",
    "evidence_refs",
    "received_at",
    "evaluated_at",
    "deadline_at",
    "deadline_remaining_ms",
    "final_resolution",
)
_RECEIPT_FIELDS = frozenset(
    (*_SUBMISSION_FIELDS, "recorded_at", "previous_receipt_hash", "receipt_hash")
)


class ReceiptLedgerError(Exception):
    """Base error for receipt-ledger operations."""


class InvalidReceiptError(ReceiptLedgerError):
    """Raised when a receipt cannot be represented safely and canonically."""


class IdempotencyConflictError(ReceiptLedgerError):
    """Raised when an idempotency key is reused with changed content."""


class ReceiptIntegrityError(ReceiptLedgerError):
    """Raised when stored receipts no longer form a valid hash chain."""


def canonical_json(value: Any) -> str:
    """Serialize supported JSON values deterministically."""

    return json.dumps(
        _normalise_json(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _normalise_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidReceiptError("receipt contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        normalised: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidReceiptError("receipt object keys must be strings")
            normalised[key] = _normalise_json(item)
        return normalised
    if isinstance(value, (list, tuple)):
        return [_normalise_json(item) for item in value]
    raise InvalidReceiptError("receipt contains a non-JSON value")


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidReceiptError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _json_sequence(value: Any, field: str) -> list[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InvalidReceiptError(f"{field} must be a sequence")
    return [_normalise_json(item) for item in value]


def _reason_codes(value: Any) -> list[str]:
    values = _json_sequence(value, "reason_codes")
    if not all(isinstance(item, str) and item.strip() for item in values):
        raise InvalidReceiptError("reason_codes must contain non-empty strings")
    return values


def _checks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InvalidReceiptError("checks must be a sequence")
    checks: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise InvalidReceiptError("checks must contain objects")
        normalised = _normalise_json(item)
        if not isinstance(normalised, dict):
            raise InvalidReceiptError("checks must contain objects")
        checks.append(normalised)
    return checks


def _evidence_refs(value: Any) -> list[Any]:
    values = _json_sequence(value, "evidence_refs")
    for item in values:
        if isinstance(item, str) and item.strip():
            continue
        if isinstance(item, dict):
            continue
        raise InvalidReceiptError("evidence_refs must contain non-empty strings or objects")
    return values


def _policy_version(value: Any) -> str | int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InvalidReceiptError("policy_version must be a string or integer")
    if isinstance(value, str) and not value.strip():
        raise InvalidReceiptError("policy_version must be non-empty")
    return value


def _deadline_remaining_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidReceiptError("deadline_remaining_ms must be a non-negative integer")
    return value


def _final_resolution(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise InvalidReceiptError("final_resolution must be an object or null")
    normalised = _normalise_json(value)
    if not isinstance(normalised, dict):
        raise InvalidReceiptError("final_resolution must be an object or null")
    return normalised


def _receipt_hash(unsigned_receipt: Mapping[str, Any]) -> str:
    digest = sha256(canonical_json(unsigned_receipt).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


class DecisionReceiptLedger:
    """SQLite-backed append-only receipt ledger with idempotent writes."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connection = sqlite3.connect(
            str(database_path), check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._closed = False
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS decision_receipts (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT NOT NULL UNIQUE,
                submission_json TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                previous_receipt_hash TEXT,
                receipt_hash TEXT NOT NULL UNIQUE,
                recorded_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS decision_receipts_no_update
            BEFORE UPDATE ON decision_receipts
            BEGIN
                SELECT RAISE(ABORT, 'decision receipt ledger is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS decision_receipts_no_delete
            BEFORE DELETE ON decision_receipts
            BEGIN
                SELECT RAISE(ABORT, 'decision receipt ledger is append-only');
            END;
            CREATE TABLE IF NOT EXISTS receipt_outbox_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                receipt_hash TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                published_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                FOREIGN KEY (receipt_hash) REFERENCES decision_receipts(receipt_hash)
            );
            """
        )

    def __enter__(self) -> "DecisionReceiptLedger":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def append(
        self,
        *,
        authorization_id: str,
        idempotency_key: str,
        decision: str,
        policy_hash: str,
        policy_version: str | int,
        engine_version: str,
        reason_codes: Sequence[str] = (),
        checks: Sequence[Mapping[str, Any]] = (),
        evidence_refs: Sequence[str | Mapping[str, Any]] = (),
        run_id: str | None = None,
        request_id: str | None = None,
        received_at: str | None = None,
        evaluated_at: str | None = None,
        deadline_at: str | None = None,
        deadline_remaining_ms: int | None = None,
        final_resolution: Mapping[str, Any] | None = None,
        outbox_event: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a decision receipt or return its idempotent prior record."""

        submission = self._submission(
            authorization_id=authorization_id,
            idempotency_key=idempotency_key,
            decision=decision,
            policy_hash=policy_hash,
            policy_version=policy_version,
            engine_version=engine_version,
            reason_codes=reason_codes,
            checks=checks,
            evidence_refs=evidence_refs,
            run_id=run_id,
            request_id=request_id,
            received_at=received_at,
            evaluated_at=evaluated_at,
            deadline_at=deadline_at,
            deadline_remaining_ms=deadline_remaining_ms,
            final_resolution=final_resolution,
        )
        submission_json = canonical_json(submission)

        with self._lock:
            self._ensure_open()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                rows = self._rows()
                self._verify_rows(rows)
                existing = self._connection.execute(
                    "SELECT * FROM decision_receipts WHERE idempotency_key = ?",
                    (submission["idempotency_key"],),
                ).fetchone()
                if existing is not None:
                    if existing["submission_json"] != submission_json:
                        raise IdempotencyConflictError(
                            "idempotency key is already bound to different receipt content"
                        )
                    record = self._record_from_row(existing)
                    self._connection.commit()
                    return record

                previous_receipt_hash = (
                    self._record_from_row(rows[-1])["receipt_hash"] if rows else None
                )
                unsigned_receipt = {
                    **submission,
                    "recorded_at": self._recorded_at(),
                    "previous_receipt_hash": previous_receipt_hash,
                }
                receipt_hash = _receipt_hash(unsigned_receipt)
                record = {**unsigned_receipt, "receipt_hash": receipt_hash}
                self._connection.execute(
                    """
                    INSERT INTO decision_receipts (
                        idempotency_key,
                        submission_json,
                        receipt_json,
                        previous_receipt_hash,
                        receipt_hash,
                        recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        submission["idempotency_key"],
                        submission_json,
                        canonical_json(record),
                        previous_receipt_hash,
                        receipt_hash,
                        record["recorded_at"],
                    ),
                )
                if outbox_event is not None:
                    self._store_outbox_event(record, outbox_event)
                self._connection.commit()
                return record
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise

    def get(self, idempotency_key: str) -> dict[str, Any] | None:
        """Return the receipt bound to an idempotency key, if present."""

        key = _required_text(idempotency_key, "idempotency_key")
        with self._lock:
            self._ensure_open()
            rows = self._rows()
            self._verify_rows(rows)
            for row in rows:
                if row["idempotency_key"] == key:
                    return self._record_from_row(row)
        return None

    def iter_receipts(self) -> Iterator[dict[str, Any]]:
        """Iterate over receipts in append order after verifying the chain."""

        with self._lock:
            self._ensure_open()
            rows = self._rows()
            self._verify_rows(rows)
            records = tuple(self._record_from_row(row) for row in rows)
        return iter(records)

    def pending_outbox_events(self, limit: int = 100) -> tuple[dict[str, Any], ...]:
        """Return receipt-safe flywheel events awaiting delivery."""

        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                """
                SELECT event_id, event_type, payload_json, created_at, attempts, last_error
                FROM receipt_outbox_events
                WHERE published_at IS NULL
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ReceiptIntegrityError("receipt outbox contains invalid stored JSON") from exc
            if not isinstance(payload, dict) or payload.get("event_id") != row["event_id"]:
                raise ReceiptIntegrityError("receipt outbox event does not match its stored key")
            events.append({
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "payload": payload,
                "created_at": row["created_at"],
                "attempts": row["attempts"],
                "last_error": row["last_error"],
            })
        return tuple(events)

    def mark_outbox_published(self, event_id: str) -> None:
        """Mark an event delivered after an idempotent consumer acknowledges it."""

        key = _required_text(event_id, "event_id")
        with self._lock:
            self._ensure_open()
            self._connection.execute(
                """
                UPDATE receipt_outbox_events
                SET published_at = COALESCE(published_at, ?), last_error = NULL
                WHERE event_id = ?
                """,
                (self._recorded_at(), key),
            )

    def record_outbox_failure(self, event_id: str, error: str) -> None:
        """Retain a delivery failure for asynchronous retry and operator visibility."""

        key = _required_text(event_id, "event_id")
        detail = _required_text(error, "error")
        with self._lock:
            self._ensure_open()
            self._connection.execute(
                """
                UPDATE receipt_outbox_events
                SET attempts = attempts + 1, last_error = ?
                WHERE event_id = ? AND published_at IS NULL
                """,
                (detail[:512], key),
            )

    def outbox_status(self) -> dict[str, Any]:
        """Return bounded delivery status without exposing event payloads."""

        with self._lock:
            self._ensure_open()
            row = self._connection.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE published_at IS NULL) AS pending_count,
                    COUNT(*) FILTER (WHERE published_at IS NOT NULL) AS published_count,
                    MAX(attempts) AS max_attempts
                FROM receipt_outbox_events
                """
            ).fetchone()
        return {
            "pending_count": row["pending_count"],
            "published_count": row["published_count"],
            "max_attempts": row["max_attempts"] or 0,
        }

    def verify_chain(self) -> None:
        """Raise ReceiptIntegrityError unless every persisted receipt verifies."""

        with self._lock:
            self._ensure_open()
            self._verify_rows(self._rows())

    def _ensure_open(self) -> None:
        if self._closed:
            raise ReceiptLedgerError("receipt ledger is closed")

    def _rows(self) -> list[sqlite3.Row]:
        return list(
            self._connection.execute(
                "SELECT * FROM decision_receipts ORDER BY sequence ASC"
            )
        )

    def _recorded_at(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ReceiptLedgerError("receipt clock must return a datetime")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")

    def _store_outbox_event(
        self,
        receipt: Mapping[str, Any],
        outbox_event: Mapping[str, Any],
    ) -> None:
        if not isinstance(outbox_event, Mapping):
            raise InvalidReceiptError("outbox_event must be an object")
        payload = _normalise_json(outbox_event)
        if not isinstance(payload, dict):
            raise InvalidReceiptError("outbox_event must be an object")
        if "event_id" in payload:
            raise InvalidReceiptError("outbox_event must not supply event_id")
        event_type = _required_text(payload.get("event_type"), "outbox_event.event_type")
        event_id = _required_text(receipt.get("receipt_hash"), "receipt_hash")
        provenance = payload.get("provenance")
        if isinstance(provenance, Mapping):
            if "receipt_hash" in provenance and provenance["receipt_hash"] != event_id:
                raise InvalidReceiptError("outbox_event provenance receipt_hash must match the receipt")
            payload["provenance"] = {**provenance, "receipt_hash": event_id}
        stored_payload = {**payload, "event_id": event_id}
        self._connection.execute(
            """
            INSERT INTO receipt_outbox_events (
                event_id, receipt_hash, event_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event_id,
                event_type,
                canonical_json(stored_payload),
                _required_text(receipt.get("recorded_at"), "recorded_at"),
            ),
        )

    def _submission(
        self,
        *,
        authorization_id: Any,
        idempotency_key: Any,
        decision: Any,
        policy_hash: Any,
        policy_version: Any,
        engine_version: Any,
        reason_codes: Any,
        checks: Any,
        evidence_refs: Any,
        run_id: Any,
        request_id: Any,
        received_at: Any,
        evaluated_at: Any,
        deadline_at: Any,
        deadline_remaining_ms: Any,
        final_resolution: Any,
    ) -> dict[str, Any]:
        if not isinstance(decision, str) or decision not in _DECISIONS:
            raise InvalidReceiptError("decision must be approve, decline, or step_up")
        return {
            "schema_version": _SCHEMA_VERSION,
            "authorization_id": _required_text(authorization_id, "authorization_id"),
            "run_id": _optional_text(run_id, "run_id"),
            "request_id": _optional_text(request_id, "request_id"),
            "idempotency_key": _required_text(idempotency_key, "idempotency_key"),
            "decision": decision,
            "policy_hash": _required_text(policy_hash, "policy_hash"),
            "policy_version": _policy_version(policy_version),
            "engine_version": _required_text(engine_version, "engine_version"),
            "reason_codes": _reason_codes(reason_codes),
            "checks": _checks(checks),
            "evidence_refs": _evidence_refs(evidence_refs),
            "received_at": _optional_text(received_at, "received_at"),
            "evaluated_at": _optional_text(evaluated_at, "evaluated_at"),
            "deadline_at": _optional_text(deadline_at, "deadline_at"),
            "deadline_remaining_ms": _deadline_remaining_ms(deadline_remaining_ms),
            "final_resolution": _final_resolution(final_resolution),
        }

    def _record_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            record = json.loads(row["receipt_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReceiptIntegrityError("receipt ledger contains invalid stored JSON") from exc
        if not isinstance(record, dict):
            raise ReceiptIntegrityError("receipt ledger contains an invalid receipt")
        return record

    def _verify_rows(self, rows: Sequence[sqlite3.Row]) -> None:
        previous_receipt_hash: str | None = None
        try:
            for row in rows:
                record = self._record_from_row(row)
                if set(record) != _RECEIPT_FIELDS:
                    raise ReceiptIntegrityError("receipt ledger contains an unexpected receipt shape")
                if canonical_json(record) != row["receipt_json"]:
                    raise ReceiptIntegrityError("receipt ledger receipt JSON is not canonical")
                submission = {field: record[field] for field in _SUBMISSION_FIELDS}
                if canonical_json(submission) != row["submission_json"]:
                    raise ReceiptIntegrityError("receipt ledger submission content does not match receipt")
                unsigned_receipt = {
                    field: value for field, value in record.items() if field != "receipt_hash"
                }
                expected_hash = _receipt_hash(unsigned_receipt)
                if record["receipt_hash"] != expected_hash:
                    raise ReceiptIntegrityError("receipt ledger hash verification failed")
                if row["receipt_hash"] != record["receipt_hash"]:
                    raise ReceiptIntegrityError("receipt ledger hash index does not match receipt")
                if record["previous_receipt_hash"] != previous_receipt_hash:
                    raise ReceiptIntegrityError("receipt ledger chain link verification failed")
                if row["previous_receipt_hash"] != previous_receipt_hash:
                    raise ReceiptIntegrityError("receipt ledger chain index does not match receipt")
                if row["recorded_at"] != record["recorded_at"]:
                    raise ReceiptIntegrityError("receipt ledger timestamp index does not match receipt")
                previous_receipt_hash = record["receipt_hash"]
        except ReceiptIntegrityError:
            raise
        except (InvalidReceiptError, KeyError, TypeError, ValueError) as exc:
            raise ReceiptIntegrityError("receipt ledger integrity check failed") from exc
