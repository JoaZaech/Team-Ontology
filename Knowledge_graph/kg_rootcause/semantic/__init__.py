"""Explicit deterministic ontology. No free-text field can confirm a policy."""
import re
from ..common import cents

ONTOLOGY = {
    "merchant category": {"concept": "MerchantCategory", "field": "merchant.merchant_category"},
    "item category": {"concept": "ItemCategory", "field": "items[].item_category"},
    "amount limit": {"concept": "TransactionLimit", "field": "billing_amount_chf"},
    "currency": {"concept": "Currency", "field": "currency"},
    "familiar shop": {"concept": "FamiliarMerchant", "field": "card_merchant.approved_count", "relationship": "USED_MERCHANT", "condition": "approved_count > 0"},
    "familiar device": {"concept": "FamiliarDevice", "field": "card_device.approved_count", "relationship": "USED_DEVICE", "condition": "approved_count > 0"},
    "channel": {"concept": "Channel", "field": "channel"},
    "delivery": {"concept": "Delivery", "field": "fulfillment_method"},
    "returnable": {"concept": "Returnable", "field": "order_returnable"},
    "cancellable": {"concept": "Cancellable", "field": "order_cancellable"},
    "recurring": {"concept": "Recurring", "field": "recurring"},
    "country": {"concept": "Country", "field": "merchant.merchant_country"},
    "quantity": {"concept": "Quantity", "field": "items[].quantity"},
}


def compile_semantics(instruction):
    rules = []
    for phrase, entry in ONTOLOGY.items():
        for match in re.finditer(re.escape(phrase), instruction, re.IGNORECASE):
            rules.append({"concept": entry["concept"], "field": entry["field"], "operator": "requires", "value": None, "source_text": match.group(), "span": [match.start(), match.end()], "confirmation_status": "unconfirmed"})
    for match in re.finditer(r"(?:at or below|no more than|up to) CHF (\d+(?:\.\d{1,2})?)", instruction):
        rules.append({"concept": "UnscopedAmountLimit", "field": "unresolved", "operator": "<=", "value": cents(match.group(1)), "source_text": match.group(), "span": [match.start(), match.end()], "confirmation_status": "unconfirmed"})
    return {"ontology_version": "ontology-v1", "instruction": instruction, "rules": rules, "unresolved": ["Draft extraction only: confirm rule scope, values, and every unmapped clause before use."], "confirmation_status": "unconfirmed"}


def baseline_policy():
    # Explicit fixture interpretation, never represented as a customer-confirmed mandate.
    return {"version": "simulation-scen0001-v1", "status": "simulation_assumption", "scope": "SCEN0001", "maximum_order_cents": 12000, "rolling_limit_cents": 30000, "rolling_days": 7, "item_categories": ["groceries"], "fulfillment_method": "delivery"}
