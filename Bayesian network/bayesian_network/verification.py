"""Independently verify the persisted replay: schemas, hashes, temporal scopes, sources."""
import json
import sqlite3
from jsonschema import Draft202012Validator
from . import ROOT
from kg_rootcause.common import digest, timestamp


def verify(output=None):
    output=output or ROOT/'build'
    summary=json.loads((output/'summary.json').read_text())
    db=sqlite3.connect('file:'+str(output/summary['receipt_database'])+'?mode=ro',uri=True)
    schema=json.loads((ROOT/'config/contracts.schema.json').read_text())
    validator=Draft202012Validator(dict(schema,**{'$ref':'#/$defs/receipt'}))
    sources={h:json.loads(body) for h,body in db.execute('SELECT hash,body FROM source_facts')}
    errors=[];checked=0
    for fact_hash,fact in sources.items():
        if digest(fact)!=fact_hash:errors.append('fact hash mismatch '+fact_hash)
    for scope,body in db.execute('SELECT scope,body FROM receipts'):
        receipt=json.loads(body);checked+=1
        errors += [scope+': '+e.message for e in validator.iter_errors(receipt)]
        if digest({k:v for k,v in receipt.items() if k!='receipt_hash'})!=receipt['receipt_hash']:
            errors.append(scope+': receipt hash mismatch')
        snap=receipt.get('snapshot');request=receipt['request']
        if snap:
            if digest({k:v for k,v in snap.items() if k!='snapshot_id'})!=snap['snapshot_id']:
                errors.append(scope+': snapshot hash mismatch')
            for p in snap['provenance']:
                fact=sources.get(p['hash'])
                if not fact:
                    errors.append(scope+': missing durable source');continue
                if not (timestamp(fact['event_time'])<timestamp(request['transaction_time']) and timestamp(fact['known_at'])<=timestamp(request['decision_time'])):
                    errors.append(scope+': temporal leakage')
                if any(fact[k]!=request[k] for k in ('tenant','run')) or any(fact['row'][k]!=request[k] for k in ('customer_id','card_id')):
                    errors.append(scope+': scope leakage')
        spent=db.execute('SELECT amount FROM spends WHERE receipt_scope=?',(scope,)).fetchone()
        if bool(spent)!=(receipt['decision']=='approve'):
            errors.append(scope+': unexpected spend')
    result={'receipt_count':checked,'durable_source_versions':len(sources),'errors':errors,'passed':not errors}
    (output/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    db.close();print(json.dumps(result,indent=2))
    if errors:raise AssertionError('Persisted audit verification failed')

if __name__=='__main__':verify()
