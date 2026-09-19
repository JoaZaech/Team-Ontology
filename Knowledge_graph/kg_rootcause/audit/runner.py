"""Validate stored graphs/aggregates and audit all historical declines."""
from collections import Counter
import json
from ..common import timestamp
from ..ingestion import load_dataset
from ..precompute import EvidenceIndex, precompute_summaries
from ..precompute.graph import build_knowledge, validate_graph
from .factors import LABELS
from .tracing import trace

def run_audit(data_dir, build_dir):
    dataset, quality = load_dataset(data_dir)
    history = sorted(dataset['tables']['authorization_history'], key=lambda r:(timestamp(r['timestamp']),r['authorization_id']))
    index = EvidenceIndex(dataset)
    source_index = dataset['indexes']['authorization_history']
    graph = json.loads((build_dir/'source_graph.json').read_text())
    stored = json.loads((build_dir/'precomputed_evidence.json').read_text())
    graph_report = validate_graph(graph, dataset)
    errors = []
    if graph != build_knowledge(dataset): errors.append('Stored source graph differs from a fresh source build')
    if stored != precompute_summaries(dataset): errors.append('Stored aggregate evidence differs from a fresh source build')
    if not graph_report['valid']: errors.append('Source graph validation failed')
    graph_nodes = {n['id'] for n in graph['nodes']}
    graph_edges = {(e['source'], e['type'], e['target']) for e in graph['relationships']}
    cases, factor_counts, control_counts = [], Counter(), Counter()
    for row in history:
        # Outcomes never participate in factor computation for the current event.
        result = trace(row, history)
        if row['transaction_type'] == 'purchase':
            for flag in result['flags']:
                control_counts[(flag,row['status'])] += 1
        if row['status'] != 'declined': continue
        cases.append(result)
        event_node = 'Authorization:' + row['authorization_id']
        if event_node not in graph_nodes:
            errors.append(f"Missing graph authorization {event_node}")
        for relation, target in [('ON_CARD', 'Card:' + row['card_id']), ('AT_MERCHANT', 'Merchant:' + row['merchant_id'])]:
            if (event_node, relation, target) not in graph_edges:
                errors.append(f"{event_node}: missing {relation} path")
        factor_counts.update(result['flags'])
        for ids in result['evidence'].values():
            for eid in ids:
                if eid not in source_index or timestamp(source_index[eid]['timestamp']) >= timestamp(row['timestamp']):
                    errors.append(f"{row['authorization_id']}: invalid or future evidence {eid}")
        context = index.get_context(row['card_id'],row['merchant_id'],row['customer_device_id'],row['timestamp'])
        if context['card_merchant']['approved_count'] != result['prior_approved_card_merchant_count']:
            errors.append(f"{row['authorization_id']}: merchant aggregate mismatch")
        prior_card = [source_index[eid] for eid in result['evidence']['prior_card_events']]
        for summary_name, field in [('card_device', 'customer_device_id'), ('card_category', 'merchant_category'), ('card_country', 'merchant_country')]:
            expected = sum(r['status'] == 'approved' and r['transaction_type'] == 'purchase' and r[field] == row[field] for r in prior_card) if row[field] is not None else 0
            if context[summary_name]['approved_count'] != expected:
                errors.append(f"{row['authorization_id']}: {summary_name} count mismatch")
        if context['amount_profile']['amount_p95_cents'] != result['prior_purchase_p95_cents']:
            errors.append(f"{row['authorization_id']}: amount p95 mismatch")
        if set(context['recent_attempts']['supporting_event_ids']) != set(result['evidence']['recent_card_attempts']):
            errors.append(f"{row['authorization_id']}: recent attempts mismatch")
    factors = []
    for key,label in LABELS.items():
        approved,declined = control_counts[(key,'approved')],control_counts[(key,'declined')]
        factors.append({'factor':key,'label':label,'historical_declines_with_factor':factor_counts[key], 'purchase_approvals_with_factor':approved,'purchase_declines_with_factor':declined,'purchase_decline_rate_percent':round(100*declined/(approved+declined),2) if approved+declined else None})
    report = {'smoke_test_passed':not errors,'errors':errors,'source_rows':len(history),'decline_count':len(cases),'decline_types':dict(Counter(c['transaction_type'] for c in cases)), 'assessments':dict(Counter(c['assessment'] for c in cases)), 'factors':factors,'confirmed_per_event_decline_reasons_available':0,'graph_validation':graph_report,'data_quality':quality,'definitions':[
        'Every evidence query uses timestamp < current timestamp. Equal-timestamp events are excluded.',
        'First encounter means no prior record within the supplied history; absence is not proof of no lifetime relationship.',
        'Approved purchases establish familiarity and amount baselines. Month-to-date account totals include approved refunds and cash withdrawals.',
        'Above-p95 and unseen-hour checks require at least 20 earlier approved card purchases; burst means at least 3 earlier attempts in 10 minutes. These are diagnostic thresholds, not recovered issuer logic.',
        'Foreign merchant means country != CH in this Swiss fixture. It is context, not a decline cause.',
        'Observable rule conflicts compare supplied fields; issuer enforcement and account balance are unknown. The dictionary specifically documents card-lifecycle declines, but has no per-event reason code.',
        'Factor groups overlap. Control rates use purchases only, and are descriptive associations, not causal estimates.',
        'An unexplained case is not evidence of a system error or random decline; the actual logic is unavailable.',
    ]}
    return report,cases

