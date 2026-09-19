import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bayesian_network.configuration import load, validate_config
from bayesian_network.evidence import make_fact, snapshot, eligible, static_at
from bayesian_network.inference import ExactNetwork, ModelError, analyze
from bayesian_network.policy import DecisionService, normalize
from bayesian_network.receipts import ReceiptStore, Conflict
from bayesian_network.human import HumanResolver
from kg_rootcause.common import digest


def fixture():
    request=normalize(dict(tenant='t',run='r',idempotency_key='k',transaction_id='T',customer_id='C',card_id='CA',
        merchant_id='M',country='CH',channel='ecommerce',device_id='D',amount_cents=1000,
        transaction_time='2026-02-01T12:00:00Z',decision_time='2026-02-01T12:00:00Z',mode='synthetic_retrospective',authority_id='A'))
    facts=[make_fact(dict(authorization_id=f'T{i}',customer_id='C',card_id='CA',merchant_id='M',merchant_country='CH',
        customer_device_id='D',timestamp=f'2026-01-{i+1:02d}T12:00:00Z',status='approved',transaction_type='purchase',billing_amount_chf=1000),tenant='t',run='r') for i in range(6)]
    coverage=dict(available=True,tenant='t',run='r',card_id='CA',customer_id='C',start='2026-01-01T00:00:00Z',through=request['transaction_time'],known_at=request['decision_time'],known_at_basis='assumed_event_time')
    return request,facts,coverage


def rules(request, result='pass'):
    return dict(version='test-policy-1',request_hash=digest(request),checks=[dict(id='mandatory_policy',result=result),dict(id='authority_active',result='pass'),dict(id='authority_valid_at_resolution',result='pass')])


class TemporalTests(unittest.TestCase):
    def test_exclusive_event_and_inclusive_knowledge(self):
        r,f,c=fixture()
        late=copy.deepcopy(f[0]);late['id']='late';late['row']['authorization_id']='late';late['known_at']='2026-02-02T00:00:00Z'
        equal=copy.deepcopy(f[0]);equal['id']='equal';equal['row']['authorization_id']='equal';equal['event_time']=r['transaction_time'];equal['row']['timestamp']=r['transaction_time']
        boundary=copy.deepcopy(f[0]);boundary['id']='boundary';boundary['row']['authorization_id']='boundary';boundary['known_at']=r['decision_time']
        self.assertEqual({x['id'] for x in eligible([late,equal,boundary],r)},{'boundary'})
    def test_scope_and_future(self):
        r,f,c=fixture()
        variants=[]
        for key,value in [('run','other'),('tenant','other'),('event_time','2026-03-01T00:00:00Z')]:
            x=copy.deepcopy(f[0]);x[key]=value
            if key=='event_time':x['row']['timestamp']=value
            variants.append(x)
        x=copy.deepcopy(f[0]);x['row']['customer_id']='other';variants.append(x)
        x=copy.deepcopy(f[0]);x['row']['card_id']='other';variants.append(x)
        for variant in variants:
            self.assertEqual(eligible([variant],r),[])
    def test_correction_and_timezone(self):
        r,f,c=fixture();updated=copy.deepcopy(f[0]);updated['version']=2;updated['known_at']='2026-02-02T00:00:00Z'
        self.assertEqual(eligible([f[0],updated],r)[0]['version'],1)
        updated['known_at']='2026-02-01T13:00:00+01:00'
        self.assertEqual(eligible([f[0],updated],r)[0]['version'],2)
    def test_states(self):
        r,f,c=fixture()
        self.assertEqual(snapshot(f,r,c)['features']['merchant']['state'],'observed')
        r['merchant_id']='NEW'
        self.assertEqual(snapshot(f,r,c)['features']['merchant']['state'],'observed_novelty')
        self.assertEqual(snapshot(f[:2],r,c)['features']['merchant']['state'],'insufficient_history')
        self.assertEqual(snapshot(f,r,dict(c,available=False))['features']['merchant']['state'],'history_unavailable')
        r['channel']='in_store';r['device_id']=None
        self.assertEqual(snapshot(f,r,c)['features']['device']['state'],'not_applicable')
    def test_coverage_scope_and_static_effective(self):
        r,f,c=fixture();c['run']='other'
        self.assertEqual(snapshot(f,r,c)['features']['merchant']['state'],'history_unavailable')
        v=dict(version=1,known_at='2026-01-01T00:00:00Z',effective_from='2026-01-01T00:00:00Z',effective_to=r['transaction_time'])
        self.assertIsNone(static_at([v],r['transaction_time'],r['decision_time']))
    def test_provenance_and_current_outcome_exclusion(self):
        r,f,c=fixture();s=snapshot(f,r,c)
        self.assertEqual(s['provenance'][0]['graph_path'],['CA','T0','M'])
        with self.assertRaises(ValueError):normalize(dict(r,status='declined'))
        f[0]['row']['billing_amount_chf']=2000
        self.assertNotEqual(snapshot(f,r,c)['snapshot_id'],s['snapshot_id'])


