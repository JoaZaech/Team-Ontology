from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from hashlib import sha256
import json
from time import perf_counter_ns
from typing import Any

from decision_receipts import canonical_json
from guardian import MerchantHistory
from rulebook import evaluate_request
from viseca_mock import DATA_DIR, build_connection_event
from wallet_policy import WalletPolicyStore


def decision_signature(result: Mapping[str, Any]) -> str:
    required = ("authorization_id", "recommended_decision", "reason_codes", "checks", "engine_version")
    if any(field not in result for field in required):
        raise ValueError("evaluation result is missing a determinism field")
    payload = {field: result[field] for field in required}
    return f"sha256:{sha256(canonical_json(payload).encode('utf-8')).hexdigest()}"


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
    for _ in range(runs):
        started = perf_counter_ns()
        result = evaluator()
        durations_ms.append((perf_counter_ns() - started) / 1_000_000)
        signatures.append(decision_signature(result))
    baseline = signatures[0]
    identical_runs = sum(signature == baseline for signature in signatures)
    return {
        "runs": runs,
        "identical_runs": identical_runs,
        "deterministic": identical_runs == runs,
        "decision_signature": baseline,
        "latency_ms": {
            "p50": percentile(durations_ms, 50),
            "p95": percentile(durations_ms, 95),
            "p99": percentile(durations_ms, 99),
            "max": max(durations_ms),
        },
    }


def connection_check_report(runs: int = 100) -> dict[str, Any]:
    history = MerchantHistory.from_data_dir(DATA_DIR)
    event = build_connection_event()
    policy = WalletPolicyStore().get()
    return replay_evaluation(
        lambda: evaluate_request(event, history, wallet_policy=policy),
        runs=runs,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay the local rulebook determinism benchmark")
    parser.add_argument("--runs", type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(connection_check_report(args.runs), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
