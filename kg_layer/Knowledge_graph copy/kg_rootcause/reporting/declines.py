"""Export audit results as HTML, JSON, Markdown, and CSV."""
import csv
import json
from html import escape
from ..common import write_json
from ..audit.factors import LABELS

def export(report,cases,output):
    output.mkdir(parents=True,exist_ok=True)
    write_json(output/'decline_smoke_report.json',report)
    write_json(output/'decline_case_traces.json',cases)
    columns=['authorization_id','timestamp','card_id','merchant_id','merchant_name','transaction_type','amount_cents','assessment','flags','prior_card_merchant_count','other_card_merchant_approval_count','prior_approved_purchase_count','prior_purchase_p95_cents','account_month_with_attempt_cents','monthly_limit_cents']
    with (output/'decline_case_index.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for c in cases:writer.writerow({k:'; '.join(c[k]) if k=='flags' else c[k] for k in columns})
    def e(value): return escape(str(value))
    def money(value):return 'Unavailable' if value is None else f'CHF {value/100:,.2f}'
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Historical decline smoke test</title><style>body{font:16px system-ui;margin:32px auto;padding:0 20px;max-width:1100px;color:#20302b;background:#fafbf9}h1{font-size:30px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:9px;border-bottom:1px solid #d9e0db}details{padding:12px 0;border-bottom:1px solid #d9e0db}summary{cursor:pointer}code{overflow-wrap:anywhere}a{color:#176147}.scroll{overflow:auto}.note{color:#8b2929}p{line-height:1.5}</style><h1>Historical decline smoke test</h1>',f"<p><strong>{'PASS' if report['smoke_test_passed'] else 'FAIL'}</strong> · {report['decline_count']} declines traced · {len(report['errors'])} audit errors</p>",'<p class="note">Recorded historical outcomes only. These are observed factors and counter-evidence—not recovered issuer reasons. No new approval or decline decisions were made.</p>','<h2>Observed factors</h2><div class="scroll"><table><tr><th>Factor</th><th>All declines</th><th>Purchase approvals with factor</th><th>Purchase declines with factor</th><th>Purchase decline rate</th></tr>']
    for f in report['factors']:
        parts.append(f"<tr><td><a href='#factor-{e(f['factor'])}'>{e(f['label'])}</a></td><td>{f['historical_declines_with_factor']}</td><td>{f['purchase_approvals_with_factor']}</td><td>{f['purchase_declines_with_factor']}</td><td>{f['purchase_decline_rate_percent']}%</td></tr>")
    parts += ['</table></div><h2>Case groups</h2>']
    for f in report['factors']:
        members=[c for c in cases if f['factor'] in c['flags']]
        parts.append(f"<details id='factor-{e(f['factor'])}'><summary>{e(f['label'])} · {len(members)} cases</summary><p>"+' · '.join(f"<a href='#case-{c['authorization_id']}'>{c['authorization_id']}</a>" for c in members)+'</p></details>')
    parts.append('<h2>All decline traces</h2>')
    for c in cases:
        aid=c['authorization_id'];flags='; '.join(LABELS[k] for k in c['flags']) or 'No checked factor triggered'
        parts.append(f"<details id='case-{aid}'><summary><strong>{aid}</strong> · {e(c['card_id'])} → {e(c['merchant_name'])} · {money(c['amount_cents'])} · {e(c['assessment'].replace('_',' '))}</summary><p><strong>Recorded reason:</strong> unavailable.<br><strong>Observed factors:</strong> {e(flags)}</p><p>{e(c['description'])} · {e(c['timestamp'])} · {e(c['transaction_type'])} · {e(c['channel'])}</p><table>")
        facts=[('Card status at event',c['card_status_at_event']),('Merchant country',c['country']),('International payments enabled (source row)',c['international_enabled']),('Online payments enabled (source row)',c['online_enabled']),('Previous card–merchant attempts',c['prior_card_merchant_count']),('Previous approved card–merchant purchases',c['prior_approved_card_merchant_count']),('Same customer: approved merchant purchases on other cards',c['other_card_merchant_approval_count']),('Prior approved device purchases',c['prior_device_approved_purchases'] if c['device'] else 'No device involved'),('Prior card purchase sample size',c['prior_approved_purchase_count']),('Prior purchase p95',money(c['prior_purchase_p95_cents'])),('Earlier attempts in 10 minutes',c['prior_10m_attempt_count']),('Per-transaction limit',money(c['transaction_limit_cents'])),('Account month total including proposed attempt',money(c['account_month_with_attempt_cents'])),('Monthly limit',money(c['monthly_limit_cents'])),('Seconds since previous card event',c['seconds_since_previous_card_event'])]
        parts += [f'<tr><th>{e(k)}</th><td>{e(v)}</td></tr>' for k,v in facts]
        parts.append('</table><p>'+e(' '.join(c['missing_evidence']))+'</p><details><summary>Supporting source records (strictly earlier)</summary>')
        for k,ids in c['evidence'].items():parts.append(f'<p>{e(k)}: <code>{e(", ".join(ids)) or "None"}</code></p>')
        parts.append('</details></details>')
    parts += ['<h2>Definitions and limitations</h2><ul>']+[f'<li>{e(d)}</li>' for d in report['definitions']]+['</ul><script>function reveal(){const el=document.getElementById(location.hash.slice(1));if(el&&el.tagName==="DETAILS"){el.open=true;el.scrollIntoView()}}window.addEventListener("hashchange",reveal);reveal();</script></html>']
    (output/'decline_smoke_report.html').write_text(''.join(parts))
    lines=['# Historical decline smoke test','',f"Result: {'PASS' if report['smoke_test_passed'] else 'FAIL'}; {len(cases)} declines; {len(report['errors'])} audit errors.",'',json.dumps(report['assessments']), '', '| Observed factor | Declined records | Approved purchases with factor | Declined purchases with factor |','| --- | ---: | ---: | ---: |']
    lines += [f"| {f['label']} | {f['historical_declines_with_factor']} | {f['purchase_approvals_with_factor']} | {f['purchase_declines_with_factor']} |" for f in report['factors']]
    lines += ['', '## Interpretation','']+['- '+d for d in report['definitions']]
    (output/'decline_smoke_report.md').write_text('\n'.join(lines)+'\n')