class InferenceTests(unittest.TestCase):
    def test_hand_calculation_and_marginalization(self):
        net=ExactNetwork({'target':'b','nodes':[{'name':'a','parents':[],'cpt':{'':[.8,.2]}},{'name':'b','parents':['a'],'cpt':{'0':[.9,.1],'1':[.3,.7]}}]})
        self.assertAlmostEqual(net.posterior({}),.22)
        self.assertAlmostEqual(net.posterior({'a':1}),.7)
        self.assertAlmostEqual(net.posterior({'b':1}),1)
    def test_invalid_cpts_duplicates_and_states(self):
        base=load()['models']['baseline']
        for value in ([.5,.8],[float('nan'),0],[-.1,1.1]):
            m=copy.deepcopy(base);m['nodes'][0]['cpt']['']=value
            with self.assertRaises(ModelError):ExactNetwork(m)
        m=copy.deepcopy(base);del m['nodes'][-1]['cpt']['000']
        with self.assertRaises(ModelError):ExactNetwork(m)
        m=copy.deepcopy(base);m['nodes'].append(m['nodes'][0])
        with self.assertRaises(ModelError):ExactNetwork(m)
        with self.assertRaises(ModelError):ExactNetwork(base).posterior({'merchant':'new'})
    def test_correlation_sensitivity_hash(self):
        cfg=load();nets={k:ExactNetwork(m) for k,m in cfg['models'].items()}
        base={'merchant':0,'amount':0,'velocity':0,'device':1,'country':0}
        # Redundant country/device novelty has a deliberately small joint increment.
        self.assertLess(nets['baseline'].posterior(dict(base,country=1))-nets['baseline'].posterior(base),.03)
        a=analyze(nets,base);self.assertLess(a['minimum'],a['maximum'])
        self.assertTrue(any(x['delta']<0 for x in a['influence']))
        m=copy.deepcopy(cfg);m['policy']['threshold']=.4
        self.assertNotEqual(digest(m),digest(cfg))
        m['policy']['threshold']=float('nan')
        with self.assertRaises(ModelError):validate_config(m)


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=ReceiptStore(Path(self.temp.name)/'receipts.sqlite')
        self.config=load();self.service=DecisionService(self.store,self.config)
        self.r,self.f,self.c=fixture()
    def tearDown(self):
        self.store.db.close();self.temp.cleanup()
    def decide(self,**kw):
        return self.service.decide(self.r,rules(self.r),self.f,self.c,**kw)[0]
    def test_normal_and_unusual(self):
        self.assertEqual(self.decide()['decision'],'approve')
        self.r.update(idempotency_key='new',amount_cents=100000,merchant_id='NEW')
        self.assertEqual(self.decide()['decision'],'step_up')
    def test_hard_rule_precedence(self):
        self.service=DecisionService(self.store,{})
        result=self.service.decide(self.r,rules(self.r,'fail'),[],{},budget_seconds=0)[0]
        self.assertEqual(result['decision'],'decline')
    def test_missing_timeout_invalid_configuration(self):
        self.c['available']=False
        self.assertEqual(self.decide()['reason'],'MISSING_REQUIRED_EVIDENCE')
        self.r['idempotency_key']='timeout';self.c['available']=True
        self.assertEqual(self.decide(budget_seconds=0)['reason'],'MODEL_TIMEOUT')
        self.r['idempotency_key']='config';self.service=DecisionService(self.store,{})
        self.assertEqual(self.decide()['reason'],'INVALID_CONFIGURATION')
    def test_boundary_and_invalid_model_output(self):
        result={'baseline':.35,'minimum':.35,'maximum':.35,'scenarios':{'baseline':.35},'influence':[]}
        with patch('bayesian_network.policy.analyze',return_value=result):
            self.assertEqual(self.decide()['decision'],'step_up')
        self.r['idempotency_key']='state'
        with patch('bayesian_network.policy.analyze',side_effect=ModelError('bad state')):
            self.assertEqual(self.decide()['reason'],'INVALID_MODEL_STATE')
    def test_strict_mode_rejects_assumptions(self):
        self.r['mode']='strict'
        self.assertEqual(self.decide()['reason'],'SNAPSHOT_UNAVAILABLE')
    def test_replay_conflict_and_immutable(self):
        first=self.decide();self.f.clear()
        self.assertEqual(self.decide(),first)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM spends').fetchone()[0],1)
        self.r['amount_cents']+=1
        self.assertEqual(self.decide()['reason'],'IDEMPOTENCY_CONFLICT')
        with self.assertRaises(sqlite3.IntegrityError):self.store.db.execute("UPDATE receipts SET body='{}'")
    def test_persistence_failure(self):
        self.store.db.close()
        self.assertEqual(self.decide()['reason'],'RECEIPT_STORAGE_UNAVAILABLE')
        self.assertFalse(self.decide()['persisted'])
    def pending(self,key):
        self.r.update(idempotency_key=key,amount_cents=100000)
        return self.decide()
    def test_authenticated_human_paths(self):
        resolver=HumanResolver(self.store,{'C':b'test-only-secret'})
        for action in ('approve','reject','revoke'):
            receipt=self.pending(action)
            event=dict(customer_id='C',event_key=action,receipt_scope=receipt['scope'],request_hash=digest(receipt['request']),action=action,resolved_at='2026-02-01T12:01:00Z')
            with self.assertRaises(ValueError):resolver.resolve(event,'invalid',rules)
            result=resolver.resolve(event,resolver.sign(event),rules)
            self.assertEqual(result['status'],{'approve':'approved','reject':'customer_rejected','revoke':'authority_revoked'}[action])
            self.assertEqual(resolver.resolve(event,resolver.sign(event),rules),result)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM spends').fetchone()[0],1)
        self.r['idempotency_key']='after-revoke'
        self.assertEqual(self.decide()['decision'],'decline')
    def test_human_cannot_override_rules(self):
        receipt=self.pending('blocked');resolver=HumanResolver(self.store,{'C':b'test'})
        event=dict(customer_id='C',event_key='blocked',receipt_scope=receipt['scope'],request_hash=digest(receipt['request']),action='approve',resolved_at='2026-02-01T12:01:00Z')
        result=resolver.resolve(event,resolver.sign(event),lambda r:rules(r,'fail'))
        self.assertEqual(result['status'],'approval_blocked')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM spends').fetchone()[0],0)


