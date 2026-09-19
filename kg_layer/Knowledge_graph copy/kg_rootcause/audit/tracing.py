"""Pure per-event analysis using an exclusive event-time cutoff."""
from datetime import timedelta
import math
from ..common import timestamp
from .factors import LABELS, HARD, BEHAVIOR

def trace(row, history):
    cutoff = timestamp(row['timestamp'])
    earlier = [r for r in history if timestamp(r['timestamp']) < cutoff]
    card = [r for r in earlier if r['card_id'] == row['card_id']]
    customer = [r for r in earlier if r['customer_id'] == row['customer_id']]
    account_month = [r for r in earlier if r['account_id'] == row['account_id'] and r['status'] == 'approved' and timestamp(r['timestamp']).year == cutoff.year and timestamp(r['timestamp']).month == cutoff.month]
    merchant = [r for r in card if r['merchant_id'] == row['merchant_id']]
    customer_merchant = [r for r in customer if r['merchant_id'] == row['merchant_id']]
    other_approved = [r for r in customer_merchant if r['card_id'] != row['card_id'] and r['status'] == 'approved' and r['transaction_type'] == 'purchase']
    device = [r for r in card if row['customer_device_id'] and r['customer_device_id'] == row['customer_device_id']]
    recent = [r for r in card if timestamp(r['timestamp']) >= cutoff - timedelta(minutes=10)]
    purchases = [r for r in card if r['status'] == 'approved' and r['transaction_type'] == 'purchase']
    approved_merchant = [r for r in merchant if r['status'] == 'approved' and r['transaction_type'] == 'purchase']
    amounts = sorted(r['billing_amount_chf'] for r in purchases)
    p95 = amounts[math.ceil(len(amounts)*.95)-1] if amounts else None
    monthly = sum(r['billing_amount_chf'] for r in account_month)
    flags = {
        'card_inactive': row['card_status'] in ('blocked', 'expired'),
        'transaction_limit': row['billing_amount_chf'] > row['per_transaction_limit_chf'],
        'monthly_limit': monthly + row['billing_amount_chf'] > row['monthly_limit_chf'],
        'online_disabled': row['channel'] == 'ecommerce' and not row['online_enabled'],
        'international_disabled': row['merchant_country'] != 'CH' and not row['international_enabled'],
        'first_card_merchant': not merchant,
        'no_approved_card_merchant': not approved_merchant,
        'first_customer_merchant': not customer_merchant,
        'first_card_device': bool(row['customer_device_id']) and not device,
        'first_card_category': not any(r['merchant_category'] == row['merchant_category'] for r in card),
        'first_card_country': not any(r['merchant_country'] == row['merchant_country'] for r in card),
        'amount_above_p95': row['transaction_type'] == 'purchase' and len(amounts) >= 20 and row['billing_amount_chf'] > p95,
        'burst_10m': len(recent) >= 3,
        'recent_decline_same_merchant': any(r['status'] == 'declined' and r['merchant_id'] == row['merchant_id'] for r in recent),
        'unusual_hour': len(purchases) >= 20 and not any(timestamp(r['timestamp']).hour == cutoff.hour for r in purchases),
        'foreign_merchant': row['merchant_country'] != 'CH',
    }
    active = [key for key, value in flags.items() if value]
    verdict = 'observable_rule_conflict' if set(active) & HARD else 'behavioral_context_only' if set(active) & BEHAVIOR else 'unexplained_by_checked_factors'
    evidence = {name: [r['authorization_id'] for r in rows] for name, rows in [('prior_card_events', card), ('prior_card_merchant_events', merchant), ('prior_device_events', device), ('other_card_merchant_approvals', other_approved), ('account_month_approvals', account_month), ('recent_card_attempts', recent), ('prior_approved_purchases', purchases)]}
    return {
        'authorization_id': row['authorization_id'], 'timestamp': row['timestamp'],
        'card_id': row['card_id'], 'customer_id': row['customer_id'], 'account_id': row['account_id'],
        'merchant_id': row['merchant_id'], 'merchant_name': row['merchant_name'],
        'description': row['description'], 'transaction_type': row['transaction_type'],
        'status': row['status'], 'amount_cents': row['billing_amount_chf'],
        'channel': row['channel'], 'initiator': row['initiator_type'],
        'country': row['merchant_country'], 'card_status_at_event': row['card_status'],
        'device': row['customer_device_id'], 'international_enabled': row['international_enabled'], 'online_enabled': row['online_enabled'], 'flags': active, 'assessment': verdict,
        'confirmed_decline_reason': None,
        'prior_card_merchant_count': len(merchant), 'prior_approved_card_merchant_count': len(approved_merchant),
        'prior_device_approved_purchases': sum(r['status']=='approved' and r['transaction_type']=='purchase' for r in device),
        'other_card_merchant_approval_count': len(other_approved),
        'prior_approved_purchase_count': len(purchases), 'prior_purchase_p95_cents': p95,
        'prior_10m_attempt_count': len(recent), 'account_month_before_cents': monthly,
        'account_month_with_attempt_cents': monthly + row['billing_amount_chf'],
        'monthly_limit_cents': row['monthly_limit_chf'], 'transaction_limit_cents': row['per_transaction_limit_chf'],
        'seconds_since_previous_card_event': (cutoff-timestamp(card[-1]['timestamp'])).total_seconds() if card else None,
        'missing_evidence': ['Issuer decline code, decision rules, thresholds and random draw are not supplied.'] + (['Fewer than 20 earlier approved purchases: amount/hour anomaly checks not applied.'] if len(purchases)<20 else []),
        'evidence': evidence,
        'source_file': 'authorization_history.csv', 'source_record_id': row['authorization_id'],
    }

