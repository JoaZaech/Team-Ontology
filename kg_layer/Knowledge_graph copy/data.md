# Dataset Inventory

The dataset contains 11 CSV files and 134 column occurrences. Some columns
repeat because authorization history is denormalized.

## 1. Customers — 20 rows, 8 fields

```text
customer_id
persona_name
home_region
background
shopping_preferences
typical_spending
budget_style
travel_pattern
```

## 2. Accounts — 31 rows, 9 fields

```text
account_id
customer_id
account_type
account_purpose
base_currency
status
opened_on
per_transaction_limit_chf
monthly_limit_chf
```

## 3. Cards — 41 rows, 10 fields

```text
card_id
account_id
card_type
card_purpose
status
first_used_on
expires_on
online_enabled
international_enabled
virtual_card
```

## 4. Merchants — 58 rows, 8 fields

```text
merchant_id
merchant_name
merchant_category
merchant_mcc
merchant_country
merchant_city
availability
recurring_capable
```

## 5. Items — 66 rows, 7 fields

```text
item_id
item_name
item_category
item_description
unit_price_min_chf
unit_price_typical_chf
unit_price_max_chf
```

## 6. Historical authorizations — 4,701 rows, 40 fields

### Identity

```text
authorization_id
customer_id
account_id
card_id
initiator_type
```

### Transaction

```text
timestamp
transaction_type
status
amount
currency
billing_amount_chf
description
related_transaction_id
```

### Merchant

```text
merchant_id
merchant_name
merchant_category
merchant_mcc
merchant_country
merchant_city
```

### Payment channel and device

```text
channel
card_present
recurring
customer_device_id
```

### Account context

```text
account_type
account_purpose
base_currency
per_transaction_limit_chf
monthly_limit_chf
```

### Card context at transaction time

```text
card_purpose
card_status
online_enabled
international_enabled
virtual_card
```

### Customer context

```text
customer_home_region
customer_budget_style
customer_persona_name
```

### Existing derived historical features

```text
approved_spend_before_chf
approved_merchant_transaction_count_before
approved_device_transaction_count_before
last_approved_at
```

These four derived fields are card-scoped and use only earlier approved
transactions.

## 7. Purchase attempts — 45 rows, 25 fields

### Identity and ordering

```text
authorization_id
scenario_id
replay_order
authority_id
card_id
merchant_id
timestamp
```

### Financial values

```text
amount
currency
billing_amount_chf
items_subtotal
delivery_fee
spend_in_period_before_chf
```

### Session and transaction context

```text
channel
customer_device_id
recent_attempt_count_10m
authority_status
card_status_at_attempt
```

### Order conditions

```text
fulfillment_method
delivery_by
order_returnable
order_cancellable
purchase_description
```

### Related authorization

```text
related_authorization_id
related_authorization_status
```

## 8. Purchase-attempt items — 56 rows, 9 fields

```text
authorization_id
line_no
item_id
item_name
item_category
quantity
unit_price
currency
item_details
```

`item_details` is untrusted merchant-supplied text and should not control the
system.

## 9. Scenario authorities — 5 rows, 6 fields

```text
authority_id
customer_id
card_id
valid_from
valid_until
initial_status
```

## 10. Scenario catalogue — 5 rows, 7 fields

```text
scenario_id
scenario_name
cardholder_instruction
control_question
control_theme
event_count
short_rationale
```

## 11. FX rates — 4 rows, 5 fields

```text
from_currency
to_currency
rate
rate_date
source
```

## Most useful graph relationships

These fields can directly produce graph relationships:

```text
Customer ──OWNS───────────────> Account
Account ───HAS_CARD───────────> Card
Card ──────USED_MERCHANT──────> Merchant
Card ──────USED_DEVICE────────> Device
Card ──────PURCHASED_CATEGORY─> Category
Merchant ──IN_CATEGORY────────> Category
Authorization ──AT_MERCHANT───> Merchant
Authorization ──USED_DEVICE───> Device
Authorization ──CONTAINS──────> Item
Authorization ──RELATED_TO────> Authorization
Scenario ───USES_AUTHORITY────> Authority
Authority ──CONTROLS──────────> Card
```

## Important limitations

- Historical authorizations have merchant, category, and device context but no
  structured item-level basket data.
- Structured item relationships are available only for the 45 scenario
  purchase attempts.
- Historical `status` is an authorization outcome, not a fraud label.
- Historical agent events do not include `agent_id` or historical
  `authority_id` fields.
- Currency must come from the transaction's `currency` field, not the
  merchant country.
- A missing device means no cardholder device was involved and must not become
  a `Device` node.
- `approved_spend_before_chf` is a lifetime card-scoped total, not monthly or
  rolling-period spending.