class AdditionalAcceptanceTests(unittest.TestCase):
    setUp = DecisionTests.setUp
    tearDown = DecisionTests.tearDown
    decide = DecisionTests.decide
    pending = DecisionTests.pending
    def test_nonfinite_output_fails_closed(self):
        value={'baseline':float('nan'),'minimum':0,'maximum':float('nan'),'scenarios':{'baseline':float('nan')},'influence':[]}
        with patch('bayesian_network.policy.analyze',return_value=value):
            self.assertEqual(self.decide()['reason'],'INVALID_MODEL_STATE')
    def test_model_unavailable(self):
        self.service.networks=None
        self.assertEqual(self.decide()['reason'],'MODEL_UNAVAILABLE')
    def test_hard_failure_with_broken_storage(self):
        self.store.db.close()
        result=self.service.decide(self.r,rules(self.r,'fail'),self.f,self.c)[0]
        self.assertEqual(result['decision'],'decline')
        self.assertFalse(result['persisted'])
    def test_stale_coverage_fails_closed(self):
        self.c['through']='2026-02-01T11:59:59Z'
        self.assertEqual(self.decide()['reason'],'MISSING_REQUIRED_EVIDENCE')
    def test_strict_actual_ingestion(self):
        self.r['mode']='strict';self.c['known_at_basis']='actual_ingestion'
        for f in self.f:f['known_at_basis']='actual_ingestion';f['known_at']=self.r['decision_time']
        self.assertEqual(self.decide()['decision'],'approve')
    def test_conflicting_fact_version(self):
        new=copy.deepcopy(self.f[0]);new['row']['billing_amount_chf']+=1
        self.f.append(new)
        self.assertEqual(self.decide()['reason'],'SNAPSHOT_UNAVAILABLE')
    def test_independent_recomputation(self):
        first=self.decide();other=ReceiptStore(':memory:')
        try:
            second=DecisionService(other,self.config).decide(self.r,rules(self.r),self.f,self.c)[0]
            self.assertEqual(first,second)
        finally:other.db.close()
    def test_pending_does_not_spend(self):
        self.pending('pending')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM spends').fetchone()[0],0)
    def test_revocation_blocks_existing_pending(self):
        pending=self.pending('pending');revoke=self.pending('revoke')
        resolver=HumanResolver(self.store,{'C':b'test'})
        for receipt,action in [(revoke,'revoke'),(pending,'approve')]:
            event=dict(customer_id='C',event_key=action,receipt_scope=receipt['scope'],request_hash=digest(receipt['request']),action=action,resolved_at='2026-02-01T12:01:00Z')
            result=resolver.resolve(event,resolver.sign(event),rules)
        self.assertEqual(result['status'],'approval_blocked')
    def test_machine_readable_contracts(self):
        from jsonschema import Draft202012Validator
        from bayesian_network import ROOT
        schema=json.loads((ROOT/'config/contracts.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        receipt=self.decide()
        for name,value in [('receipt',receipt),('request',self.r),('rule_result',rules(self.r)),('fact',self.f[0]),('model',self.config['models']['baseline'])]:
            Draft202012Validator(dict(schema,**{'$ref':'#/$defs/'+name})).validate(value)

if __name__=='__main__':unittest.main()
