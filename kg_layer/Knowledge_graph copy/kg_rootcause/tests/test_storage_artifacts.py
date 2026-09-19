from pathlib import Path
import unittest

from kg_rootcause.common import timestamp
from kg_rootcause.ingestion import load_dataset
from kg_rootcause.paths import dataset_directory
from kg_rootcause.precompute import EvidenceIndex
from kg_rootcause.precompute.artifacts import (
    build_dataset_manifest,
    build_policy_bindings,
    build_scenario_checkpoints,
)
from kg_rootcause.precompute.graph import build_knowledge
from kg_rootcause.semantic import baseline_policy


DATA = dataset_directory(__file__)


class StorageArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset, _ = load_dataset(DATA)
        cls.snapshot = build_knowledge(cls.dataset)
        cls.index = EvidenceIndex(cls.dataset)
        cls.policy = baseline_policy()
        cls.bindings = build_policy_bindings(cls.dataset, cls.policy)
        cls.checkpoints = build_scenario_checkpoints(
            cls.dataset, cls.snapshot, cls.index, cls.bindings, cls.policy
        )

    def test_manifest_hashes_the_test_data_release(self):
        manifest = build_dataset_manifest(DATA, self.dataset, self.snapshot)
        self.assertEqual(manifest["snapshot_id"], self.snapshot["snapshot_id"])
        self.assertEqual(len(manifest["source_release_id"]), 64)
        self.assertEqual(sum(entry["path"].endswith(".csv") for entry in manifest["source_files"]), 11)
        self.assertTrue(all(len(entry["sha256"]) == 64 for entry in manifest["source_files"]))

    def test_policy_binds_only_to_its_scenario(self):
        bindings = {binding["scenario_id"]: binding for binding in self.bindings["scenario_bindings"]}
        self.assertEqual(bindings["SCEN0001"]["status"], "bound")
        self.assertEqual(bindings["SCEN0001"]["policy_id"], "PolicyVersion:simulation-scen0001-v1")
        self.assertTrue(all(binding["status"] == "unbound" for scenario, binding in bindings.items() if scenario != "SCEN0001"))
        self.assertEqual(self.bindings["policies"][0]["status"], "simulation_assumption")

    def test_checkpoints_cover_all_attempts_without_future_evidence(self):
        checkpoints = self.checkpoints["checkpoints"]
        self.assertEqual(len(checkpoints), len(self.dataset["tables"]["purchase_attempts"]))
        graph_ids = {node["id"] for node in self.snapshot["nodes"]}
        history = self.dataset["indexes"]["authorization_history"]
        for checkpoint in checkpoints:
            self.assertTrue(set(checkpoint["graph_node_ids"]).issubset(graph_ids))
            self.assertTrue(all(timestamp(history[event_id]["timestamp"]) < timestamp(checkpoint["as_of"]) for event_id in checkpoint["supporting_event_ids"]))
        bound = [checkpoint for checkpoint in checkpoints if checkpoint["scenario_id"] == "SCEN0001"]
        self.assertEqual(len(bound), 10)
        self.assertTrue(all(checkpoint["policy_binding_status"] == "bound" for checkpoint in bound))


if __name__ == "__main__":
    unittest.main()