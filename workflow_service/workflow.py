"""State and lifecycle logic for authorization workflows."""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from hashlib import sha256
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOCK_API_ROOT = PROJECT_ROOT / "mock_api"
if str(MOCK_API_ROOT) not in sys.path:
    sys.path.insert(0, str(MOCK_API_ROOT))

from activity_projection import ActivityProjection
from decision_receipts import DecisionReceiptLedger, canonical_json
from workflow_service.flywheel import FlywheelPublisher, NullFlywheelPublisher
from workflow_service.inference import DecisionHub, PolicySubsystem
from observability import Telemetry
from rule_client import RuleServiceClient


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _deadline_remaining_ms(deadline_at: str, now: datetime) -> int:
    return max(0, int((_parse_time(deadline_at) - now).total_seconds() * 1000))


def _policy_hash(policy: dict[str, Any]) -> str:
    return f"sha256:{sha256(canonical_json(policy).encode('utf-8')).hexdigest()}"


def _agent_proposal(event: dict[str, Any]) -> dict[str, Any]:
    authorization = event["authorization"]
    return {
        "summary": authorization["purchase_description"],
        "merchant_name": authorization["merchant"]["merchant_name"],
        "items": authorization["items"],
        "items_subtotal_chf": authorization["items_subtotal"],
        "delivery_fee_chf": authorization["delivery_fee"],
        "total_chf": authorization["billing_amount_chf"],
    }


