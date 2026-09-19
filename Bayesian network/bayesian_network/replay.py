"""Offline chronological fixture replay; historical outcomes are comparison fields only."""
import argparse
from collections import Counter, defaultdict
import json
import math
import time
from pathlib import Path
from . import ROOT
from .configuration import load
from .evidence import make_fact
from .policy import DecisionService, normalize
from .receipts import ReceiptStore
from .reporting import render
from kg_rootcause.common import digest, timestamp
from kg_rootcause.ingestion import load_dataset
from kg_rootcause.precompute import EvidenceIndex
from kg_rootcause.precompute.graph import build_knowledge
from kg_rootcause.context import get_transaction_context
from kg_rootcause.simulation import apply_decision, initial_state
from kg_rootcause.simulation.guardrail import simulate_checks
from kg_rootcause.semantic import baseline_policy


def request_for(row, customer, country, run):
    return normalize(dict(tenant='fixture',run=run,idempotency_key=row['authorization_id'],transaction_id=row['authorization_id'],
        customer_id=customer,card_id=row['card_id'],merchant_id=row['merchant_id'],country=country,
        channel=row['channel'],device_id=row.get('customer_device_id'),amount_cents=row['billing_amount_chf'],
        transaction_time=row['timestamp'],decision_time=row['timestamp'],mode='synthetic_retrospective',authority_id=row.get('authority_id')))


def coverage_for(request,start):
    return dict(available=True,**{k:request[k] for k in ('tenant','run','card_id','customer_id')},start=start,
        through=request['transaction_time'],known_at=request['decision_time'],known_at_basis='assumed_event_time',
        completeness_basis='synthetic fixture assumed complete; not certified ingestion coverage')


def rule_contract(request, checks, version):
    return dict(version=version,request_hash=digest(request),checks=checks)


