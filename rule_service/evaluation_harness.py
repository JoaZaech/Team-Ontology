from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json
from time import perf_counter_ns
from typing import Any

from fixtures import DATA_DIR, build_connection_event
from guardian import MerchantHistory
from rulebook import evaluate_request
from wallet_policy import WalletPolicyStore


CONNECTION_CHECK_RECEIVED_AT = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)


def canonical_json(value: Any) -> str:
    return json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_hash(value: Any) -> str:
    return f"sha256:{sha256(canonical_json(value).encode('utf-8')).hexdigest()}"


def decision_signature(result: Mapping[str, Any]) -> str:
    required = ("authorization_id", "recommended_decision", "reason_codes", "checks", "engine_version")
    if any(field not in result for field in required):
        raise ValueError("evaluation result is missing a determinism field")
    payload = {field: result[field] for field in required}
    return canonical_hash(payload)


def percentile(values: list[float], percentage: int) -> float:
    if not values:
        raise ValueError("at least one duration is required")
    if percentage not in (50, 95, 99):
        raise ValueError("percentage must be 50, 95, or 99")
    ordered = sorted(values)
    index = max(0, ((len(ordered) * percentage + 99) // 100) - 1)
    return ordered[index]


def replay_evaluation(evaluator: Callable[[], Mapping[str, Any]], runs: int = 100) -> dict[str, Any]:
    if not isinstance(runs, int) or isinstance(runs, bool) or runs < 1:
        raise ValueError("runs must be a positive integer")
    signatures: list[str] = []
    durations_ms: list[float] = []
    baseline_result: Mapping[str, Any] | None = None
    for _ in range(runs):
        started = perf_counter_ns()
        result = evaluator()
        durations_ms.append((perf_counter_ns() - started) / 1_000_000)
        signatures.append(decision_signature(result))
        if baseline_result is None:
            baseline_result = result
    baseline = signatures[0]
    identical_runs = sum(signature == baseline for signature in signatures)
    return {
        "runs": runs,
        "identical_runs": identical_runs,
        "deterministic": identical_runs == runs,
        "decision_signature": baseline,
        "engine_version": baseline_result["engine_version"],
        "latency_ms": {
            "p50": percentile(durations_ms, 50),
            "p95": percentile(durations_ms, 95),
            "p99": percentile(durations_ms, 99),
            "max": max(durations_ms),
        },
    }


def connection_check_report(runs: int = 100) -> dict[str, Any]:
    history = MerchantHistory.from_data_dir(DATA_DIR)
    fixture_path = DATA_DIR / "scenario_fixtures" / "connection_check.json"
    event = build_connection_event(now=CONNECTION_CHECK_RECEIVED_AT)
    policy = WalletPolicyStore().get()
    report = replay_evaluation(
        lambda: evaluate_request(event, history, wallet_policy=policy),
        runs=runs,
    )
    return {
        **report,
        "benchmark_scope": "pure_rulebook_evaluation",
        "fixture": str(fixture_path.relative_to(DATA_DIR)),
        "fixture_content_hash": f"sha256:{sha256(fixture_path.read_bytes()).hexdigest()}",
        "event_hash": canonical_hash(event),
        "policy_hash": canonical_hash(policy),
        "policy_revision": policy["revision"],
        "received_at": event["runtime"]["received_at"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay the local rulebook determinism benchmark")
    parser.add_argument("--runs", type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(connection_check_report(args.runs), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