class InMemoryActivityProjection:
    def __init__(self) -> None:
        self.transactions: dict[str, dict[str, Any]] = {}

    def enqueue(
        self,
        *,
        event_key: str,
        phase: str,
        event: dict[str, Any],
        proposal: dict[str, Any],
        evaluation: dict[str, Any] | None = None,
        receipt: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        authorization = event["authorization"]
        authorization_id = authorization["authorization_id"]
        transaction = self.transactions.setdefault(authorization_id, {
            "authorization_id": authorization_id,
            "proposal_summary": proposal["summary"],
            "recommended_decision": None,
            "agent_decision": None,
            "final_decision": None,
            "status": "proposed",
        })
        transaction["last_event_key"] = event_key
        if evaluation is not None:
            transaction["recommended_decision"] = evaluation["recommended_decision"]
        decision = receipt.get("decision") if receipt else None
        if phase == "agent_decision":
            transaction["agent_decision"] = decision
            transaction["status"] = "awaiting_customer" if decision == "step_up" else f"{decision}d"
        elif phase == "customer_resolution":
            transaction["final_decision"] = decision
            transaction["status"] = f"{decision}d"
        elif phase == "error":
            transaction["status"] = "recording_error"

    def snapshot(self) -> dict[str, Any]:
        return {"updated_at": _iso_time(_utc_now()), "processing": False, "transactions": list(self.transactions.values())}

    def wait_until_idle(self) -> None:
        return

    def close(self) -> None:
        return


class WorkflowState:
    def __init__(
        self,
        rule_client: RuleServiceClient | None = None,
        decision_hub: DecisionHub | None = None,
        receipt_ledger: DecisionReceiptLedger | None = None,
        activity_projection: ActivityProjection | None = None,
        telemetry: Telemetry | None = None,
        flywheel_publisher: FlywheelPublisher | None = None,
    ):
        self.rule_client = rule_client or RuleServiceClient()
        self.decision_hub = decision_hub or DecisionHub(PolicySubsystem(self.rule_client))
        self.receipt_ledger = receipt_ledger or DecisionReceiptLedger(":memory:")
        self.activity_projection = activity_projection or InMemoryActivityProjection()
        self.telemetry = telemetry or Telemetry()
        self.flywheel_publisher = flywheel_publisher or NullFlywheelPublisher()
        self.event: dict[str, Any] | None = None
        self.run_id: str | None = None
        self.authorization_id: str | None = None
        self.evaluation: dict[str, Any] | None = None
        self.policy_snapshot: dict[str, Any] | None = None
        self.trace: Any | None = None
        self.decision: dict[str, Any] | None = None
        self.resolution: dict[str, Any] | None = None
        self.step_up_recorded_at: datetime | None = None

    def close(self) -> None:
        self.flywheel_publisher.close()
        self.receipt_ledger.close()
        self.activity_projection.close()

    def reset(self) -> None:
        self.event = None
        self.run_id = None
        self.authorization_id = None
        self.evaluation = None
        self.policy_snapshot = None
        self.trace = None
        self.decision = None
        self.resolution = None
        self.step_up_recorded_at = None

    def start(self, event: dict[str, Any], run_id: str, event_id: str | None = None) -> dict[str, Any]:
        if self.event is not None:
            raise ValueError("workflow_already_started")
        authorization = event.get("authorization")
        if not isinstance(authorization, dict):
            raise ValueError("invalid_authorization_event")
        authorization_id = authorization.get("authorization_id")
        request_id = event.get("request_id")
        if not isinstance(authorization_id, str) or not authorization_id:
            raise ValueError("invalid_authorization_id")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("invalid_request_id")
        self.event = event
        self.run_id = run_id
        self.authorization_id = authorization_id
        self.policy_snapshot = self.decision_hub.get_policy()
        self.trace = self.telemetry.start_trace(request_id)
        proposal = _agent_proposal(event)
        self.activity_projection.enqueue(
            event_key=f"proposal:{request_id}:{event['runtime']['received_at']}",
            phase="proposal",
            event=event,
            proposal=proposal,
        )
        self.telemetry.event(
            "decision.request_received",
            trace=self.trace,
            labels={"component": "workflow_service", "status": "received"},
        )
        return {
            "run_id": run_id,
            "event_id": event_id or event["request_id"],
            "type": "authorization.request",
            "authorization_id": authorization_id,
            "status": "pending",
            "occurred_at": event["runtime"]["received_at"],
            "data": {
                **event,
                "agent_proposal": proposal,
                "applied_policies": {
                    "confirmed_mandate": {
                        "mandate_id": event["mandate"]["mandate_id"],
                        "instruction": event["mandate"]["instruction"],
                        "hard_rules": event["mandate"]["hard_rules"],
                    },
                    "wallet_policy": {
                        "policy_id": self.policy_snapshot["policyId"],
                        "revision": self.policy_snapshot["revision"],
                        "enabled": self.policy_snapshot["enabled"],
                        "daily_spending_limit_chf": self.policy_snapshot["dailySpendingLimitChf"],
                        "adaptive_spend_profiles": self.policy_snapshot["adaptiveSpendProfiles"],
                        "review_triggers": self.policy_snapshot["reviewTriggers"],
                        "assistant_authority": self.policy_snapshot["assistantAuthority"],
                        "rules": self.policy_snapshot["receiptRules"],
                    },
                },
            },
        }

    def activity_snapshot(self) -> dict[str, Any]:
        snapshot = self.activity_projection.snapshot()
        return {**snapshot, "flywheel": self.flywheel_status()}

    def flywheel_status(self) -> dict[str, Any]:
        return self.receipt_ledger.outbox_status()

    def record_activity_failure(self, phase: str, error: str) -> None:
        if self.event is None:
            return
        self.activity_projection.enqueue(
            event_key=f"error:{phase}:{self.event['request_id']}:{time.time_ns()}",
            phase="error",
            event=self.event,
            proposal=_agent_proposal(self.event),
            evaluation=self.evaluation,
            error=error,
        )

    def _receipt_key(self, stage: str) -> str:
        if self.event is None:
            raise ValueError("request_not_delivered")
        return f"{stage}:{self.event['request_id']}:{self.event['runtime']['received_at']}"

    def _evidence_refs(self, evaluation: dict[str, Any], terminal_reference: str) -> tuple[object, ...]:
        if self.policy_snapshot is None:
            raise ValueError("policy_snapshot_unavailable")
        inference = evaluation.get("inference")
        hub_refs = inference.get("evidence_refs", ()) if isinstance(inference, dict) else ()
        return (
            "authorization_event",
            "confirmed_mandate",
            {"source": "dynamic_wallet_policy", "revision": self.policy_snapshot["revision"]},
            terminal_reference,
            *hub_refs,
        )

    def evaluate(self) -> dict[str, Any]:
        if self.event is None:
            raise ValueError("request_not_delivered")
        if self.evaluation is not None:
            return self.evaluation
        if self.policy_snapshot is None:
            raise ValueError("policy_snapshot_unavailable")
        started = time.perf_counter()
        with self.telemetry.span(
            "decision.evaluate",
            trace=self.trace,
            labels={"component": "workflow_service"},
        ):
            result = self.decision_hub.evaluate(self.event)
        duration_ms = (time.perf_counter() - started) * 1000
        evaluated_at = _utc_now()
        authorization = self.event["authorization"]
        receipt = self.receipt_ledger.append(
            authorization_id=authorization["authorization_id"],
            idempotency_key=self._receipt_key("evaluation"),
            decision=result["recommended_decision"],
            policy_hash=_policy_hash(self.policy_snapshot),
            policy_version=self.policy_snapshot["revision"],
            engine_version=result["engine_version"],
            reason_codes=result["reason_codes"],
            checks=result["checks"],
            evidence_refs=self._evidence_refs(result, "merchant_history"),
            run_id=self.run_id or "unknown-run",
            request_id=self.event["request_id"],
            received_at=self.event["runtime"]["received_at"],
            evaluated_at=_iso_time(evaluated_at),
            deadline_at=self.event["deadline_at"],
            deadline_remaining_ms=_deadline_remaining_ms(self.event["deadline_at"], evaluated_at),
        )
        self.telemetry.event(
            "decision.context_resolved",
            trace=self.trace,
            labels={"component": "workflow_service", "status": "ok"},
            attributes={"policy_version": f"policy_{self.policy_snapshot['revision']}"},
        )
        self.telemetry.event(
            "decision.evaluated",
            trace=self.trace,
            labels={"component": "workflow_service", "outcome": result["recommended_decision"]},
            attributes={"engine_version": result["engine_version"], "receipt_hash": receipt["receipt_hash"]},
        )
        self.telemetry.record_decision(
            result["recommended_decision"],
            reason_codes=result["reason_codes"],
            trace=self.trace,
            duration_ms=duration_ms,
            labels={"component": "workflow_service"},
            attributes={"engine_version": result["engine_version"], "receipt_hash": receipt["receipt_hash"]},
        )
        self.evaluation = result
        return result

    def record_decision(
        self,
        authorization_id: str,
        body: Any,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self._validate_decision_request(authorization_id, body)
        evaluation = self.evaluate()
        recorded_body = self._recorded_decision_body(body, evaluation)
        existing = self._existing_decision(authorization_id, recorded_body)
        if existing is not None:
            return existing
        recorded_at = now or _utc_now()
        self._assert_decision_deadline(recorded_at)
        receipt = self._append_decision_receipt(authorization_id, recorded_body, evaluation, recorded_at)
        self.decision = recorded_body
        self._project_recorded_decision(receipt, evaluation, recorded_at)
        return {
            "authorization_id": authorization_id,
            "status": "recorded",
            "decision": recorded_body["decision"],
            "decision_receipt_hash": receipt["receipt_hash"],
        }

    def resolve_decision(
        self,
        authorization_id: str,
        body: Any,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self._validate_resolution_request(authorization_id, body)
        existing = self._existing_resolution(authorization_id, body)
        if existing is not None:
            return existing
        resolved_at = now or _utc_now()
        self._assert_resolution_deadline(resolved_at)
        evaluation = self.evaluate()
        receipt = self._append_resolution_receipt(authorization_id, body, evaluation, resolved_at)
        self.resolution = body
        self._project_resolution(receipt, evaluation, body)
        return {
            "authorization_id": authorization_id,
            "status": "resolved",
            "decision": body["decision"],
            "decision_receipt_hash": receipt["receipt_hash"],
        }

    def _validate_decision_request(self, authorization_id: str, body: Any) -> None:
        if authorization_id != self.authorization_id:
            raise ValueError("unknown_authorization")
        if not isinstance(body, dict) or body.get("authorization_id") != authorization_id:
            raise ValueError("authorization_id_mismatch")
        if body.get("decision") not in ("approve", "decline", "step_up"):
            raise ValueError("invalid_decision")
        if self.event is None or self.policy_snapshot is None:
            raise ValueError("request_not_delivered")

    def _recorded_decision_body(self, body: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
        if body["decision"] != evaluation["recommended_decision"]:
            raise ValueError("decision_does_not_match_policy")
        submitted_reason_codes = body.get("reason_codes")
        if submitted_reason_codes is None:
            reason_codes = list(evaluation["reason_codes"])
        elif (
            isinstance(submitted_reason_codes, str)
            or not isinstance(submitted_reason_codes, (list, tuple))
            or not all(isinstance(reason_code, str) and reason_code for reason_code in submitted_reason_codes)
        ):
            raise ValueError("invalid_reason_codes")
        elif list(submitted_reason_codes) != evaluation["reason_codes"]:
            raise ValueError("reason_codes_do_not_match_policy")
        else:
            reason_codes = list(submitted_reason_codes)
        return {**body, "reason_codes": reason_codes}

    def _existing_decision(self, authorization_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
        if self.decision is None:
            return None
        if self.decision != body:
            raise ValueError("decision_conflict")
        receipt = self.receipt_ledger.get(self._receipt_key("decision"))
        return {
            "authorization_id": authorization_id,
            "status": "already_recorded",
            **({"decision_receipt_hash": receipt["receipt_hash"]} if receipt else {}),
        }

    def _assert_decision_deadline(self, recorded_at: datetime) -> None:
        if self.event is None or recorded_at <= _parse_time(self.event["deadline_at"]):
            return
        self.telemetry.event(
            "decision.deadline_missed",
            trace=self.trace,
            labels={"component": "workflow_service", "status": "error"},
            attributes={"deadline_missed": True},
        )
        raise ValueError("decision_deadline_exceeded")

    def _append_decision_receipt(
        self,
        authorization_id: str,
        body: dict[str, Any],
        evaluation: dict[str, Any],
        recorded_at: datetime,
    ) -> dict[str, Any]:
        if self.event is None or self.policy_snapshot is None:
            raise ValueError("request_not_delivered")
        with self.telemetry.span("decision.record", trace=self.trace, labels={"component": "workflow_service"}):
            return self.receipt_ledger.append(
                authorization_id=authorization_id,
                idempotency_key=self._receipt_key("decision"),
                decision=body["decision"],
                policy_hash=_policy_hash(self.policy_snapshot),
                policy_version=self.policy_snapshot["revision"],
                engine_version=evaluation["engine_version"],
                reason_codes=body["reason_codes"],
                checks=evaluation["checks"],
                evidence_refs=self._evidence_refs(evaluation, "merchant_history"),
                run_id=self.run_id or "unknown-run",
                request_id=self.event["request_id"],
                received_at=self.event["runtime"]["received_at"],
                evaluated_at=_iso_time(recorded_at),
                deadline_at=self.event["deadline_at"],
                deadline_remaining_ms=_deadline_remaining_ms(self.event["deadline_at"], recorded_at),
                outbox_event=self._flywheel_event("agent_decision", body["decision"], recorded_at),
            )

    def _project_recorded_decision(
        self,
        receipt: dict[str, Any],
        evaluation: dict[str, Any],
        recorded_at: datetime,
    ) -> None:
        if self.event is None or self.decision is None:
            return
        self.activity_projection.enqueue(event_key=receipt["receipt_hash"], phase="agent_decision", event=self.event, proposal=_agent_proposal(self.event), evaluation=evaluation, receipt=receipt)
        self.flywheel_publisher.trigger()
        if self.decision["decision"] == "step_up":
            self.step_up_recorded_at = recorded_at
            self.telemetry.event("decision.step_up", trace=self.trace, labels={"component": "workflow_service", "status": "recorded"})
        else:
            self.activity_projection.wait_until_idle()
        self.telemetry.event(
            "decision.recorded",
            trace=self.trace,
            labels={"component": "workflow_service", "outcome": self.decision["decision"], "status": "recorded"},
            attributes={"deadline_headroom_ms": _deadline_remaining_ms(self.event["deadline_at"], recorded_at), "receipt_hash": receipt["receipt_hash"], "idempotency_result": "recorded"},
        )

    def _validate_resolution_request(self, authorization_id: str, body: Any) -> None:
        if authorization_id != self.authorization_id:
            raise ValueError("unknown_authorization")
        if self.decision is None or self.decision.get("decision") != "step_up":
            raise ValueError("resolution_not_available")
        if not isinstance(body, dict) or body.get("authorization_id") != authorization_id:
            raise ValueError("authorization_id_mismatch")
        if body.get("decision") not in ("approve", "decline"):
            raise ValueError("invalid_resolution_decision")
        if self.event is None or self.policy_snapshot is None:
            raise ValueError("request_not_delivered")

    def _existing_resolution(self, authorization_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
        if self.resolution is None:
            return None
        if self.resolution != body:
            raise ValueError("resolution_conflict")
        receipt = self.receipt_ledger.get(self._receipt_key("resolution"))
        return {
            "authorization_id": authorization_id,
            "status": "already_resolved",
            **({"decision_receipt_hash": receipt["receipt_hash"]} if receipt else {}),
        }

    def _assert_resolution_deadline(self, resolved_at: datetime) -> None:
        if self.step_up_recorded_at is None or resolved_at <= self.step_up_recorded_at + timedelta(seconds=120):
            return
        self.telemetry.event(
            "decision.deadline_missed",
            trace=self.trace,
            labels={"component": "workflow_service", "status": "error"},
            attributes={"deadline_missed": True},
        )
        raise ValueError("resolution_deadline_exceeded")

    def _append_resolution_receipt(
        self,
        authorization_id: str,
        body: dict[str, Any],
        evaluation: dict[str, Any],
        resolved_at: datetime,
    ) -> dict[str, Any]:
        if self.event is None or self.policy_snapshot is None:
            raise ValueError("request_not_delivered")
        resolution = {"decision": body["decision"], "resolved_at": _iso_time(resolved_at), "spend_effect": "approved" if body["decision"] == "approve" else "declined"}
        with self.telemetry.span("decision.resolve", trace=self.trace, labels={"component": "workflow_service"}):
            return self.receipt_ledger.append(
                authorization_id=authorization_id,
                idempotency_key=self._receipt_key("resolution"),
                decision=body["decision"],
                policy_hash=_policy_hash(self.policy_snapshot),
                policy_version=self.policy_snapshot["revision"],
                engine_version=evaluation["engine_version"],
                reason_codes=("customer_confirmation",),
                checks=evaluation["checks"],
                evidence_refs=self._evidence_refs(evaluation, "customer_resolution"),
                run_id=self.run_id or "unknown-run",
                request_id=self.event["request_id"],
                received_at=self.event["runtime"]["received_at"],
                evaluated_at=_iso_time(resolved_at),
                deadline_at=self.event["deadline_at"],
                deadline_remaining_ms=_deadline_remaining_ms(self.event["deadline_at"], resolved_at),
                final_resolution=resolution,
                outbox_event=self._flywheel_event("customer_resolution", body["decision"], resolved_at),
            )

    def _project_resolution(self, receipt: dict[str, Any], evaluation: dict[str, Any], body: dict[str, Any]) -> None:
        if self.event is None:
            return
        self.activity_projection.enqueue(event_key=receipt["receipt_hash"], phase="customer_resolution", event=self.event, proposal=_agent_proposal(self.event), evaluation=evaluation, receipt=receipt)
        self.flywheel_publisher.trigger()
        self.activity_projection.wait_until_idle()
        self.telemetry.event(
            "decision.resolved",
            trace=self.trace,
            labels={"component": "workflow_service", "outcome": body["decision"], "status": "resolved"},
            attributes={"receipt_hash": receipt["receipt_hash"]},
        )

    def _flywheel_event(self, phase: str, decision: str, effective_at: datetime) -> dict[str, Any]:
        if self.event is None or self.policy_snapshot is None:
            raise ValueError("request_not_delivered")
        authorization = self.event["authorization"]
        merchant = authorization["merchant"]
        minor_amount = (Decimal(str(authorization["billing_amount_chf"])) * 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
        if decision == "approve":
            spend_eligibility = "authorization_approved"
        else:
            spend_eligibility = "none"
        return {
            "event_type": "decision.receipt-recorded.v1",
            "occurred_at": _iso_time(effective_at),
            "authorization": {
                "authorization_id": authorization["authorization_id"],
                "card_id": authorization["card_id"],
                "customer_id": self.event["mandate"]["customer_id"],
                "merchant_id": merchant["merchant_id"],
                "merchant_category": merchant["merchant_category"],
                "device_id": authorization.get("customer_device_id"),
                "billing_amount_minor": int(minor_amount),
                "currency": authorization["currency"],
                "requested_at": authorization["timestamp"],
            },
            "outcome": {
                "phase": phase,
                "decision": decision,
                "effective_at": _iso_time(effective_at),
                "spend_eligibility": spend_eligibility,
            },
            "provenance": {
                "policy_version": str(self.policy_snapshot["revision"]),
                "engine_version": "workflow-service-v1",
            },
        }
