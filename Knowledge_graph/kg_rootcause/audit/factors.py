"""Named diagnostic factors; these are not recovered issuer rules."""
LABELS = {
    'card_inactive': 'Card blocked or expired at event',
    'transaction_limit': 'Amount exceeds supplied per-transaction limit',
    'monthly_limit': 'Account month-to-date total plus attempt exceeds monthly limit',
    'online_disabled': 'Ecommerce attempt while online payments disabled',
    'international_disabled': 'Foreign merchant while international payments disabled',
    'first_card_merchant': 'First recorded card–merchant encounter',
    'no_approved_card_merchant': 'No prior approved purchase at merchant on this card',
    'first_customer_merchant': 'First recorded customer–merchant encounter',
    'first_card_device': 'First recorded use of device on this card',
    'first_card_category': 'First recorded merchant category on this card',
    'first_card_country': 'First recorded country on this card',
    'amount_above_p95': 'Amount above prior approved-purchase p95 (20+ samples)',
    'burst_10m': 'At least 3 earlier card attempts within 10 minutes',
    'recent_decline_same_merchant': 'Earlier decline at same merchant within 10 minutes',
    'unusual_hour': 'UTC hour absent from 20+ prior approved purchases',
    'foreign_merchant': 'Merchant country is not CH (context only)',
}
HARD = {'card_inactive', 'transaction_limit', 'monthly_limit', 'online_disabled', 'international_disabled'}
BEHAVIOR = set(LABELS) - HARD - {'foreign_merchant'}

