"""Background transaction-history projection for decision receipts."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import json
import os
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ActivityProjection:
    """Projects lifecycle events into the local PostgreSQL transaction history."""

    def __init__(self, database_url: str | None = None) -> None:
        self._connection = psycopg.connect(
            database_url or os.environ.get(
                "ACTIVITY_DATABASE_URL", "postgresql://viseca:viseca@127.0.0.1:5432/viseca"
            ),
            row_factory=dict_row,
        )
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="activity-projection")
        self._pending: set[Future[None]] = set()
        self._closed = False
        with self._lock:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS activity_events (
                    event_key TEXT PRIMARY KEY,
                    authorization_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    decision TEXT,
                    receipt_hash TEXT,
                    details_json JSONB NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    authorization_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    merchant_name TEXT NOT NULL,
                    merchant_category TEXT NOT NULL,
                    card_id TEXT NOT NULL,
                    amount_chf REAL NOT NULL,
                    currency TEXT NOT NULL,
                    proposal_summary TEXT NOT NULL,
                    recommended_decision TEXT,
                    agent_decision TEXT,
                    final_decision TEXT,
                    status TEXT NOT NULL,
                    reason_codes_json JSONB NOT NULL,
                    policy_version TEXT,
                    received_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_receipt_hash TEXT
                );
                """
            )
            self._connection.commit()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def enqueue(
        self,
        *,
        event_key: str,
        phase: str,
        event: Mapping[str, Any],
        proposal: Mapping[str, Any],
        evaluation: Mapping[str, Any] | None = None,
        receipt: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Queue a projection update without delaying the decision endpoint response."""

        payload = json.loads(_json({
            "event_key": event_key,
            "phase": phase,
            "event": event,
            "proposal": proposal,
            "evaluation": evaluation,
            "receipt": receipt,
            "error": error,
        }))
        with self._lock:
            if self._closed:
                return
            future = self._executor.submit(self._apply, payload)
            self._pending.add(future)
            future.add_done_callback(self._pending.discard)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM transactions ORDER BY updated_at DESC, authorization_id DESC"
            ).fetchall()
            transactions = [self._transaction_from_row(row) for row in rows]
            return {
                "updated_at": _now(),
                "processing": bool(self._pending),
                "transactions": transactions,
            }

    def wait_until_idle(self) -> None:
        """Wait for queued work. Tests use this instead of timing-sensitive sleeps."""

        while True:
            with self._lock:
                pending = tuple(self._pending)
            if not pending:
                return
            for future in pending:
                future.result()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True)
        with self._lock:
            self._connection.close()

    def _apply(self, payload: Mapping[str, Any]) -> None:
        event = payload["event"]
        authorization = event["authorization"]
        receipt = payload.get("receipt")
        evaluation = payload.get("evaluation") or {}
        proposal = payload["proposal"]
        phase = payload["phase"]
        decision = receipt.get("decision") if isinstance(receipt, dict) else None
        reason_codes = receipt.get("reason_codes", []) if isinstance(receipt, dict) else []
        receipt_hash = receipt.get("receipt_hash") if isinstance(receipt, dict) else None
        policy_version = receipt.get("policy_version") if isinstance(receipt, dict) else None
        existing = self._connection.execute(
            "SELECT agent_decision, final_decision FROM transactions WHERE authorization_id = %s",
            (authorization["authorization_id"],),
        ).fetchone()
        agent_decision = existing["agent_decision"] if existing else None
        final_decision = existing["final_decision"] if existing else None
        status = "proposed"
        if phase == "agent_decision":
            agent_decision = decision
            status = "awaiting_customer" if decision == "step_up" else f"{decision}d"
        elif phase == "customer_resolution":
            final_decision = decision
            status = f"{decision}d"
        elif phase == "error":
            status = "recording_error"
        elif existing:
            status = "awaiting_customer" if agent_decision == "step_up" and not final_decision else (
                f"{final_decision or agent_decision}d" if final_decision or agent_decision else "proposed"
            )

        now = _now()
        details = {"error": payload.get("error"), "reason_codes": reason_codes}
        with self._lock:
            if self._closed:
                return
            self._connection.execute(
                """
                INSERT INTO activity_events (
                    event_key, authorization_id, phase, decision, receipt_hash, details_json, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_key) DO NOTHING
                """,
                (payload["event_key"], authorization["authorization_id"], phase, decision, receipt_hash, Json(details), now),
            )
            self._connection.execute(
                """
                INSERT INTO transactions (
                    authorization_id, request_id, merchant_name, merchant_category, card_id, amount_chf,
                    currency, proposal_summary, recommended_decision, agent_decision, final_decision, status,
                    reason_codes_json, policy_version, received_at, updated_at, last_receipt_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(authorization_id) DO UPDATE SET
                    recommended_decision = excluded.recommended_decision,
                    agent_decision = excluded.agent_decision,
                    final_decision = excluded.final_decision,
                    status = excluded.status,
                    reason_codes_json = excluded.reason_codes_json,
                    policy_version = COALESCE(excluded.policy_version, transactions.policy_version),
                    updated_at = excluded.updated_at,
                    last_receipt_hash = COALESCE(excluded.last_receipt_hash, transactions.last_receipt_hash)
                """,
                (
                    authorization["authorization_id"],
                    event["request_id"],
                    authorization["merchant"]["merchant_name"],
                    authorization["merchant"]["merchant_category"],
                    authorization["card_id"],
                    authorization["billing_amount_chf"],
                    authorization["currency"],
                    proposal["summary"],
                    evaluation.get("recommended_decision"),
                    agent_decision,
                    final_decision,
                    status,
                    Json(reason_codes),
                    str(policy_version) if policy_version is not None else None,
                    event["runtime"]["received_at"],
                    now,
                    receipt_hash,
                ),
            )
            self._connection.commit()

    @staticmethod
    def _transaction_from_row(row: dict[str, Any]) -> dict[str, Any]:
        transaction = dict(row)
        transaction["reason_codes"] = transaction.pop("reason_codes_json")
        return transaction