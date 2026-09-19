"""Deterministic business outputs; wall-clock telemetry is stored separately."""
from collections import Counter
from copy import deepcopy
from time import perf_counter_ns
import math
from ..common import timestamp
from ..context import get_transaction_context
from ..explanation import explain_decision
from ..frontend_contract import audit_explanation
from ..schema import validate
from .guardrail import simulate_checks


def initial_state():
    return {"events": [], "processed": []}


def apply_decision(state, transaction, decision, dataset):
    aid = transaction["authorization_id"]
    if aid in state["processed"]:
        return False
    if decision not in ("approve", "decline", "step_up"):
        raise ValueError("Invalid decision")
    merchant = dataset["indexes"]["merchants"][transaction["merchant_id"]]
    authority = dataset["indexes"]["scenario_authorities"][transaction["authority_id"]]
    state["events"].append(dict(transaction, status={"approve": "approved", "decline": "declined", "step_up": "pending"}[decision], transaction_type="purchase", initiator_type="agent", customer_id=authority["customer_id"], merchant_category=merchant["merchant_category"], merchant_country=merchant["merchant_country"]))
    state["processed"].append(aid)
    return True


def simulate(requests, dataset, snapshot, index, policy, state=None):
    state = deepcopy(state if state is not None else initial_state())
    results, telemetry = [], []
    previous_time = None
    for transaction in requests:
        current_time = timestamp(transaction["timestamp"])
        if previous_time is not None and current_time < previous_time:
            raise ValueError("Replay must use chronological order")
        previous_time = current_time
        if transaction["authorization_id"] in state["processed"]:
            raise ValueError("Duplicate request; state remains idempotent")
        before = deepcopy(state)
        start = perf_counter_ns()
        context = get_transaction_context(transaction, snapshot, dataset, index, state["events"], policy)
        checks = simulate_checks(transaction, policy, context, state)
        explanation = explain_decision(transaction, policy, checks, context, snapshot)
        apply_decision(state, transaction, explanation["decision"], dataset)
        result = {"input": transaction, "dynamic_context": context, "simulated_guardrail_checks": checks, "KG_Rootcause": explanation, "highlighted_graph_subset": explanation["highlight_graph"], "state_before": before, "state_after": deepcopy(state)}
        validate("SimulationResult", result)
        results.append(result)
        telemetry.append({"authorization_id": transaction["authorization_id"], "latency_ms": (perf_counter_ns() - start)/1_000_000})
    return results, telemetry


def evidence_ids(value):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("supporting_event_ids", "source_event_ids", "duplicate_candidates", "retry_candidates"):
                found.update(child)
            else:
                found.update(evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(evidence_ids(child))
    return found


def build_report(first, second, telemetry, dataset, snapshot, policy):
    counts = Counter(r["KG_Rootcause"]["decision"] for r in first)
    invalid, valid_paths, path_count, future, missing, duplicates, complete, covered = 0, 0, 0, 0, 0, 0, 0, 0
    historical = dataset["indexes"]["authorization_history"]
    attempts = dataset["indexes"]["purchase_attempts"]
    for result in first:
        ctx, explanation = result["dynamic_context"], result["KG_Rootcause"]
        audit = audit_explanation(explanation, snapshot, ctx["overlay"], dataset)
        invalid += len(audit["errors"])
        valid_paths += audit["valid_paths"]
        path_count += audit["path_count"]
        prior_runtime = {e["authorization_id"] for e in result["state_before"]["events"]}
        ids = evidence_ids(ctx["historical_evidence"]) | evidence_ids(result["simulated_guardrail_checks"])
        for eid in ids:
            event = historical.get(eid) or attempts.get(eid)
            if not event:
                invalid += 1
            elif timestamp(event["timestamp"]) >= timestamp(ctx["as_of"]) or (eid in attempts and eid not in prior_runtime):
                future += 1
        missing += len(ctx["missing_evidence"])
        events = result["state_after"]["events"]
        duplicates += len(events) - len({e["authorization_id"] for e in events})
        complete += bool(explanation["decision_cause"]["rules"] and explanation["root_cause_paths"] and not audit["errors"])
        covered += not ctx["missing_evidence"]
    count = len(first)
    replay = 100 * sum(a == b for a, b in zip(first, second)) / max(count, len(second), 1)
    latency = sorted(t["latency_ms"] for t in telemetry)
    report = {"request_count": count, "approve_count": counts["approve"], "step_up_count": counts["step_up"], "decline_count": counts["decline"], "average_evaluation_latency_ms": sum(latency)/len(latency) if latency else 0, "p95_evaluation_latency_ms": latency[math.ceil(.95*len(latency))-1] if latency else 0, "context_coverage_percent": 100*covered/max(count,1), "explanation_completeness_percent": 100*complete/max(count,1), "valid_provenance_path_percent": 100*valid_paths/max(path_count,1), "missing_evidence_count": missing, "future_leakage_count": future, "deterministic_replay_percent": replay, "invalid_graph_reference_count": invalid, "duplicate_state_updates": duplicates, "baseline_passed": count == 10 and future == invalid == duplicates == 0 and replay == 100 and complete == count, "policy": policy, "replay_comparison": "Every business output compared recursively, including context, checks, explanation, highlights, and before/after state. Measured wall-clock latency is separate non-deterministic telemetry.", "limitations": ["Synthetic data; simulation policy is an explicit interpretation of SCEN0001, not a confirmed mandate or expected-decision answer key.", "Source graph contains all fixtures; context evidence reads only prior history and this run's earlier decisions.", "Static catalogue validity cannot be reconstructed without effective-date records.", "Semantic extraction is a conservative draft, not a complete natural-language policy compiler.", "Index is card-partitioned; aggregates scan the time-filtered card history. No bounded prefix aggregates or production latency target yet.", "No fraud model or live-layer integration. Step-up resolution is not implemented."]}
    return validate("SimulationReport", report)
