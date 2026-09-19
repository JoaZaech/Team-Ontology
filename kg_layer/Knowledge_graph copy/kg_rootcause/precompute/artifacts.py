"""Offline storage artifacts derived from the validated test dataset."""
from hashlib import sha256
from pathlib import Path

from ..common import digest
from ..context import get_transaction_context


ARTIFACT_VERSIONS = {
    "source_graph": "kg-v1",
    "historical_evidence_index": "evidence-index-v1",
    "precomputed_evidence": "evidence-v1",
    "scenario_checkpoints": "scenario-checkpoints-v1",
    "policy_bindings": "policy-bindings-v1",
    "dataset_manifest": "dataset-manifest-v1",
}


def _file_digest(path):
    return sha256(path.read_bytes()).hexdigest()


def _source_files(data_dir, dataset):
    data_dir = Path(data_dir)
    source_names = {
        row["_source"]["source_file"]
        for rows in dataset["tables"].values()
        for row in rows
    }
    paths = sorted(
        [data_dir / name for name in source_names] + list((data_dir / "schemas").glob("*.json")),
        key=lambda path: str(path.relative_to(data_dir)),
    )
    return [
        {
            "path": str(path.relative_to(data_dir)),
            "sha256": _file_digest(path),
        }
        for path in paths
    ]


def build_dataset_manifest(data_dir, dataset, snapshot):
    """Describe the exact source release and compatible artifact versions."""
    source_files = _source_files(data_dir, dataset)
    return {
        "version": ARTIFACT_VERSIONS["dataset_manifest"],
        "source_release_id": digest(source_files),
        "source_files": source_files,
        "row_counts": {name: len(rows) for name, rows in sorted(dataset["tables"].items())},
        "source_as_of": "2026-08-01T00:00:00Z",
        "snapshot_id": snapshot["snapshot_id"],
        "artifact_versions": ARTIFACT_VERSIONS,
    }


def build_policy_bindings(dataset, policy):
    """Persist policy-to-evidence bindings without evaluating a live request."""
    policy_id = f"PolicyVersion:{policy['version']}"
    rules = [
        {
            "id": f"PolicyRule:{policy['version']}:maximum_order",
            "classification": "hard",
            "operator": "<=",
            "value": policy["maximum_order_cents"],
            "target_concept": "TransactionLimit",
            "dataset_field": "purchase_attempts.billing_amount_chf",
            "evidence_definition": None,
        },
        {
            "id": f"PolicyRule:{policy['version']}:rolling_budget",
            "classification": "hard",
            "operator": "<=",
            "value": policy["rolling_limit_cents"],
            "target_concept": "RollingSpendLimit",
            "dataset_field": "purchase_attempts.billing_amount_chf",
            "evidence_definition": "approved_authority_spend_within_rolling_window",
            "window_days": policy["rolling_days"],
        },
        {
            "id": f"PolicyRule:{policy['version']}:item_category",
            "classification": "hard",
            "operator": "in",
            "value": policy["item_categories"],
            "target_concept": "ItemCategory",
            "dataset_field": "purchase_attempt_items.item_category",
            "evidence_definition": None,
        },
        {
            "id": f"PolicyRule:{policy['version']}:fulfillment_method",
            "classification": "hard",
            "operator": "==",
            "value": policy["fulfillment_method"],
            "target_concept": "Delivery",
            "dataset_field": "purchase_attempts.fulfillment_method",
            "evidence_definition": None,
        },
    ]
    policy_record = {
        "id": policy_id,
        "version": policy["version"],
        "status": policy["status"],
        "scope": policy["scope"],
        "content_hash": digest(policy),
        "source_kind": "simulation_rationale" if policy["status"] == "simulation_assumption" else "confirmed_policy",
        "rules": rules,
    }
    bindings = []
    for scenario in sorted(dataset["tables"]["scenario_catalogue"], key=lambda row: row["scenario_id"]):
        is_bound = scenario["scenario_id"] == policy["scope"]
        bindings.append(
            {
                "scenario_id": scenario["scenario_id"],
                "policy_id": policy_id if is_bound else None,
                "status": "bound" if is_bound else "unbound",
            }
        )
    return {
        "version": ARTIFACT_VERSIONS["policy_bindings"],
        "ontology_version": "ontology-v1",
        "policies": [policy_record],
        "scenario_bindings": bindings,
    }


def _supporting_event_ids(value):
    ids = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"supporting_event_ids", "duplicate_candidates", "retry_candidates"}:
                ids.update(child)
            else:
                ids.update(_supporting_event_ids(child))
    elif isinstance(value, list):
        for child in value:
            ids.update(_supporting_event_ids(child))
    return sorted(ids)


def build_scenario_checkpoints(dataset, snapshot, index, policy_bindings, policy):
    """Materialize static, exclusive-cutoff context for every test attempt."""
    policy_id = f"PolicyVersion:{policy['version']}"
    binding_by_scenario = {
        binding["scenario_id"]: binding for binding in policy_bindings["scenario_bindings"]
    }
    checkpoints = []
    attempts = sorted(
        dataset["tables"]["purchase_attempts"],
        key=lambda row: (row["scenario_id"], row["replay_order"], row["authorization_id"]),
    )
    for attempt in attempts:
        binding = binding_by_scenario[attempt["scenario_id"]]
        applied_policy = policy if binding["policy_id"] == policy_id else None
        context = get_transaction_context(attempt, snapshot, dataset, index, policy=applied_policy)
        graph_node_ids = {f"PurchaseAttempt:{attempt['authorization_id']}"}
        graph_node_ids.update(edge["target"] for edge in context["overlay"]["relationships"])
        checkpoints.append(
            {
                "id": f"ScenarioCheckpoint:{attempt['authorization_id']}",
                "authorization_id": attempt["authorization_id"],
                "scenario_id": attempt["scenario_id"],
                "replay_order": attempt["replay_order"],
                "as_of": attempt["timestamp"],
                "snapshot_id": snapshot["snapshot_id"],
                "calculation_version": ARTIFACT_VERSIONS["precomputed_evidence"],
                "policy_id": binding["policy_id"],
                "policy_binding_status": binding["status"],
                "graph_node_ids": sorted(graph_node_ids),
                "supporting_event_ids": _supporting_event_ids(context["historical_evidence"]),
                "historical_evidence": context["historical_evidence"],
                "semantic_matches": context["semantic_matches"],
                "missing_evidence": context["missing_evidence"],
            }
        )
    return {
        "version": ARTIFACT_VERSIONS["scenario_checkpoints"],
        "snapshot_id": snapshot["snapshot_id"],
        "calculation_version": ARTIFACT_VERSIONS["precomputed_evidence"],
        "checkpoints": checkpoints,
    }