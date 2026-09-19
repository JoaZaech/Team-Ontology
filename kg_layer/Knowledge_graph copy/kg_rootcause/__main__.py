import argparse
from pathlib import Path
from .common import write_json
from .frontend_contract.viewer import render_viewer
from .ingestion import load_dataset, DataQualityError
from .precompute import EvidenceIndex, precompute_summaries
from .precompute.artifacts import build_dataset_manifest, build_policy_bindings, build_scenario_checkpoints
from .precompute.graph import build_knowledge, validate_graph
from .paths import dataset_directory
from .schema import validate
from .semantic import ONTOLOGY, baseline_policy, compile_semantics
from .simulation import simulate, build_report
from .storage import persist_graph_store


def main():
    parser = argparse.ArgumentParser(description="Build and audit the SCEN0001 knowledge-graph baseline")
    graph_root = Path(__file__).resolve().parent.parent
    parser.add_argument("--data", type=Path, default=dataset_directory(__file__))
    parser.add_argument("--output", type=Path, default=graph_root / "build")
    args = parser.parse_args()
    try:
        dataset, quality = load_dataset(args.data)
    except DataQualityError as exc:
        write_json(args.output / "data_quality_report.json", exc.report)
        raise SystemExit("Dataset rejected; see data_quality_report.json")
    write_json(args.output / "data_quality_report.json", quality)
    snapshot = validate("KnowledgeSnapshot", build_knowledge(dataset))
    graph_report = validate_graph(snapshot, dataset)
    write_json(args.output / "graph_validation_report.json", graph_report)
    if not graph_report["valid"]:
        raise SystemExit("Graph rejected")
    write_json(args.output / "source_graph.json", snapshot)
    write_json(args.output / "ontology.json", ONTOLOGY)
    instruction = dataset["indexes"]["scenario_catalogue"]["SCEN0001"]["cardholder_instruction"]
    write_json(args.output / "semantic_policy_draft.json", validate("SemanticPolicyDraft", compile_semantics(instruction)))
    evidence = precompute_summaries(dataset)
    write_json(args.output / "precomputed_evidence.json", evidence)
    index = EvidenceIndex(dataset)
    # Reusable time-indexed source evidence, never precomputed fixture outcomes.
    write_json(args.output / "historical_evidence_index.json", dict(index.by_card))
    policy = baseline_policy()
    bindings = build_policy_bindings(dataset, policy)
    write_json(args.output / "policy_bindings.json", bindings)
    checkpoints = build_scenario_checkpoints(dataset, snapshot, index, bindings, policy)
    write_json(args.output / "scenario_checkpoints.json", checkpoints)
    manifest = build_dataset_manifest(args.data, dataset, snapshot)
    write_json(args.output / "dataset_manifest.json", manifest)
    persist_graph_store(args.output / "knowledge_graph.sqlite", snapshot, evidence, bindings, checkpoints, manifest)
    requests = sorted((r for r in dataset["tables"]["purchase_attempts"] if r["scenario_id"] == "SCEN0001"), key=lambda r: r["replay_order"])
    first, telemetry = simulate(requests, dataset, snapshot, index, policy)
    second, replay_telemetry = simulate(requests, dataset, snapshot, index, policy)
    report = build_report(first, second, telemetry, dataset, snapshot, policy)
    for name, value in [("simulation_results", first), ("replay_results", second), ("latency", telemetry), ("replay_latency", replay_telemetry), ("baseline_report", report)]:
        write_json(args.output / (name + ".json"), value)
    render_viewer(first, args.output / "evidence_viewer.html")
    lines = ["# SCEN0001 baseline", "", "Simulation policy only; no expected decisions are supplied by the dataset.", "", "| Metric | Result |", "| --- | --- |"]
    lines += [f"| {k} | {v:.3f} |" if isinstance(v, float) else f"| {k} | {v} |" for k, v in report.items() if isinstance(v, (int, float, bool))]
    lines += ["", "## Decisions", "", "| Request | Decision | Cause |", "| --- | --- | --- |"]
    lines += [f"| {r['input']['authorization_id']} | {r['KG_Rootcause']['decision']} | {', '.join(r['KG_Rootcause']['decision_cause']['rules'])} |" for r in first]
    lines += ["", "## Limitations", ""] + ["- " + line for line in report["limitations"]] + ["", report["replay_comparison"]]
    (args.output / "baseline_report.md").write_text("\n".join(lines) + "\n")
    print(f"Baseline {'PASS' if report['baseline_passed'] else 'FAIL'}: {report['approve_count']} approve, {report['step_up_count']} step-up, {report['decline_count']} decline; replay {report['deterministic_replay_percent']}%")
    print(f"Artifacts: {args.output.resolve()}")
    if not report["baseline_passed"]:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
