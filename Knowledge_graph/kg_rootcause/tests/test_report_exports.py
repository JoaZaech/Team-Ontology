"""Verify portable exports and shared, source-derived contextual explanations."""
import json
from pathlib import Path
import tempfile
import unittest
from kg_rootcause.frontend_contract.explorer import render_explorer
from kg_rootcause.reporting.html import standalone_document
from kg_rootcause.ingestion import load_dataset
from kg_rootcause.precompute import precompute_summaries
from kg_rootcause.precompute.graph import build_knowledge
from kg_rootcause.common import write_json

KG = Path(__file__).resolve().parents[2]


class ReportExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory()
        cls.build = Path(cls.workspace.name)
        dataset, _ = load_dataset(KG.parent/'viseca-2026/data')
        write_json(cls.build/'source_graph.json', build_knowledge(dataset))
        write_json(cls.build/'precomputed_evidence.json', precompute_summaries(dataset))
        write_json(cls.build/'simulation_results.json', [])

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def test_standalone_focused_report_embeds_runtime_and_data(self):
        # Works on a fresh checkout without ignored build artifacts.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'case.html'
            payload = render_explorer(self.build, KG.parent/'viseca-2026/data', output,
                                      standalone=True, authorization_id='TR03359')
            page = output.read_text()
            self.assertTrue(page.startswith('<!doctype html>'))
            self.assertIn('function draw()', page)
            self.assertIn('--red:', page)
            self.assertNotIn('__KG_DATA__', page)
            self.assertNotIn('__EXPLORER_JS__', page)
            self.assertNotIn('src="http', page)
            self.assertEqual(payload['focus_authorization_id'], 'TR03359')
            note = payload['declines']['TR03359']['context_note']
            self.assertIn('3 earlier approved purchases', note)
            self.assertIn('TR00205', note)
            self.assertIn('NOT a confirmed decline cause', note)
            self.assertIsNone(payload['declines']['TR03359']['decline_reason'])
            self.assertGreater(sum('context_note' in case for case in payload['declines'].values()), 1)

    def test_wrapper_escapes_title(self):
        page = standalone_document('<div>Graph</div>', '<script>bad</script>')
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;', page)
        self.assertNotIn('<title><script>', page)


if __name__ == '__main__':
    unittest.main()