def compact(receipt,original=None):
    snap=receipt.get('snapshot') or {};analysis=receipt.get('analysis')
    return {'id':receipt['request']['transaction_id'],'card':receipt['request']['card_id'],'merchant':receipt['request']['merchant_id'],
        'time':receipt['request']['transaction_time'],'run':receipt['request']['run'],'original_outcome':original,
        'decision':receipt['decision'],'reason':receipt['reason'],'analysis':analysis,
        'features':{k:{a:b for a,b in v.items() if a!='support_ids'} for k,v in snap.get('features',{}).items()},
        'sources':[p['id'] for p in snap.get('provenance',[])],
        'snapshot_id':snap.get('snapshot_id'),'receipt_hash':receipt.get('receipt_hash'),'scope':receipt['scope'],
        'rule_failures':receipt.get('rule_failures',[])}


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    dataset,quality=load_dataset(ROOT.parent/'viseca-2026/data')
    config=load()
    database=output/('receipts-'+str(time.time_ns())+'.sqlite')
    store=ReceiptStore(database);service=DecisionService(store,config)
    independent_store=ReceiptStore(':memory:');independent=DecisionService(independent_store,config)
    bycard=defaultdict(list)
    history=sorted(dataset['tables']['authorization_history'],key=lambda r:(timestamp(r['timestamp']),r['authorization_id']))
    start=history[0]['timestamp'];rows=[];latencies=[];stable=0;recomputed=0;leaks=0;paths=0;invalid_paths=0
    graph=build_knowledge(dataset)
    graph_links={(e['source'],e['type'],e['target']) for e in graph['relationships']}
    # All source outcomes (approved/declined, purchase/refund/cash) can supply prior context.
    for row in history:bycard[row['card_id']].append(make_fact(row,run='historical'))
    def record(request,rules,facts,coverage,original=None):
        nonlocal stable,recomputed,leaks,paths,invalid_paths
        receipt,telemetry=service.decide(request,rules,facts,coverage)
        retry,_=service.decide(request,rules,facts,coverage)
        stable+=receipt==retry
        fresh,_=independent.decide(request,rules,facts,coverage)
        recomputed+=receipt==fresh
        for p in (receipt.get('snapshot') or {}).get('provenance',[]):
            leaks+=timestamp(p['event_time'])>=timestamp(request['transaction_time']) or timestamp(p['known_at'])>timestamp(request['decision_time'])
            paths+=1
            source=('Authorization:' if p['id'].startswith('TR') else 'PurchaseAttempt:')+p['id']
            invalid_paths+=((source,'ON_CARD','Card:'+p['graph_path'][0]) not in graph_links or (source,'AT_MERCHANT','Merchant:'+p['graph_path'][2]) not in graph_links)
        rows.append(compact(receipt,original));latencies.append(telemetry['elapsed_seconds']*1000)
        return receipt
    for row in history:
        if row['transaction_type']!='purchase':continue
        request=request_for(row,row['customer_id'],row['merchant_country'],'historical')
        rules=rule_contract(request,[dict(id='analytical_eligibility_assumption',result='pass')],'historical-analysis-only-1')
        record(request,rules,bycard[row['card_id']],coverage_for(request,start),row['status'])
    graph=build_knowledge(dataset);index=EvidenceIndex(dataset);states={}
    for row in sorted(dataset['tables']['purchase_attempts'],key=lambda r:(r['scenario_id'],timestamp(r['timestamp']),r['authorization_id'])):
        scenario=row['scenario_id'];state=states.setdefault(scenario,initial_state())
        authority=dataset['indexes']['scenario_authorities'][row['authority_id']]
        merchant=dataset['indexes']['merchants'][row['merchant_id']]
        request=request_for(row,authority['customer_id'],merchant['merchant_country'],scenario)
        if scenario=='SCEN0001':
            policy=baseline_policy();context=get_transaction_context(row,graph,dataset,index,state['events'],policy)
            checks=[dict(id=c['rule'],result=c['status']) for c in simulate_checks(row,policy,context,state) if c['kind']=='hard']
            version=policy['version']
        else:
            checks=[dict(id='scenario_mandate_not_compiled',result='unknown')];version='unavailable-scenario-policy-1'
        facts=[dict(f,run=scenario) for f in bycard[row['card_id']]]
        facts += [make_fact(e,run=scenario) for e in state['events']]
        receipt=record(request,rule_contract(request,checks,version),facts,coverage_for(request,start))
        apply_decision(state,row,receipt['decision'],dataset)
    historical=[r for r in rows if r['run']=='historical'];modeled=[r for r in rows if r['analysis']]
    latency=sorted(latencies)
    summary={'version':'replay-1','config_hash':digest(config),'mode':'synthetic_retrospective',
        'historical_purchase_count':len(historical),'unscored_nonpurchase_count':len(history)-len(historical),
        'historical_original_outcomes':dict(Counter(r['original_outcome'] for r in historical)),
        'historical_recommendations':dict(Counter(r['decision'] for r in historical)),
        'scenario_recommendations':dict(Counter(r['decision'] for r in rows if r['run']!='historical')),
        'reasons':dict(Counter(r['reason'] for r in rows)),'modeled_count':len(modeled),
        'sensitivity_changes':sum(r['analysis']['recommendation_changes'] for r in modeled),
        'independent_recomputation_matches':recomputed,'invalid_graph_paths':invalid_paths,'receipt_database':database.name,
        'same_key_replay_matches':stable,'request_count':len(rows),'temporal_violations':leaks,'provenance_paths_checked':paths,
        'latency_ms':{'median':latency[len(latency)//2],'p95':latency[math.ceil(len(latency)*.95)-1],'maximum':max(latency)},
        'limitations':['Expert probabilities, not calibrated fraud scores or historical decline reasons.',
        'Fixture known_at and coverage are assumptions.', 'Historical rule eligibility is an analytical assumption.',
        'SCEN0001 uses the existing simulation hard policy; other scenario mandates are unavailable and step up.',
        'Historical cash/refunds supply context but only purchase requests are scored.',
        'Durable complete receipts are in the named local SQLite file; this report contains portable compact explanations.']}
    report={'summary':summary,'config':config,'rows':rows}
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    render(report,output/'index.html')
    store.db.close();independent_store.db.close()
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'build')
    run(parser.parse_args().output)
