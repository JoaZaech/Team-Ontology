"""Fail-safe orchestration. External authoritative rules are a trusted integration boundary."""
import time
import math
from kg_rootcause.common import digest, timestamp
from . import VERSION, ROOT
from .configuration import validate_config
from .evidence import snapshot, FEATURE_SPEC, STATES
from .inference import ExactNetwork, analyze, ModelError
from .receipts import Conflict


def normalize(request):
    request = dict(request)
    request.setdefault('transaction_type','purchase')
    if request['transaction_type'] != 'purchase':
        raise ValueError('unsupported transaction type')
    for key in ('tenant','run','idempotency_key','transaction_id','customer_id','card_id','merchant_id','country','channel','transaction_time','decision_time','mode'):
        if not isinstance(request.get(key),str) or not request[key]:
            raise ValueError('invalid request field: '+key)
    if type(request.get('amount_cents')) is not int or request['amount_cents'] < 0:
        raise ValueError('amount must be nonnegative integer cents')
    if request['mode'] not in ('strict','synthetic_retrospective'):
        raise ValueError('unknown temporal mode')
    for key in ('transaction_time','decision_time'):
        request[key] = timestamp(request[key]).isoformat()
    if timestamp(request['decision_time']) < timestamp(request['transaction_time']):
        raise ValueError('decision precedes transaction')
    forbidden = {'status','historical_outcome','decline_reason','approved_spend_before_chf'}
    if forbidden & set(request):
        raise ValueError('outcome fields cannot enter model request')
    return request


def rules_result(rules, request):
    # A caller cannot bypass incomplete checks by sending an empty pass list.
    if not isinstance(rules,dict) or rules.get('request_hash') != digest(request) or not rules.get('version') or not rules.get('checks'):
        raise ValueError('unbound or incomplete authoritative rules')
    if any(c.get('result') not in ('pass','fail','unknown') or not c.get('id') for c in rules['checks']):
        raise ValueError('invalid rule result')
    if len({c['id'] for c in rules['checks']}) != len(rules['checks']):
        raise ValueError('duplicate rule')
    return [c['id'] for c in rules['checks'] if c['result']=='fail'], any(c['result']=='unknown' for c in rules['checks'])


class DecisionService:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.implementation_hash = digest({p.name:p.read_text() for p in sorted((ROOT/'bayesian_network').glob('*.py'))})
        self.networks = None
        self.config_error = None
        try:
            validate_config(config)
            self.networks = {k: ExactNetwork(v) for k,v in config['models'].items()}
        except (ValueError,KeyError,TypeError) as exc:
            self.config_error = str(exc)

    def decide(self, request, rules, facts, coverage, budget_seconds=2):
        started = time.monotonic()
        try:
            request = normalize(request)
        except (ValueError,KeyError,TypeError):
            return {'decision':'step_up','reason':'INVALID_REQUEST','persisted':False,'recovery':'correct invalid request and retry'}, {'elapsed_seconds':time.monotonic()-started}
        scope = digest([request['tenant'],request['run'],request['idempotency_key']])
        # Evidence is pinned on first acceptance; a retry cannot pick up later facts.
        fingerprint = digest({'request':request,'rules':rules,'config':self.config,'features':FEATURE_SPEC,'implementation':self.implementation_hash})
        receipt = {'version':VERSION,'scope':scope,'request':request,'input_hash':fingerprint,'config_hash':digest(self.config),
                   'feature_hash':digest(FEATURE_SPEC),'implementation_version':VERSION,'implementation_hash':self.implementation_hash,
                   'model_hashes':{k:v.validation['model_hash'] for k,v in (self.networks or {}).items()},
                   'policy_hash':digest(self.config.get('policy')),'rules':rules,
                   'decision':'step_up','reason':'INFERENCE_ERROR','snapshot':None,'analysis':None,'persisted':False}
        try:
            failures, unknown = rules_result(rules, request)
        except (ValueError,KeyError,TypeError):
            failures, unknown = [], True
        if failures:
            receipt.update(decision='decline',reason='HARD_RULE_VIOLATION',rule_failures=failures)
        try:
            old = self.store.lookup(scope,fingerprint)
            if old:
                return old, {'elapsed_seconds':time.monotonic()-started,'replayed':True}
            try:
                failures, unknown = rules_result(rules, request)
            except (ValueError,KeyError,TypeError):
                failures, unknown = [], True
            if failures:
                receipt.update(decision='decline',reason='HARD_RULE_VIOLATION',rule_failures=failures)
            elif unknown:
                receipt['reason']='RULES_UNAVAILABLE'
            elif self.config_error:
                receipt['reason']='INVALID_CONFIGURATION'
            elif not self.networks:
                receipt['reason']='MODEL_UNAVAILABLE'
            elif self.store.revoked(request):
                receipt.update(decision='decline',reason='AUTHORITY_REVOKED')
            else:
                try:
                    if request['mode']=='strict' and (coverage.get('known_at_basis') != 'actual_ingestion' or any(f.get('known_at_basis')!='actual_ingestion' for f in facts)):
                        raise ValueError('assumed availability in strict mode')
                    snap = snapshot(facts,request,coverage)
                    receipt['snapshot']=snap
                    if any(v['state'] not in STATES or (v['value'] is not None and (type(v['value']) is not int or v['value'] not in (0,1))) for v in snap['features'].values()):
                        raise ModelError('unknown state')
                    missing=[k for k in FEATURE_SPEC['required'] if snap['features'][k]['value'] is None]
                    if missing:
                        receipt.update(reason='MISSING_REQUIRED_EVIDENCE',missing_features=missing)
                    else:
                        evidence={k:v['value'] for k,v in snap['features'].items() if v['value'] is not None}
                        result=analyze(self.networks,evidence,started+max(0,budget_seconds))
                        probabilities=[result[k] for k in ('baseline','minimum','maximum')]+list(result['scenarios'].values())
                        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in probabilities):
                            raise ModelError('nonfinite or out-of-range posterior')
                        threshold=self.config['policy']['threshold']
                        result['recommendation_changes']=len({v >= threshold for v in result['scenarios'].values()})>1
                        receipt.update(analysis=result,decision='step_up' if result['maximum']>=threshold else 'approve',reason='PROTOTYPE_MODEL_POLICY')
                except TimeoutError:
                    receipt['reason']='MODEL_TIMEOUT'
                except ModelError:
                    receipt['reason']='INVALID_MODEL_STATE'
                except (ValueError,KeyError,TypeError):
                    receipt['reason']='SNAPSHOT_UNAVAILABLE'
                except Exception:
                    receipt['reason']='INFERENCE_ERROR'
            result=self.store.save(scope,fingerprint,receipt,facts)
        except Conflict:
            result={'decision':'step_up','reason':'IDEMPOTENCY_CONFLICT','persisted':False,'scope':scope}
        except Exception:
            result={'decision':'decline' if receipt['decision']=='decline' else 'step_up','reason':'RECEIPT_STORAGE_UNAVAILABLE',
                    'persisted':False,'scope':scope,'recovery':'No approval or spend emitted. Retry same request/key after durable storage recovers.'}
        return result, {'elapsed_seconds':time.monotonic()-started,'replayed':False}
