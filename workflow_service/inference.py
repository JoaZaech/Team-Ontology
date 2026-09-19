"""Central decision hub with pluggable policy and evidence subsystems."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MOCK_API_ROOT = Path(__file__).resolve().parents[1] / "mock_api"
if str(MOCK_API_ROOT) not in sys.path:
    sys.path.insert(0, str(MOCK_API_ROOT))

from rule_client import RuleServiceClient


HUB_VERSION = "decision-hub-v1"


class SubsystemError(ValueError):
    pass


class AdvisorySubsystem(Protocol):
    name: str
    required: bool

    def assess(self, event: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class SubsystemAssessment:
    name: str
    version: str
    status: str
    recommendation: str | None
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[object, ...]


class PolicySubsystem:
    name = "policy"
    required = True

    def __init__(self, rule_client: RuleServiceClient):
        self.rule_client = rule_client

    def get_policy(self) -> dict[str, Any]:
        return self.rule_client.get_policy()

    def evaluate(self, event: Mapping[str, Any]) -> dict[str, Any]:
        result = self.rule_client.evaluate(event)
        evaluation = result.get("evaluation")
        if not isinstance(evaluation, dict):
            raise SubsystemError("policy_evaluation_unavailable")
        return evaluation


class KnowledgeGraphSubsystem:
    name = "knowledge_graph"

    def __init__(
        self,
        base_url: str,
        api_token: str | None = None,
        *,
        required: bool = False,
        timeout: float = 2,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.required = required
        self.timeout = timeout

    def assess(self, event: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = json.dumps({"event": event}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        request = Request(self.base_url + "/v1/evidence/resolve", data=payload, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read())
        except HTTPError as exc:
            raise SubsystemError(f"knowledge_graph_http_{exc.code}") from exc
        except (URLError, json.JSONDecodeError) as exc:
            raise SubsystemError("knowledge_graph_unavailable") from exc
        if not isinstance(data, dict):
            raise SubsystemError("knowledge_graph_invalid_response")
        return data


class DecisionHub:
    def __init__(
        self,
        policy: PolicySubsystem,
        advisors: tuple[AdvisorySubsystem, ...] = (),
    ):
        names = [advisor.name for advisor in advisors]
        if len(names) != len(set(names)) or "policy" in names:
            raise ValueError("duplicate_inference_subsystem")
        self.policy = policy
        self.advisors = advisors

    def get_policy(self) -> dict[str, Any]:
        return self.policy.get_policy()

    def evaluate(self, event: Mapping[str, Any]) -> dict[str, Any]:
        policy_result = self.policy.evaluate(event)
        assessments = [SubsystemAssessment(
            name=self.policy.name,
            version=str(policy_result.get("engine_version", "unknown")),
            status="available",
            recommendation=policy_result.get("recommended_decision"),
            reason_codes=tuple(policy_result.get("reason_codes", ())),
            evidence_refs=("policy_evaluation",),
        )]
        result = dict(policy_result)
        if result.get("recommended_decision") != "decline":
            for advisor in self.advisors:
                assessment = self._assess(advisor, event)
                assessments.append(assessment)
                if self._requires_step_up(assessment):
                    self._escalate(result, assessment)
        result["inference"] = {
            "hub_version": HUB_VERSION,
            "subsystems": [self._assessment_payload(assessment) for assessment in assessments],
            "evidence_refs": [reference for assessment in assessments for reference in assessment.evidence_refs],
        }
        return result

    def _assess(self, advisor: AdvisorySubsystem, event: Mapping[str, Any]) -> SubsystemAssessment:
        try:
            payload = advisor.assess(event)
            return self._normalise_assessment(advisor, payload)
        except (ValueError, TypeError):
            return SubsystemAssessment(
                name=advisor.name,
                version="unavailable",
                status="unavailable",
                recommendation="step_up" if advisor.required else None,
                reason_codes=(f"{advisor.name}_unavailable",) if advisor.required else (),
                evidence_refs=(),
            )

    @staticmethod
    def _normalise_assessment(advisor: AdvisorySubsystem, payload: Mapping[str, Any]) -> SubsystemAssessment:
        status = payload.get("status", "available")
        recommendation = payload.get("recommendation")
        version = payload.get("version")
        reason_codes = payload.get("reason_codes", ())
        evidence_refs = payload.get("evidence_refs", ())
        if status not in ("available", "unavailable"):
            raise SubsystemError("invalid_subsystem_status")
        if recommendation not in (None, "step_up"):
            raise SubsystemError("invalid_subsystem_recommendation")
        if not isinstance(version, str) or not version:
            raise SubsystemError("invalid_subsystem_version")
        if isinstance(reason_codes, str) or not isinstance(reason_codes, (list, tuple)):
            raise SubsystemError("invalid_subsystem_reason_codes")
        if not all(isinstance(code, str) and code for code in reason_codes):
            raise SubsystemError("invalid_subsystem_reason_codes")
        if isinstance(evidence_refs, str) or not isinstance(evidence_refs, (list, tuple)):
            raise SubsystemError("invalid_subsystem_evidence_refs")
        if not all(isinstance(reference, (str, dict)) for reference in evidence_refs):
            raise SubsystemError("invalid_subsystem_evidence_refs")
        return SubsystemAssessment(
            name=advisor.name,
            version=version,
            status=status,
            recommendation=recommendation,
            reason_codes=tuple(reason_codes),
            evidence_refs=tuple(evidence_refs),
        )

    @staticmethod
    def _requires_step_up(assessment: SubsystemAssessment) -> bool:
        return assessment.recommendation == "step_up"

    @staticmethod
    def _assessment_payload(assessment: SubsystemAssessment) -> dict[str, Any]:
        return {
            "name": assessment.name,
            "version": assessment.version,
            "status": assessment.status,
            "recommendation": assessment.recommendation,
            "reason_codes": list(assessment.reason_codes),
        }

    @staticmethod
    def _escalate(result: dict[str, Any], assessment: SubsystemAssessment) -> None:
        result["recommended_decision"] = "step_up"
        reason_codes = list(result.get("reason_codes", ()))
        for code in assessment.reason_codes:
            if code not in reason_codes:
                reason_codes.append(code)
        result["reason_codes"] = reason_codes
        checks = list(result.get("checks", ()))
        checks.append({
            "name": f"Inference: {assessment.name}",
            "outcome": "review",
            "reason_code": assessment.reason_codes[0] if assessment.reason_codes else f"{assessment.name}_review",
            "detail": f"{assessment.name} requires customer review.",
        })
        result["checks"] = checks
