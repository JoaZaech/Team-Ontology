"""Small synthetic acceptance demonstrations; test keys never leave this process."""
import json
import secrets
import time
from . import ROOT
from .configuration import load
from .evidence import make_fact
from .policy import normalize, DecisionService
from .receipts import ReceiptStore
from .human import HumanResolver
from kg_rootcause.common import digest


def demo_rules(request,failed=False):
    return {'version':'explicit-demo-policy-1','request_hash':digest(request),
            'checks':[{'id':k,'result':'fail' if failed and k=='mandatory_policy' else 'pass'}
                      for k in ('mandatory_policy','authority_active','authority_valid_at_resolution')]}


def run(output=None):
    output=output or ROOT/'build';output.mkdir(parents=True,exist_ok=True)
    store=ReceiptStore(output/('demo-'+str(time.time_ns())+'.sqlite'))
    service=DecisionService(store,load())
    request=normalize(dict(tenant='demo',run='acceptance',transaction_id='DEMO',idempotency_key='normal',
        customer_id='CU',card_id='CA',merchant_id='ME',country='CH',channel='ecommerce',device_id='D',
        amount_cents=1000,transaction_time='2026-02-01T12:00:00Z',decision_time='2026-02-01T12:00:00Z',
        mode='synthetic_retrospective',authority_id='AUTH'))
    facts=[make_fact(dict(authorization_id=f'DEMO{i}',customer_id='CU',card_id='CA',merchant_id='ME',merchant_country='CH',
        customer_device_id='D',timestamp=f'2026-01-{i+1:02d}T12:00:00Z',status='approved',transaction_type='purchase',billing_amount_chf=1000),tenant='demo',run='acceptance') for i in range(6)]
    coverage=dict(available=True,tenant='demo',run='acceptance',card_id='CA',customer_id='CU',start='2026-01-01T00:00:00Z',through=request['transaction_time'],known_at=request['decision_time'],known_at_basis='assumed_event_time')
    results={}
    for name,amount,hard,available in [('normal',1000,False,True),('unusual',100000,False,True),('hard_violation',1000,True,True),('missing_evidence',1000,False,False)]:
        r=dict(request,idempotency_key=name,amount_cents=amount)
        results[name]=service.decide(r,demo_rules(r,hard),facts,dict(coverage,available=available))[0]
    resolver=HumanResolver(store,{'CU':secrets.token_bytes(32)})
    for action in ('approve','reject','revoke'):
        r=dict(request,idempotency_key='human-'+action,amount_cents=100000)
        receipt=service.decide(r,demo_rules(r),facts,coverage)[0]
        event=dict(customer_id='CU',event_key=action,receipt_scope=receipt['scope'],request_hash=digest(r),
                   action=action,resolved_at='2026-02-01T12:01:00Z')
        results['human_'+action]=resolver.resolve(event,resolver.sign(event),demo_rules)
    r=dict(request,idempotency_key='after-revocation')
    results['after_revocation']=service.decide(r,demo_rules(r),facts,coverage)[0]
    expected={'normal':'approve','unusual':'step_up','hard_violation':'decline','missing_evidence':'step_up','after_revocation':'decline'}
    assert all(results[k]['decision']==v for k,v in expected.items())
    assert [results['human_'+k]['status'] for k in ('approve','reject','revoke')]==['approved','customer_rejected','authority_revoked']
    (output/'demonstrations.json').write_text(json.dumps(results,indent=2)+'\n')
    store.db.close()
    print('8 acceptance demonstrations passed; demonstrations.json saved.')

if __name__=='__main__':run()
