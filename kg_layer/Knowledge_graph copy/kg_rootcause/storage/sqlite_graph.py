"""Embedded, queryable storage for the precomputed knowledge graph."""
import argparse
from collections import deque
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    properties_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL
);
CREATE INDEX nodes_type_idx ON nodes(type);
CREATE TABLE relationships (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES nodes(id),
    target_id TEXT NOT NULL REFERENCES nodes(id),
    provenance_json TEXT NOT NULL
);
CREATE INDEX relationships_source_idx ON relationships(source_id);
CREATE INDEX relationships_target_idx ON relationships(target_id);
CREATE INDEX relationships_type_idx ON relationships(type);
CREATE TABLE aggregate_views (
    name TEXT NOT NULL,
    key_json TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    PRIMARY KEY (name, key_json)
);
CREATE INDEX aggregate_views_name_idx ON aggregate_views(name);
CREATE TABLE policy_versions (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    scope TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_kind TEXT NOT NULL
);
CREATE TABLE policy_rules (
    id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES policy_versions(id),
    classification TEXT NOT NULL,
    operator TEXT NOT NULL,
    value_json TEXT NOT NULL,
    target_concept TEXT NOT NULL,
    dataset_field TEXT NOT NULL,
    evidence_definition TEXT,
    window_days INTEGER
);
CREATE INDEX policy_rules_policy_idx ON policy_rules(policy_id);
CREATE TABLE scenario_policy_bindings (
    scenario_id TEXT PRIMARY KEY,
    policy_id TEXT REFERENCES policy_versions(id),
    status TEXT NOT NULL
);
CREATE TABLE scenario_checkpoints (
    id TEXT PRIMARY KEY,
    authorization_id TEXT NOT NULL UNIQUE,
    scenario_id TEXT NOT NULL,
    replay_order INTEGER NOT NULL,
    as_of TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    policy_id TEXT REFERENCES policy_versions(id),
    policy_binding_status TEXT NOT NULL,
    historical_evidence_json TEXT NOT NULL,
    semantic_matches_json TEXT NOT NULL,
    missing_evidence_json TEXT NOT NULL
);
CREATE INDEX scenario_checkpoints_scenario_idx ON scenario_checkpoints(scenario_id, replay_order);
CREATE TABLE checkpoint_graph_nodes (
    checkpoint_id TEXT NOT NULL REFERENCES scenario_checkpoints(id),
    node_id TEXT NOT NULL REFERENCES nodes(id),
    PRIMARY KEY (checkpoint_id, node_id)
);
CREATE TABLE checkpoint_supporting_events (
    checkpoint_id TEXT NOT NULL REFERENCES scenario_checkpoints(id),
    authorization_id TEXT NOT NULL,
    PRIMARY KEY (checkpoint_id, authorization_id)
);
"""


def persist_graph_store(path, snapshot, evidence, policy_bindings, checkpoints, manifest):
    """Atomically persist raw graph data and derived precomputed artifacts."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = None
    try:
        connection = sqlite3.connect(temporary)
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO nodes VALUES (?, ?, ?, ?)",
            [
                (node["id"], node["type"], _json(node["properties"]), _json(node["provenance"]))
                for node in snapshot["nodes"]
            ],
        )
        connection.executemany(
            "INSERT INTO relationships VALUES (?, ?, ?, ?, ?)",
            [
                (
                    relationship["id"],
                    relationship["type"],
                    relationship["source"],
                    relationship["target"],
                    _json(relationship["provenance"]),
                )
                for relationship in snapshot["relationships"]
            ],
        )
        connection.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [
                ("snapshot_id", _json(snapshot["snapshot_id"])),
                ("manifest", _json(manifest)),
                ("evidence_as_of", _json(evidence["as_of"])),
                ("evidence_calculation_version", _json(evidence["calculation_version"])),
                ("policy_bindings_version", _json(policy_bindings["version"])),
                ("scenario_checkpoints_version", _json(checkpoints["version"])),
            ],
        )
        aggregate_rows = []
        for name, summaries in evidence["aggregates"].items():
            for summary in summaries:
                aggregate_rows.append((name, _json(summary["key"]), _json(summary)))
        connection.executemany("INSERT INTO aggregate_views VALUES (?, ?, ?)", aggregate_rows)
        connection.executemany(
            "INSERT INTO policy_versions VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    policy["id"],
                    policy["version"],
                    policy["status"],
                    policy["scope"],
                    policy["content_hash"],
                    policy["source_kind"],
                )
                for policy in policy_bindings["policies"]
            ],
        )
        rule_rows = []
        for policy in policy_bindings["policies"]:
            for rule in policy["rules"]:
                rule_rows.append(
                    (
                        rule["id"],
                        policy["id"],
                        rule["classification"],
                        rule["operator"],
                        _json(rule["value"]),
                        rule["target_concept"],
                        rule["dataset_field"],
                        rule["evidence_definition"],
                        rule.get("window_days"),
                    )
                )
        connection.executemany("INSERT INTO policy_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rule_rows)
        connection.executemany(
            "INSERT INTO scenario_policy_bindings VALUES (?, ?, ?)",
            [
                (binding["scenario_id"], binding["policy_id"], binding["status"])
                for binding in policy_bindings["scenario_bindings"]
            ],
        )
        connection.executemany(
            "INSERT INTO scenario_checkpoints VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    checkpoint["id"],
                    checkpoint["authorization_id"],
                    checkpoint["scenario_id"],
                    checkpoint["replay_order"],
                    checkpoint["as_of"],
                    checkpoint["snapshot_id"],
                    checkpoint["calculation_version"],
                    checkpoint["policy_id"],
                    checkpoint["policy_binding_status"],
                    _json(checkpoint["historical_evidence"]),
                    _json(checkpoint["semantic_matches"]),
                    _json(checkpoint["missing_evidence"]),
                )
                for checkpoint in checkpoints["checkpoints"]
            ],
        )
        connection.executemany(
            "INSERT INTO checkpoint_graph_nodes VALUES (?, ?)",
            [
                (checkpoint["id"], node_id)
                for checkpoint in checkpoints["checkpoints"]
                for node_id in checkpoint["graph_node_ids"]
            ],
        )
        connection.executemany(
            "INSERT INTO checkpoint_supporting_events VALUES (?, ?)",
            [
                (checkpoint["id"], authorization_id)
                for checkpoint in checkpoints["checkpoints"]
                for authorization_id in checkpoint["supporting_event_ids"]
            ],
        )
        connection.commit()
        connection.execute("VACUUM")
    except Exception:
        if connection is not None:
            connection.rollback()
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if connection is not None:
            connection.close()
    temporary.replace(path)


