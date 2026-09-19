"""Versioned, scoped temporal facts; reuse graph summaries after eligibility filtering."""
from datetime import timedelta
from kg_rootcause.common import timestamp, digest
from kg_rootcause.precompute import summary

FEATURE_SPEC = {'version': 'features-1', 'min_approved_purchases': 5, 'window_days': 90,
                'min_coverage_days': 7, 'velocity_minutes': 10, 'velocity_count': 3,
                'amount_p95_multiplier': 1.5, 'required': ['merchant', 'amount', 'country', 'velocity'],
                'optional': ['device'], 'freshness_seconds': 0}
STATES = {'observed', 'observed_novelty', 'history_unavailable', 'insufficient_history', 'not_applicable'}


def make_fact(row, tenant='fixture', run='history', known_at=None, version=1):
    return {'id': row['authorization_id'], 'version': version, 'tenant': tenant, 'run': run,
            'event_time': row['timestamp'], 'known_at': known_at or row['timestamp'],
            'known_at_basis': 'actual_ingestion' if known_at else 'assumed_event_time', 'row': dict(row)}


def eligible(facts, request):
    identities = {}
    for fact in facts:
        if fact['tenant'] != request['tenant'] or fact['run'] != request['run']:
            continue
        key = (fact['id'], fact['version'])
        if key in identities and identities[key] != digest(fact):
            raise ValueError('conflicting immutable fact version')
        identities[key] = digest(fact)
        if fact['id'] != fact['row']['authorization_id'] or timestamp(fact['event_time']) != timestamp(fact['row']['timestamp']):
            raise ValueError('inconsistent source identity/time')
        if fact['known_at_basis'] not in ('actual_ingestion', 'assumed_event_time') or type(fact['version']) is not int or fact['version'] < 1:
            raise ValueError('invalid fact version/provenance')
    # Choose the latest version known at decision time BEFORE evaluating its event time.
    latest = {}
    for fact in facts:
        if fact['tenant'] != request['tenant'] or fact['run'] != request['run']:
            continue
        if timestamp(fact['known_at']) > timestamp(request['decision_time']):
            continue
        previous = latest.get(fact['id'])
        if previous is None or (timestamp(fact['known_at']), fact['version']) > (timestamp(previous['known_at']), previous['version']):
            latest[fact['id']] = fact
    start = timestamp(request['transaction_time']) - timedelta(days=FEATURE_SPEC['window_days'])
    return sorted([f for f in latest.values() if f['row']['card_id'] == request['card_id']
                   and f['row']['customer_id'] == request['customer_id']
                   and start <= timestamp(f['event_time']) < timestamp(request['transaction_time'])],
                  key=lambda f: (timestamp(f['event_time']), f['id'], f['version']))


def static_at(versions, event_time, decision_time):
    matches = [v for v in versions if timestamp(v['known_at']) <= timestamp(decision_time)
               and timestamp(v['effective_from']) <= timestamp(event_time)
               and (v.get('effective_to') is None or timestamp(event_time) < timestamp(v['effective_to']))]
    return max(matches, key=lambda v: (timestamp(v['known_at']), v['version'])) if matches else None


def snapshot(facts, request, coverage):
    available = coverage.get('available', False)
    if available:
        # Coverage is scoped evidence too, not an untrusted global boolean.
        available = all(coverage.get(k) == request[k] for k in ('tenant', 'run', 'card_id', 'customer_id'))
        available = available and timestamp(coverage['known_at']) <= timestamp(request['decision_time'])
        available = available and timestamp(coverage['through']) <= timestamp(request['decision_time'])
        available = available and 0 <= (timestamp(request['transaction_time'])-timestamp(coverage['through'])).total_seconds() <= FEATURE_SPEC['freshness_seconds']
    selected = [f for f in eligible(facts, request) if timestamp(f['event_time']) >= timestamp(coverage['start'])] if available else []
    rows = [f['row'] for f in selected]
    aggregate = summary(rows, request['transaction_time'])
    purchases = [r for r in rows if r['status'] == 'approved' and r['transaction_type'] == 'purchase']
    window_start = timestamp(request['transaction_time'])-timedelta(days=FEATURE_SPEC['window_days'])
    coverage_days = max(0, (timestamp(request['transaction_time'])-max(timestamp(coverage['start']), window_start)).total_seconds()/86400) if available else 0
    enough = len(purchases) >= FEATURE_SPEC['min_approved_purchases'] and coverage_days >= FEATURE_SPEC['min_coverage_days']
    missing = 'history_unavailable' if not available else 'insufficient_history'
    definitions = {'merchant': ('merchant_id', request['merchant_id']),
                   'country': ('merchant_country', request['country']),
                   'device': ('customer_device_id', request.get('device_id'))}
    features = {}
    support = [{'id': f['id'], 'version': f['version'], 'hash': digest(f), 'event_time': f['event_time'],
                'known_at': f['known_at'], 'known_at_basis': f['known_at_basis'],
                'graph_path': [request['card_id'], f['id'], f['row']['merchant_id']]} for f in selected]
    for name in ('merchant', 'amount', 'country', 'velocity', 'device'):
        value, state = None, missing
        if name == 'device' and request['channel'] in ('in_store', 'atm'):
            state = 'not_applicable'
        elif name == 'device' and not request.get('device_id'):
            state = 'history_unavailable'
        elif enough:
            state = 'observed'
            if name in definitions:
                field, match = definitions[name]
                value = int(not any(r.get(field) == match for r in purchases))
                if value:
                    state = 'observed_novelty'
            elif name == 'amount':
                value = int(request['amount_cents'] > aggregate['amount_p95_cents'] * FEATURE_SPEC['amount_p95_multiplier'])
            else:
                start = timestamp(request['transaction_time'])-timedelta(minutes=FEATURE_SPEC['velocity_minutes'])
                value = int(sum(timestamp(r['timestamp']) >= start for r in rows) >= FEATURE_SPEC['velocity_count'])
        features[name] = {'value': value, 'state': state, 'sample_size': len(purchases), 'coverage_days': coverage_days,
                          'reason': None if value is not None else state, 'support_ids': [f['id'] for f in selected]}
    payload = {'features': features, 'provenance': support, 'coverage': coverage,
               'transaction_time': request['transaction_time'], 'decision_time': request['decision_time'],
               'scope': {k: request[k] for k in ('tenant', 'run', 'card_id', 'customer_id')},
               'feature_spec': FEATURE_SPEC, 'feature_hash': digest(FEATURE_SPEC),
               'mode': request['mode'], 'summary': aggregate}
    return dict(payload, snapshot_id=digest(payload))
