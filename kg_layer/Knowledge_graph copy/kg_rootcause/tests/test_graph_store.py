from pathlib import Path
import sqlite3
import tempfile
import unittest

from kg_rootcause.ingestion import load_dataset
from kg_rootcause.paths import dataset_directory
from kg_rootcause.precompute import EvidenceIndex, precompute_summaries
from kg_rootcause.precompute.artifacts import (
    build_dataset_manifest,
    build_policy_bindings,
    build_scenario_checkpoints,
)
from kg_rootcause.precompute.graph import build_knowledge
from kg_rootcause.semantic import baseline_policy
from kg_rootcause.storage import GraphStore, persist_graph_store


DATA = dataset_directory(__file__)


class GraphStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset, _ = load_dataset(DATA)
        cls.snapshot = build_knowledge(cls.dataset)
        cls.evidence = precompute_summaries(cls.dataset)
        cls.policy = baseline_policy()
        cls.bindings = build_policy_bindings(cls.dataset, cls.policy)
        cls.checkpoints = build_scenario_checkpoints(
            cls.dataset, cls.snapshot, EvidenceIndex(cls.dataset), cls.bindings, cls.policy
        )
        cls.manifest = build_dataset_manifest(DATA, cls.dataset, cls.snapshot)

    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.path = Path(self.workspace.name) / "knowledge_graph.sqlite"
        persist_graph_store(
            self.path,
            self.snapshot,
            self.evidence,
            self.bindings,
            self.checkpoints,
            self.manifest,
        )
        self.store = GraphStore(self.path)

    def tearDown(self):
        self.workspace.cleanup()

    def test_persists_graph_and_precomputed_artifacts(self):
        summary = self.store.summary()
        self.assertEqual(summary["node_count"], len(self.snapshot["nodes"]))
        self.assertEqual(summary["relationship_count"], len(self.snapshot["relationships"]))
        self.assertEqual(summary["checkpoint_count"], 45)
        self.assertEqual(summary["policy_count"], 1)
        self.assertEqual(
            summary["aggregate_count"],
            sum(len(values) for values in self.evidence["aggregates"].values()),
        )

    def test_node_neighbors_and_path_are_queryable(self):
        relationship = self.snapshot["relationships"][0]
        self.assertEqual(self.store.node(relationship["source"])["id"], relationship["source"])
        self.assertIn(relationship["id"], {item["id"] for item in self.store.neighbors(relationship["source"], "out")})
        self.assertEqual(
            self.store.shortest_path(relationship["source"], relationship["target"], max_depth=1),
            [relationship["source"], relationship["target"]],
        )

    def test_policy_and_checkpoint_bindings_are_stored(self):
        connection = sqlite3.connect(self.path)
        try:
            binding = connection.execute(
                "SELECT policy_id, status FROM scenario_policy_bindings WHERE scenario_id = 'SCEN0001'"
            ).fetchone()
            unbound = connection.execute(
                "SELECT COUNT(*) FROM scenario_policy_bindings WHERE scenario_id != 'SCEN0001' AND status = 'unbound'"
            ).fetchone()[0]
            graph_links = connection.execute("SELECT COUNT(*) FROM checkpoint_graph_nodes").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(binding, ("PolicyVersion:simulation-scen0001-v1", "bound"))
        self.assertEqual(unbound, 4)
        self.assertGreater(graph_links, 45)


if __name__ == "__main__":
    unittest.main()