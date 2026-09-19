"""Stateful HTTP-facing replay support for the bundled Viseca benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from time import perf_counter
from typing import Any, Mapping
from uuid import uuid4

from decision_receipts import DecisionReceiptLedger, canonical_json
from rule_client import RuleServiceClient
from viseca_benchmark import BenchmarkDataError, BenchmarkPolicyBinding, VisecaBenchmark


class BenchmarkRunError(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _deadline_remaining_ms(deadline_at: str, now: datetime) -> int:
    return max(0, int((_parse_time(deadline_at) - now).total_seconds() * 1000))


def _policy_hash(policy: Mapping[str, Any]) -> str:
    return f"sha256:{sha256(canonical_json(policy).encode('utf-8')).hexdigest()}"


def _policy_snapshot(result: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("policySnapshot", "scenarioPolicy", "policy_snapshot"):
        value = result.get(key)
        if isinstance(value, Mapping):
            nested = value.get("scenarioPolicy")
            if isinstance(nested, Mapping):
                return nested
            return value
    raise BenchmarkRunError("rule service response is missing the policy snapshot")


def _evaluation(result: Mapping[str, Any]) -> dict[str, Any]:
    value = result.get("evaluation")
    if not isinstance(value, Mapping):
        raise BenchmarkRunError("rule service response is missing the evaluation")
    required = {"authorization_id", "recommended_decision", "reason_codes", "checks", "engine_version"}
    if not required.issubset(value):
        raise BenchmarkRunError("rule service evaluation is incomplete")
    if value["recommended_decision"] not in {"approve", "decline", "step_up"}:
        raise BenchmarkRunError("rule service returned an invalid recommendation")
    if not isinstance(value["reason_codes"], list) or not isinstance(value["checks"], list):
        raise BenchmarkRunError("rule service evaluation has invalid checks")
    return dict(value)


@dataclass
class _EventRecord:
    source_authorization_id: str
    authorization_id: str
    replay_order: int
    event: dict[str, Any]
    evaluation: dict[str, Any] | None = None
    evaluation_receipt_hash: str | None = None
    decision: str | None = None
    decision_receipt_hash: str | None = None
    resolution: str | None = None
    resolution_receipt_hash: str | None = None

    def final_status(self) -> str | None:
        if self.decision in {"approve", "decline"}:
            return self.decision
        if self.decision == "step_up" and self.resolution in {"approve", "decline"}:
            return self.resolution
        return None


class BenchmarkRunState:
    def __init__(
        self,
        benchmark: VisecaBenchmark,
        scenario_id: str,
        policy_snapshot: Mapping[str, Any],
        service_run_id: str,
        rule_client: RuleServiceClient,
        receipt_ledger: DecisionReceiptLedger,
        run_id: str | None = None,
    ) -> None:
        self.benchmark = benchmark
        self.scenario_id = scenario_id
        self.policy_snapshot = dict(policy_snapshot)
        self.scenario_policy = dict(_policy_snapshot({"policySnapshot": self.policy_snapshot}))
        self.policy = benchmark.binding_for_scenario(scenario_id, self.scenario_policy)
        self.service_run_id = service_run_id
        self.rule_client = rule_client
        self.receipt_ledger = receipt_ledger
        self.run_id = run_id or f"RUN_BENCHMARK_{scenario_id}_{uuid4().hex[:12].upper()}"
        self._attempts = benchmark.attempts(scenario_id)
        self._next_index = 0
        self._current: _EventRecord | None = None
        self._records: list[_EventRecord] = []
        self._delivered: list[_EventRecord] = []

    def _live_authorization_id(self, source_authorization_id: str) -> str:
        return f"MOCK_{self.run_id}_{source_authorization_id}"

    def _request_id(self, source_authorization_id: str) -> str:
        return f"req_{self.run_id.lower()}_{source_authorization_id.lower()}"

    def _period_days(self) -> int | None:
        periods = [
            rule.get("period_days")
            for rule in self.policy.hard_rules
            if rule.get("scope") == "period" and isinstance(rule.get("period_days"), int)
        ]
        rules = self.scenario_policy.get("rules")
        if isinstance(rules, Mapping):
            for key in ("periodDays", "period_days", "rollingPeriodDays", "rolling_period_days"):
                value = rules.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    periods.append(value)
            rolling = rules.get("rollingPeriod")
            if isinstance(rolling, Mapping):
                for key in ("days", "periodDays", "period_days"):
                    value = rolling.get(key)
                    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                        periods.append(value)
        return max(periods) if periods else None

    def _prior_final_authorizations(self, timestamp: datetime) -> list[dict[str, Any]]:
        prior: list[dict[str, Any]] = []
        for record in self._records:
            final_status = record.final_status()
            if final_status is None:
                continue
            authorization = record.event["authorization"]
            record_time = _parse_time(authorization["timestamp"])
            if record_time >= timestamp:
                continue
            prior.append({
                "authorization_id": record.authorization_id,
                "timestamp": authorization["timestamp"],
                "merchant_id": authorization["merchant"]["merchant_id"],
                "billing_amount_chf": authorization["billing_amount_chf"],
                "status": final_status,
            })
        return prior

    def _approved_spend_in_period(self, timestamp: datetime) -> float:
        period_days = self._period_days()
        if period_days is None:
            return 0.0
        cutoff = timestamp - timedelta(days=period_days)
        return float(sum(
            float(entry["billing_amount_chf"])
            for entry in self._prior_final_authorizations(timestamp)
            if entry["status"] == "approve" and cutoff <= _parse_time(entry["timestamp"]) < timestamp
        ))

    def _context_for(self, timestamp: datetime) -> tuple[float, list[dict[str, Any]], int]:
        prior = self._prior_final_authorizations(timestamp)
        cutoff = timestamp - timedelta(minutes=10)
        recent = [entry for entry in prior if cutoff <= _parse_time(entry["timestamp"]) < timestamp]
        attempts = sum(
            1
            for record in self._delivered
            if cutoff <= _parse_time(record.event["authorization"]["timestamp"]) < timestamp
        )
        return self._approved_spend_in_period(timestamp), recent, attempts

    def _assert_policy_binding(self, snapshot: Mapping[str, Any]) -> None:
        binding = BenchmarkPolicyBinding.from_policy_snapshot(snapshot)
        if (
            binding.policy_id != self.policy.policy_id
            or binding.scenario_id != self.scenario_id
            or binding.card_id != self.policy.card_id
            or binding.mandate_id != self.policy.mandate_id
        ):
            raise BenchmarkRunError("rule service evaluated the event with a mismatched policy binding")

    def _receipt_key(self, stage: str, record: _EventRecord) -> str:
        return f"benchmark:{self.run_id}:{stage}:{record.authorization_id}"

    def _append_receipt(
        self,
        stage: str,
        record: _EventRecord,
        decision: str,
        now: datetime,
        *,
        final_resolution: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if record.evaluation is None:
            raise BenchmarkRunError("evaluation is required before recording a receipt")
        return self.receipt_ledger.append(
            authorization_id=record.authorization_id,
            idempotency_key=self._receipt_key(stage, record),
            decision=decision,
            policy_hash=_policy_hash(self.policy_snapshot),
            policy_version=self.policy_snapshot.get("revision", 1),
            engine_version=record.evaluation["engine_version"],
            reason_codes=record.evaluation["reason_codes"] if stage != "resolution" else ["customer_confirmation"],
            checks=record.evaluation["checks"],
            evidence_refs=(
                "viseca_mock_benchmark",
                {"source": "mock_rule_testing.csv", "source_authorization_id": record.source_authorization_id},
                {"source": "scenario_policy", "policy_id": self.policy.policy_id},
            ),
            run_id=self.run_id,
            request_id=record.event["request_id"],
            received_at=record.event["runtime"]["received_at"],
            evaluated_at=_iso_time(now),
            deadline_at=record.event["deadline_at"],
            deadline_remaining_ms=_deadline_remaining_ms(record.event["deadline_at"], now),
            final_resolution=final_resolution,
        )

    def next_request(self, now: datetime | None = None) -> dict[str, Any] | None:
        if self._current is not None:
            return self._envelope(self._current)
        if self._next_index >= len(self._attempts):
            return None
        source = self._attempts[self._next_index]
        source_id = source["authorization_id"]
        timestamp = _parse_time(source["timestamp"])
        spend, recent, attempts = self._context_for(timestamp)
        event = self.benchmark.build_event(
            source_id,
            self.policy,
            authorization_id=self._live_authorization_id(source_id),
            request_id=self._request_id(source_id),
            received_at=now or _utc_now(),
            approved_spend_in_period_chf=spend,
            recent_authorizations=recent,
            recent_attempt_count_10m=attempts,
            live_authorization_ids={record.source_authorization_id: record.authorization_id for record in self._records},
        )
        record = _EventRecord(
            source_authorization_id=source_id,
            authorization_id=event["authorization"]["authorization_id"],
            replay_order=event["authorization"]["replay_order"],
            event=event,
        )
        self._current = record
        self._records.append(record)
        self._delivered.append(record)
        return self._envelope(record)

    def _envelope(self, record: _EventRecord) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event_id": f"EVT_{self.run_id}_{record.replay_order}",
            "type": "authorization.request",
            "authorization_id": record.authorization_id,
            "source_authorization_id": record.source_authorization_id,
            "status": "pending" if record.final_status() is None else record.final_status(),
            "occurred_at": record.event["runtime"]["received_at"],
            "data": record.event,
        }

    def _require_current(self, authorization_id: str | None = None) -> _EventRecord:
        if self._current is None:
            raise BenchmarkRunError("no_pending_authorization")
        if authorization_id is not None and authorization_id != self._current.authorization_id:
            raise BenchmarkRunError("unknown_authorization")
        return self._current

    def evaluate(self, authorization_id: str | None = None, now: datetime | None = None) -> dict[str, Any]:
        record = self._require_current(authorization_id)
        if record.evaluation is not None:
            return dict(record.evaluation)
        started = perf_counter()
        result = self.rule_client.evaluate(record.event, run_id=self.service_run_id)
        if not isinstance(result, Mapping):
            raise BenchmarkRunError("rule service returned an invalid response")
        evaluated = _evaluation(result)
        if evaluated["authorization_id"] != record.authorization_id:
            raise BenchmarkRunError("rule service evaluated a different authorization")
        snapshot = _policy_snapshot(result)
        self._assert_policy_binding(snapshot)
        record.evaluation = evaluated
        receipt = self._append_receipt("evaluation", record, evaluated["recommended_decision"], now or _utc_now())
        record.evaluation_receipt_hash = receipt["receipt_hash"]
        return {
            **evaluated,
            "policy_snapshot": dict(snapshot),
            "source_authorization_id": record.source_authorization_id,
            "decision_receipt_hash": receipt["receipt_hash"],
            "duration_ms": (perf_counter() - started) * 1000,
        }

    def _validate_reason_codes(self, value: Any, evaluation: Mapping[str, Any]) -> list[str]:
        if value is None:
            return list(evaluation["reason_codes"])
        if (
            isinstance(value, str)
            or not isinstance(value, (list, tuple))
            or not all(isinstance(code, str) and code for code in value)
        ):
            raise BenchmarkRunError("invalid_reason_codes")
        if list(value) != evaluation["reason_codes"]:
            raise BenchmarkRunError("reason_codes_do_not_match_policy")
        return list(value)

    def _advance_after_final(self, record: _EventRecord) -> None:
        if record.final_status() is None:
            return
        if self._current is not record:
            raise BenchmarkRunError("authorization_state_conflict")
        self._current = None
        self._next_index += 1

    def record_decision(
        self,
        authorization_id: str,
        body: Any,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        record = self._require_current(authorization_id)
        if not isinstance(body, Mapping) or body.get("authorization_id") != authorization_id:
            raise BenchmarkRunError("authorization_id_mismatch")
        decision = body.get("decision")
        if decision not in {"approve", "decline", "step_up"}:
            raise BenchmarkRunError("invalid_decision")
        evaluation = self.evaluate(authorization_id, now=now)
        if decision != evaluation["recommended_decision"]:
            raise BenchmarkRunError("decision_does_not_match_policy")
        reason_codes = self._validate_reason_codes(body.get("reason_codes"), evaluation)
        recorded_at = now or _utc_now()
        if recorded_at > _parse_time(record.event["deadline_at"]):
            raise BenchmarkRunError("decision_deadline_exceeded")
        if record.decision is not None:
            if record.decision != decision:
                raise BenchmarkRunError("decision_conflict")
            return {
                "authorization_id": authorization_id,
                "source_authorization_id": record.source_authorization_id,
                "status": "already_recorded",
                "decision": decision,
                "decision_receipt_hash": record.decision_receipt_hash,
            }
        self.rule_client.record_decision(
            self.service_run_id,
            authorization_id,
            decision,
            customer_confirmed=False,
        )
        record.decision = decision
        receipt = self._append_receipt("decision", record, decision, recorded_at)
        record.decision_receipt_hash = receipt["receipt_hash"]
        self._advance_after_final(record)
        return {
            "authorization_id": authorization_id,
            "source_authorization_id": record.source_authorization_id,
            "status": "recorded",
            "decision": decision,
            "reason_codes": reason_codes,
            "decision_receipt_hash": receipt["receipt_hash"],
        }

    def resolve_decision(
        self,
        authorization_id: str,
        body: Any,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        record = self._require_current(authorization_id)
        if record.decision != "step_up":
            raise BenchmarkRunError("resolution_not_available")
        if not isinstance(body, Mapping) or body.get("authorization_id") != authorization_id:
            raise BenchmarkRunError("authorization_id_mismatch")
        decision = body.get("decision")
        if decision not in {"approve", "decline"}:
            raise BenchmarkRunError("invalid_resolution_decision")
        if record.resolution is not None:
            if record.resolution != decision:
                raise BenchmarkRunError("resolution_conflict")
            return {
                "authorization_id": authorization_id,
                "source_authorization_id": record.source_authorization_id,
                "status": "already_resolved",
                "decision": decision,
                "decision_receipt_hash": record.resolution_receipt_hash,
            }
        resolved_at = now or _utc_now()
        if resolved_at > _parse_time(record.event["deadline_at"]) + timedelta(seconds=120):
            raise BenchmarkRunError("resolution_deadline_exceeded")
        self.rule_client.record_decision(
            self.service_run_id,
            authorization_id,
            decision,
            customer_confirmed=True,
        )
        record.resolution = decision
        final_resolution = {
            "decision": decision,
            "resolved_at": _iso_time(resolved_at),
            "spend_effect": "approved" if decision == "approve" else "declined",
        }
        receipt = self._append_receipt(
            "resolution", record, decision, resolved_at, final_resolution=final_resolution
        )
        record.resolution_receipt_hash = receipt["receipt_hash"]
        self._advance_after_final(record)
        return {
            "authorization_id": authorization_id,
            "source_authorization_id": record.source_authorization_id,
            "status": "resolved",
            "decision": decision,
            "decision_receipt_hash": receipt["receipt_hash"],
        }

    def summary(self) -> dict[str, Any]:
        self.receipt_ledger.verify_chain()
        return {
            "run_id": self.run_id,
            "service_run_id": self.service_run_id,
            "scenario_id": self.scenario_id,
            "status": "completed" if self._next_index == len(self._attempts) and self._current is None else "pending",
            "event_count": len(self._attempts),
            "delivered_count": len(self._delivered),
            "completed_count": sum(record.final_status() is not None for record in self._records),
            "policy": {
                "policy_id": self.policy.policy_id,
                "scenario_id": self.policy.scenario_id,
                "card_id": self.policy.card_id,
                "mandate_id": self.policy.mandate_id,
                "revision": self.policy_snapshot.get("revision", 1),
            },
            "events": [
                {
                    "source_authorization_id": record.source_authorization_id,
                    "authorization_id": record.authorization_id,
                    "replay_order": record.replay_order,
                    "recommended_decision": (
                        record.evaluation["recommended_decision"] if record.evaluation is not None else None
                    ),
                    "decision": record.decision,
                    "resolution": record.resolution,
                    "final_status": record.final_status(),
                    "evaluation_receipt_hash": record.evaluation_receipt_hash,
                    "decision_receipt_hash": record.decision_receipt_hash,
                    "resolution_receipt_hash": record.resolution_receipt_hash,
                }
                for record in self._records
            ],
            "receipt_chain_valid": True,
        }


class BenchmarkMockController:
    def __init__(
        self,
        rule_client: RuleServiceClient,
        receipt_ledger: DecisionReceiptLedger,
        benchmark: VisecaBenchmark | None = None,
    ) -> None:
        self.rule_client = rule_client
        self.receipt_ledger = receipt_ledger
        self.benchmark = benchmark or VisecaBenchmark()
        self._runs: dict[str, BenchmarkRunState] = {}

    def start(self, scenario_id: str) -> dict[str, Any]:
        attempts = self.benchmark.attempts(scenario_id)
        started = self.rule_client.start_run(scenario_id, attempts[0]["card_id"])
        if not isinstance(started, Mapping):
            raise BenchmarkRunError("rule service returned an invalid run")
        service_run_id = started.get("runId")
        policy_snapshot = started.get("policySnapshot")
        if not isinstance(service_run_id, str) or not service_run_id:
            raise BenchmarkRunError("rule service run ID is unavailable")
        if not isinstance(policy_snapshot, Mapping):
            raise BenchmarkRunError("rule service run policy is unavailable")
        state = BenchmarkRunState(
            self.benchmark,
            scenario_id,
            policy_snapshot,
            service_run_id,
            self.rule_client,
            self.receipt_ledger,
        )
        self._runs[state.run_id] = state
        return state.summary()

    def start_many(self, scenario_ids: list[str]) -> dict[str, Any]:
        return {"runs": [self.start(scenario_id) for scenario_id in scenario_ids]}

    def run(self, run_id: str) -> BenchmarkRunState:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise BenchmarkRunError("unknown_run") from exc

    def summaries(self) -> list[dict[str, Any]]:
        return [self._runs[run_id].summary() for run_id in sorted(self._runs)]
