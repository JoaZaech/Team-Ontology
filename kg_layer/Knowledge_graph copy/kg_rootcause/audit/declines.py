"""CLI compatibility entry: python -m kg_rootcause.audit.declines."""
import argparse
import json
from pathlib import Path
from .tracing import trace  # Backwards-compatible public import.
from .runner import run_audit
from ..paths import dataset_directory
from ..reporting.declines import export

def main():
    root=Path(__file__).resolve().parents[2]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=dataset_directory(__file__))
    parser.add_argument('--build',type=Path,default=root/'build')
    parser.add_argument('--output',type=Path,default=root/'build/decline_audit')
    args=parser.parse_args()
    report,cases=run_audit(args.data,args.build)
    export(report,cases,args.output)
    print(json.dumps({k:report[k] for k in ['smoke_test_passed','decline_count','decline_types','assessments','errors']},indent=2))
    print('Report:',args.output/'decline_smoke_report.html')
    if not report['smoke_test_passed']:raise SystemExit(1)

if __name__=='__main__':main()
