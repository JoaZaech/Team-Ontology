"""Durable temporal evidence projection owned by the Evidence Service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any


EVENT_TYPE = "decision.receipt-recorded.v1"
PROJECTION_VERSION = "evidence-v1"


class InvalidEvidenceEvent(ValueError):
    """Raised when a receipt-safe event cannot enter the evidence projection."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidEvidenceEvent(f"{field} must be a non-empty string")
    return value


def _timestamp(value: Any, field: str) -> str:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidEvidenceEvent(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise InvalidEvidenceEvent(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidEvidenceEvent(f"{field} must be an object")
    return value


def _normalise_event(value: Any) -> dict[str, Any]:
    event = _object(value, "event")
    if event.get("event_type") != EVENT_TYPE:
        raise InvalidEvidenceEvent("event_type is not supported")
    authorization = _object(event.get("authorization"), "authorization")
    outcome = _object(event.get("outcome"), "outcome")
    provenance = _object(event.get("provenance"), "provenance")
    amount = authorization.get("billing_amount_minor")
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise InvalidEvidenceEvent("authorization.billing_amount_minor must be an integer")
    decision = _text(outcome.get("decision"), "outcome.decision")
    if decision not in {"approve", "decline", "step_up"}:
        raise InvalidEvidenceEvent("outcome.decision is invalid")
    spend_eligibility = _text(outcome.get("spend_eligibility"), "outcome.spend_eligibility")
    if spend_eligibility not in {"none", "authorization_approved", "settled_purchase", "settled_refund"}:
        raise InvalidEvidenceEvent("outcome.spend_eligibility is invalid")
    event_id = _text(event.get("event_id"), "event_id")
    receipt_hash = _text(provenance.get("receipt_hash"), "provenance.receipt_hash")
    if event_id != receipt_hash:
        raise InvalidEvidenceEvent("event_id must match provenance.receipt_hash")
    return {
        "event_id": event_id,
        "event_type": EVENT_TYPE,
        "occurred_at": _timestamp(event.get("occurred_at"), "occurred_at"),
        "authorization_id": _text(authorization.get("authorization_id"), "authorization.authorization_id"),
        "card_id": _text(authorization.get("card_id"), "authorization.card_id"),
        "customer_id": _text(authorization.get("customer_id"), "authorization.customer_id"),
        "merchant_id": _text(authorization.get("merchant_id"), "authorization.merchant_id"),
        "merchant_category": _text(authorization.get("merchant_category"), "authorization.merchant_category"),
        "device_id": authorization.get("device_id"),
        "billing_amount_minor": amount,
        "currency": _text(authorization.get("currency"), "authorization.currency"),
        "requested_at": _timestamp(authorization.get("requested_at"), "authorization.requested_at"),
        "phase": _text(outcome.get("phase"), "outcome.phase"),
        "decision": decision,
        "effective_at": _timestamp(outcome.get("effective_at"), "outcome.effective_at"),
        "spend_eligibility": spend_eligibility,
        "receipt_hash": receipt_hash,
        "policy_version": _text(provenance.get("policy_version"), "provenance.policy_version"),
        "engine_version": _text(provenance.get("engine_version"), "provenance.engine_version"),
    }


class EvidenceProjection:
    """Service-owned, idempotent projection of receipt-safe evidence events."""

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(database_path), check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._closed = False
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS evidence_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                authorization_id TEXT NOT NULL,
                card_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                merchant_id TEXT NOT NULL,
                merchant_category TEXT NOT NULL,
                device_id TEXT,
                billing_amount_minor INTEGER NOT NULL,
                currency TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                phase TEXT NOT NULL,
                decision TEXT NOT NULL,
                effective_at TEXT NOT NULL,
                spend_eligibility TEXT NOT NULL,
                receipt_hash TEXT NOT NULL UNIQUE,
                policy_version TEXT NOT NULL,
                engine_version TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS evidence_events_temporal_lookup
            ON evidence_events (card_id, merchant_id, effective_at, sequence);
            CREATE TABLE IF NOT EXISTS authorization_evidence_state (
                authorization_id TEXT PRIMARY KEY,
                card_id TEXT NOT NULL,
                merchant_id TEXT NOT NULL,
                attempt_recorded INTEGER NOT NULL,
                approved_recorded INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS card_merchant_evidence (
                card_id TEXT NOT NULL,
                merchant_id TEXT NOT NULL,
                attempt_count INTEGER NOT NULL,
                approved_count INTEGER NOT NULL,
                approved_amount_minor INTEGER NOT NULL,
                last_effective_at TEXT NOT NULL,
                PRIMARY KEY (card_id, merchant_id)
            );
            """
        )

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def ingest(self, value: Mapping[str, Any]) -> dict[str, Any]:
        event = _normalise_event(value)
        payload_json = json.dumps(value, separators=(",", ":"), sort_keys=True)
        is_approved = event["spend_eligibility"] in {"authorization_approved", "settled_purchase"}
        with self._lock:
            self._ensure_open()
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                inserted = self._connection.execute(
                    """
                    INSERT OR IGNORE INTO evidence_events (
                        event_id, authorization_id, card_id, customer_id, merchant_id, merchant_category,
                        device_id, billing_amount_minor, currency, requested_at, phase, decision,
                        effective_at, spend_eligibility, receipt_hash, policy_version, engine_version, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["event_id"], event["authorization_id"], event["card_id"], event["customer_id"],
                        event["merchant_id"], event["merchant_category"], event["device_id"],
                        event["billing_amount_minor"], event["currency"], event["requested_at"], event["phase"],
                        event["decision"], event["effective_at"], event["spend_eligibility"],
                        event["receipt_hash"], event["policy_version"], event["engine_version"], payload_json,
                    ),
                ).rowcount == 1
                if not inserted:
                    self._connection.commit()
                    return {"status": "accepted", "idempotent": True, "event_id": event["event_id"], "version": PROJECTION_VERSION}
                state = self._connection.execute(
                    "SELECT * FROM authorization_evidence_state WHERE authorization_id = ?",
                    (event["authorization_id"],),
                ).fetchone()
                if state is None:
                    self._connection.execute(
                        """
                        INSERT INTO authorization_evidence_state (
                            authorization_id, card_id, merchant_id, attempt_recorded, approved_recorded
                        ) VALUES (?, ?, ?, 1, ?)
                        """,
                        (event["authorization_id"], event["card_id"], event["merchant_id"], int(is_approved)),
                    )
                    self._upsert_aggregate(event, attempts=1, approvals=int(is_approved))
                elif is_approved and not state["approved_recorded"]:
                    self._connection.execute(
                        "UPDATE authorization_evidence_state SET approved_recorded = 1 WHERE authorization_id = ?",
                        (event["authorization_id"],),
                    )
                    self._upsert_aggregate(event, attempts=0, approvals=1)
                self._connection.commit()
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise
        return {"status": "accepted", "idempotent": False, "event_id": event["event_id"], "version": PROJECTION_VERSION}

    def resolve(self, value: Mapping[str, Any]) -> dict[str, Any]:
        event = _object(value, "event")
        authorization = _object(event.get("authorization"), "event.authorization")
        merchant = _object(authorization.get("merchant"), "event.authorization.merchant")
        cutoff = _timestamp(authorization.get("timestamp"), "event.authorization.timestamp")
        card_id = _text(authorization.get("card_id"), "event.authorization.card_id")
        merchant_id = _text(merchant.get("merchant_id"), "event.authorization.merchant.merchant_id")
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                """
                SELECT receipt_hash, decision, spend_eligibility
                FROM evidence_events
                WHERE card_id = ? AND merchant_id = ? AND effective_at < ?
                ORDER BY effective_at ASC, sequence ASC
                """,
                (card_id, merchant_id, cutoff),
            ).fetchall()
        approved = sum(row["spend_eligibility"] in {"authorization_approved", "settled_purchase"} for row in rows)
        return {
            "status": "available",
            "version": PROJECTION_VERSION,
            "recommendation": None,
            "reason_codes": [],
            "evidence_refs": [
                {"source": "evidence_projection", "receipt_hash": row["receipt_hash"]}
                for row in rows
            ],
            "summary": {"prior_attempt_count": len(rows), "prior_approved_count": approved, "as_of": cutoff},
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_open()
            row = self._connection.execute(
                "SELECT COUNT(*) AS event_count, MAX(effective_at) AS watermark FROM evidence_events"
            ).fetchone()
        return {
            "status": "ok",
            "version": PROJECTION_VERSION,
            "event_count": row["event_count"],
            "watermark": row["watermark"],
        }

    def _upsert_aggregate(self, event: Mapping[str, Any], *, attempts: int, approvals: int) -> None:
        amount = event["billing_amount_minor"] if approvals else 0
        self._connection.execute(
            """
            INSERT INTO card_merchant_evidence (
                card_id, merchant_id, attempt_count, approved_count, approved_amount_minor, last_effective_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(card_id, merchant_id) DO UPDATE SET
                attempt_count = card_merchant_evidence.attempt_count + excluded.attempt_count,
                approved_count = card_merchant_evidence.approved_count + excluded.approved_count,
                approved_amount_minor = card_merchant_evidence.approved_amount_minor + excluded.approved_amount_minor,
                last_effective_at = MAX(card_merchant_evidence.last_effective_at, excluded.last_effective_at)
            """,
            (event["card_id"], event["merchant_id"], attempts, approvals, amount, event["effective_at"]),
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("evidence projection is closed")