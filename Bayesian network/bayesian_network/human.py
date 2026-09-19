"""Authenticated local demo resolution, not a production identity provider."""
import hashlib
import hmac
import json
from kg_rootcause.common import digest, timestamp
from .policy import normalize, rules_result
from .receipts import Conflict


class HumanResolver:
    def __init__(self, store, customer_keys):
        self.store, self.keys = store, customer_keys

    def sign(self, event):
        return hmac.new(self.keys[event['customer_id']],json.dumps(event,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()

    def resolve(self, event, signature, recheck):
        if event['customer_id'] not in self.keys or not hmac.compare_digest(self.sign(event),signature):
            raise ValueError('authentication failed')
        if event['action'] not in ('approve','reject','revoke'):
            raise ValueError('unknown resolution')
        db=self.store.db
        with db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT body FROM receipts WHERE scope=?',(event['receipt_scope'],)).fetchone()
            if not row:
                raise ValueError('unknown receipt')
            receipt=json.loads(row[0]);request=receipt['request']
            if request['customer_id']!=event['customer_id'] or event['request_hash']!=digest(request):
                raise ValueError('transaction/customer binding mismatch')
            if timestamp(event['resolved_at'])<timestamp(request['decision_time']):
                raise ValueError('resolution predates request')
            old=db.execute('SELECT body FROM resolutions WHERE receipt_scope=?',(event['receipt_scope'],)).fetchone()
            if old:
                old=json.loads(old[0])
                if old['event']!=event:
                    raise Conflict('already resolved with different content')
                return old
            if receipt['decision']!='step_up':
                raise ValueError('only pending step-up can resolve')
            status='customer_rejected'
            check=None
            if event['action']=='revoke':
                key=digest([request['tenant'],request['run'],request.get('authority_id')])
                if not request.get('authority_id'):
                    raise ValueError('missing authority')
                db.execute('INSERT OR IGNORE INTO revocations VALUES(?,?)',(key,json.dumps(event,sort_keys=True)))
                status='authority_revoked'
            elif event['action']=='approve':
                # Trusted policy adapter must recheck current spending and effective authority.
                current=normalize(dict(request,decision_time=event['resolved_at']))
                check=recheck(current)
                failed,unknown=rules_result(check,current)
                required={'authority_active','authority_valid_at_resolution','mandatory_policy'}
                if not required<={c['id'] for c in check['checks']} or failed or unknown or self.store.revoked(request):
                    status='approval_blocked'
                else:
                    status='approved'
                    db.execute('INSERT INTO spends VALUES(?,?)',(event['receipt_scope'],request['amount_cents']))
            result={'event':event,'status':status,'rechecked_rules':check,'authentication':'HMAC-SHA256 local demo principal',
                    'original_receipt_hash':receipt['receipt_hash'],'signature':signature}
            result['resolution_hash']=digest(result)
            db.execute('INSERT INTO resolutions VALUES(?,?,?)',(event['receipt_scope'],event['event_key'],json.dumps(result,sort_keys=True)))
            return result