class GraphStore:
    """Read-only graph queries over a persisted precomputed graph."""

    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def summary(self):
        with self._connection() as connection:
            counts = {
                "node_count": connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
                "relationship_count": connection.execute("SELECT COUNT(*) FROM relationships").fetchone()[0],
                "aggregate_count": connection.execute("SELECT COUNT(*) FROM aggregate_views").fetchone()[0],
                "checkpoint_count": connection.execute("SELECT COUNT(*) FROM scenario_checkpoints").fetchone()[0],
                "policy_count": connection.execute("SELECT COUNT(*) FROM policy_versions").fetchone()[0],
            }
            snapshot_id = json.loads(
                connection.execute("SELECT value_json FROM metadata WHERE key = 'snapshot_id'").fetchone()[0]
            )
        return {"path": str(self.path), "snapshot_id": snapshot_id, **counts}

    def node(self, node_id):
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "type": row["type"],
            "properties": json.loads(row["properties_json"]),
            "provenance": json.loads(row["provenance_json"]),
        }

    def neighbors(self, node_id, direction="both"):
        if direction not in {"in", "out", "both"}:
            raise ValueError("direction must be in, out, or both")
        queries = []
        if direction in {"out", "both"}:
            queries.append(
                ("out", "SELECT id, type, source_id, target_id FROM relationships WHERE source_id = ?", node_id)
            )
        if direction in {"in", "both"}:
            queries.append(
                ("in", "SELECT id, type, source_id, target_id FROM relationships WHERE target_id = ?", node_id)
            )
        results = []
        with self._connection() as connection:
            for relationship_direction, query, parameter in queries:
                for row in connection.execute(query, (parameter,)):
                    results.append(
                        {
                            "id": row["id"],
                            "type": row["type"],
                            "source": row["source_id"],
                            "target": row["target_id"],
                            "direction": relationship_direction,
                        }
                    )
        return sorted(results, key=lambda relationship: relationship["id"])

    def _neighbor_ids(self, node_id):
        for relationship in self.neighbors(node_id):
            yield relationship["target"] if relationship["source"] == node_id else relationship["source"]

    @staticmethod
    def _reconstruct_path(parents, target_id):
        path = [target_id]
        while parents[path[-1]] is not None:
            path.append(parents[path[-1]])
        return list(reversed(path))

    def shortest_path(self, source_id, target_id, max_depth=6):
        if max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        if source_id == target_id:
            return [source_id] if self.node(source_id) else None
        frontier = deque([(source_id, 0)])
        parents = {source_id: None}
        while frontier:
            current, depth = frontier.popleft()
            if depth >= max_depth:
                continue
            for neighbor in self._neighbor_ids(current):
                if neighbor in parents:
                    continue
                parents[neighbor] = current
                if neighbor == target_id:
                    return self._reconstruct_path(parents, target_id)
                frontier.append((neighbor, depth + 1))
        return None


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Query the offline precomputed knowledge graph store")
    parser.add_argument("command", choices=("summary", "node", "neighbors", "path"))
    parser.add_argument("--db", type=Path, default=root / "build/knowledge_graph.sqlite")
    parser.add_argument("--node-id")
    parser.add_argument("--source-id")
    parser.add_argument("--target-id")
    parser.add_argument("--direction", choices=("in", "out", "both"), default="both")
    parser.add_argument("--max-depth", type=int, default=6)
    args = parser.parse_args()
    store = GraphStore(args.db)
    if args.command == "summary":
        result = store.summary()
    elif args.command == "node":
        if not args.node_id:
            parser.error("node requires --node-id")
        result = store.node(args.node_id)
    elif args.command == "neighbors":
        if not args.node_id:
            parser.error("neighbors requires --node-id")
        result = store.neighbors(args.node_id, args.direction)
    else:
        if not args.source_id or not args.target_id:
            parser.error("path requires --source-id and --target-id")
        result = store.shortest_path(args.source_id, args.target_id, args.max_depth)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()