"""Rebuild the offline historical knowledge explorer from baseline outputs.

Run from Knowledge_graph:
  .venv/bin/python -m kg_rootcause.frontend_contract.explorer --output /path/explorer.html

Standalone HTML is the default; --format fragment targets in-conversation use.
Python supplies source-derived data; templates and assets own presentation.
"""
import argparse
import json
from pathlib import Path
from ..ingestion import load_dataset
from ..precompute import EvidenceIndex
from ..audit.tracing import trace
from ..reporting.html import standalone_document


def build_payload(build, data_dir):
    graph = json.loads((build / 'source_graph.json').read_text())
    aggregates = json.loads((build / 'precomputed_evidence.json').read_text())
    types = {kind: {n['properties'][field]: n['properties'] for n in graph['nodes'] if n['type'] == kind} for kind, field in [('Customer', 'customer_id'), ('Account', 'account_id'), ('Card', 'card_id'), ('Merchant', 'merchant_id')]}
    cards = {}
    for cid, card in types['Card'].items():
        account = types['Account'][card['account_id']]
        customer = types['Customer'][account['customer_id']]
        cards[cid] = [card['account_id'], account['customer_id'], customer['persona_name'], card['card_purpose']]
    fields = ['key', 'approved_count', 'declined_count', 'approved_purchase_cents', 'net_approved_cents', 'amount_p50_cents', 'amount_p95_cents', 'first_approved_at', 'last_approved_at', 'supporting_event_ids']
    dataset, _ = load_dataset(data_dir)
    index = EvidenceIndex(dataset)
    declines = {}
    for row in dataset['tables']['authorization_history']:
        if row['status'] != 'declined':
            continue
        context = index.get_context(row['card_id'], row['merchant_id'], row['customer_device_id'], row['timestamp'])
        declines[row['authorization_id']] = {
            'timestamp': row['timestamp'], 'description': row['description'],
            'card_id': row['card_id'], 'merchant_id': row['merchant_id'],
            'merchant_category': row['merchant_category'], 'merchant_country': row['merchant_country'],
            'billing_cents': row['billing_amount_chf'], 'amount_cents': row['amount'], 'currency': row['currency'],
            'transaction_type': row['transaction_type'], 'channel': row['channel'],
            'initiator_type': row['initiator_type'], 'device': row['customer_device_id'],
            'card_status': row['card_status'], 'account_limit_cents': row['per_transaction_limit_chf'],
            'prior_merchant_purchases': context['card_merchant']['approved_count'],
            'prior_device_purchases': context['card_device']['approved_count'] if row['customer_device_id'] else None,
            'prior_p95_cents': context['amount_profile']['amount_p95_cents'],
            'prior_purchase_count': context['amount_profile']['approved_count'],
            'prior_attempts_10m': len(context['recent_attempts']['supporting_event_ids']),
            'prior_supporting_ids': context['card_merchant']['supporting_event_ids'],
            'decline_reason': None,
        }
    # Derive contextual findings from the same analysis used by the audit report.
    history = sorted(dataset['tables']['authorization_history'], key=lambda r: r['timestamp'])
    for aid, case in declines.items():
        result = trace(dataset['indexes']['authorization_history'][aid], history)
        if 'first_card_merchant' in result['flags']:
            other = result['evidence']['other_card_merchant_approvals']
            case['context_note'] = (
                f"At {case['timestamp']}, this was {case['card_id']}'s first recorded "
                f"encounter with {case['merchant_id']} in the supplied history. "
                f"The customer had {len(other)} earlier approved purchases at this merchant "
                f"on other cards" + (f" ({', '.join(other)})" if other else '') +
                '. This is a possible factor, NOT a confirmed decline cause. '
                'The original issuer reason is unavailable.'
            )
            case['reason_short'] = 'Possible factor: new merchant'
        else:
            case['reason_short'] = 'Reason not supplied'
    simulated = []
    for result in json.loads((build / 'simulation_results.json').read_text()):
        if result['KG_Rootcause']['decision'] != 'decline':
            continue
        t = result['input']
        simulated.append({'id': t['authorization_id'], 'card_id': t['card_id'], 'merchant_id': t['merchant_id'], 'amount': t['billing_amount_chf'], 'checks': [c for c in result['simulated_guardrail_checks'] if c['kind'] == 'hard' and c['status'] == 'fail']})
    return {'cards': cards, 'merchants': {mid: m['merchant_name'] for mid, m in types['Merchant'].items()}, 'aggregates': {k: [[r[f] for f in fields] for r in rows] for k, rows in aggregates['aggregates'].items()}, 'declines': declines, 'simulated': simulated}


def render_explorer(build, data_dir, output, *, standalone=False, authorization_id=None):
    payload = build_payload(build, data_dir)
    if authorization_id is not None and authorization_id not in payload['declines']:
        raise ValueError(f'Unknown historical decline: {authorization_id}')
    payload['focus_authorization_id'] = authorization_id
    frontend = Path(__file__).parent
    template = (frontend / 'templates/knowledge_explorer.html').read_text()
    template = template.replace('__EXPLORER_CSS__', (frontend / 'assets/explorer.css').read_text())
    template = template.replace('__EXPLORER_JS__', (frontend / 'assets/explorer.js').read_text())
    serialized = json.dumps(payload, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    fragment = template.replace('__KG_DATA__', serialized)
    if len(fragment.encode()) >= 1_000_000:
        raise ValueError('Explorer exceeds inline size limit')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(standalone_document(fragment) if standalone else fragment)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    kg = Path(__file__).resolve().parents[2]
    parser.add_argument('--build', type=Path, default=kg / 'build')
    parser.add_argument('--data', type=Path, default=kg.parent / 'viseca-2026/data')
    parser.add_argument('--output', type=Path, default=kg / 'build/precomputed-knowledge-graph.html')
    parser.add_argument('--format', choices=['standalone', 'fragment'], default='standalone')
    parser.add_argument('--authorization', help='Open directly on this historical decline, e.g. TR03359')
    args = parser.parse_args()
    payload = render_explorer(args.build, args.data, args.output, standalone=args.format == 'standalone', authorization_id=args.authorization)
    print(f"Built explorer with {len(payload['declines'])} historical declines and {len(payload['simulated'])} simulated declines: {args.output}")

if __name__ == '__main__':
    main()
