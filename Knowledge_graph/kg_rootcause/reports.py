"""Build all review pages: python -m kg_rootcause.reports [--rebuild]."""
import argparse
from pathlib import Path
import subprocess
import sys
from .audit.runner import run_audit
from .common import write_json
from .frontend_contract.explorer import render_explorer
from .reporting.declines import export


def build_reports(data_dir, build_dir, *, rebuild=False):
    """Reproduce local reports using only code and dependencies in this repository."""
    build_dir.mkdir(parents=True, exist_ok=True)
    required = ['source_graph.json', 'precomputed_evidence.json', 'simulation_results.json']
    if rebuild or any(not (build_dir / name).exists() for name in required):
        subprocess.run(
            [sys.executable, '-m', 'kg_rootcause', '--data', str(data_dir), '--output', str(build_dir)],
            check=True,
        )
    report, cases = run_audit(data_dir, build_dir)
    export(report, cases, build_dir / 'decline_audit')
    if not report['smoke_test_passed']:
        raise ValueError('Source audit failed; inspect decline_audit/decline_smoke_report.json')
    render_explorer(data_dir=data_dir, build=build_dir, output=build_dir / 'precomputed-knowledge-graph.html', standalone=True)
    render_explorer(data_dir=data_dir, build=build_dir, output=build_dir / 'tr03359-reason-review.html', standalone=True, authorization_id='TR03359')
    manifest = {
        'regenerate': 'python -m kg_rootcause.reports --rebuild',
        'outputs': {
            'precomputed-knowledge-graph.html': ['kg_rootcause/frontend_contract/explorer.py', 'kg_rootcause/frontend_contract/assets/explorer.js', 'kg_rootcause/frontend_contract/assets/explorer.css', 'kg_rootcause/frontend_contract/assets/standalone.css', 'kg_rootcause/frontend_contract/templates/knowledge_explorer.html', 'kg_rootcause/reporting/html.py'],
            'tr03359-reason-review.html': ['Same graph renderer; focus authorization TR03359'],
            'decline_audit/decline_smoke_report.html': ['kg_rootcause/audit/factors.py', 'kg_rootcause/audit/tracing.py', 'kg_rootcause/audit/runner.py', 'kg_rootcause/reporting/declines.py'],
        },
        'review_pages_tracked_in_git': True,
        'large_intermediate_graph_files_git_ignored': False,
    }
    write_json(build_dir / 'report_manifest.json', manifest)
    guide = ['# Generated reports', '', 'All generated reports and intermediate graph outputs are tracked in Git. Edit source files in ../kg_rootcause, then regenerate the pages.', '', 'From Knowledge_graph, regenerate everything with:', '', '```sh', '.venv/bin/python -m kg_rootcause.reports --rebuild', '```', '', '## Where the graph page logic lives', '', '- Data preparation: `../kg_rootcause/frontend_contract/explorer.py`', '- Graph drawing, selection, branching, reason display: `../kg_rootcause/frontend_contract/assets/explorer.js`', '- Page markup: `../kg_rootcause/frontend_contract/templates/knowledge_explorer.html`', '- Page styles: `../kg_rootcause/frontend_contract/assets/explorer.css` and `standalone.css`', '- Offline document wrapper: `../kg_rootcause/reporting/html.py`', '', 'The generated HTML embeds its data, CSS, and JavaScript. It has no external script dependency.', '', 'Open index.html for the report links. report_manifest.json maps each report to its sources.']
    (build_dir / 'README.md').write_text('\n'.join(guide) + '\n')
    (build_dir / 'index.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><title>Knowledge graph reports</title><body><h1>Knowledge graph reports</h1><ul><li><a href="precomputed-knowledge-graph.html">Precomputed graph explorer</a></li><li><a href="tr03359-reason-review.html">TR03359 timestamp review</a></li><li><a href="decline_audit/decline_smoke_report.html">All historical declines — smoke test</a></li></ul><p>Graph drawing logic: <code>../kg_rootcause/frontend_contract/assets/explorer.js</code></p><p>Data preparation: <code>../kg_rootcause/frontend_contract/explorer.py</code></p><p>Rebuild command: <code>python -m kg_rootcause.reports --rebuild</code></p></body></html>''')
    return report


def main():
    kg = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=kg.parent / 'viseca-2026/data')
    parser.add_argument('--output', type=Path, default=kg / 'build')
    parser.add_argument('--rebuild', action='store_true', help='Rebuild the graph and baseline before rendering reports')
    args = parser.parse_args()
    report = build_reports(args.data.resolve(), args.output.resolve(), rebuild=args.rebuild)
    print(f"Reports saved: {args.output.resolve() / 'index.html'}")
    print(f"Decline audit: {report['decline_count']} cases, {len(report['errors'])} errors")


if __name__ == '__main__':
    main()
