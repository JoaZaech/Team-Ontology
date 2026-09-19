"""Rebuild the in-conversation historical knowledge explorer from baseline outputs.

Run from Knowledge_graph:
  .venv/bin/python -m kg_rootcause.frontend_contract.explorer --output /path/explorer.html

The output is an inline fragment. The template holds layout and interaction;
Python supplies source-derived aggregates, declined records, and prior evidence.
"""
import argparse
import json
from pathlib import Path
from ..ingestion import load_dataset
from ..precompute import EvidenceIndex


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
    # Reviewed case note: preserve uncertainty and the exclusive event-time cutoff.
    case = declines.get('TR03359')
    if case:
        case['context_note'] = (
            'As of 29 April 2026, 18:35:09 UTC, this was CA0001’s first recorded '
            'interaction with RailNest (ME0006) in the supplied history. The same '
            'customer already had three approved RailNest purchases on CA0002: '
            'TR00205 (15 September 2025), TR00941 (8 November 2025), and TR01093 '
            '(19 November 2025). Merchant novelty is therefore card-specific. '
            'This is historical context, not a confirmed decline reason; '
            'first-time encounters do not automatically cause declines.'
        )
    simulated = []
    for result in json.loads((build / 'simulation_results.json').read_text()):
        if result['KG_Rootcause']['decision'] != 'decline':
            continue
        t = result['input']
        simulated.append({'id': t['authorization_id'], 'card_id': t['card_id'], 'merchant_id': t['merchant_id'], 'amount': t['billing_amount_chf'], 'checks': [c for c in result['simulated_guardrail_checks'] if c['kind'] == 'hard' and c['status'] == 'fail']})
    return {'cards': cards, 'merchants': {mid: m['merchant_name'] for mid, m in types['Merchant'].items()}, 'aggregates': {k: [[r[f] for f in fields] for r in rows] for k, rows in aggregates['aggregates'].items()}, 'declines': declines, 'simulated': simulated}


def render_explorer(build, data_dir, output):
    payload = build_payload(build, data_dir)
    template = Path(__file__).with_name('knowledge_explorer.html').read_text()
    serialized = json.dumps(payload, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    fragment = template.replace('__KG_DATA__', serialized)
    if len(fragment.encode()) >= 1_000_000:
        raise ValueError('Explorer exceeds inline size limit')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(fragment)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    kg = Path(__file__).resolve().parents[2]
    parser.add_argument('--build', type=Path, default=kg / 'build')
    parser.add_argument('--data', type=Path, default=kg.parent / 'viseca-2026/data')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    payload = render_explorer(args.build, args.data, args.output)
    print(f"Built explorer with {len(payload['declines'])} historical declines and {len(payload['simulated'])} simulated declines: {args.output}")

if __name__ == '__main__':
    main()
