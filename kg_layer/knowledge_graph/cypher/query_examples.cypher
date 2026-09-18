// Parameters used below: $card_id, $merchant_id, $device_id, $limit

// 1. Explain a card's most recent activity, including merchant context.
MATCH (card:Card {card_id: $card_id})<-[:ON_CARD]-(auth:HistoricalAuthorization)-[:AT_MERCHANT]->(merchant:Merchant)
RETURN auth.authorization_id,
       auth.event_timestamp,
       auth.transaction_type,
       auth.status,
       auth.billing_amount_chf_cents,
       auth.initiator_type,
       merchant.merchant_name,
       merchant.merchant_category
ORDER BY auth.event_timestamp DESC, auth.authorization_id DESC
LIMIT $limit;

// 2. Get the materialized familiarity explanation for a card and merchant.
MATCH (card:Card {card_id: $card_id})-[f:FAMILIAR_WITH]->(merchant:Merchant {merchant_id: $merchant_id})
RETURN f.approved_authorization_count,
       f.approved_amount_chf_cents,
       f.last_approved_at;

// 3. Compare human and delegated-agent behavior for the same card/device.
MATCH (card:Card {card_id: $card_id})<-[:ON_CARD]-(auth:HistoricalAuthorization)-[:USED_DEVICE]->(device:Device {device_id: $device_id})
RETURN auth.initiator_type,
       auth.status,
       count(*) AS authorization_count,
       sum(auth.billing_amount_chf_cents) AS amount_chf_cents
ORDER BY authorization_count DESC;

// 4. Trace a refund back to the original historical authorization.
MATCH (refund:HistoricalAuthorization:Refund)-[:REFUNDS]->(original:HistoricalAuthorization)
RETURN refund.authorization_id, refund.event_timestamp, refund.billing_amount_chf_cents,
       original.authorization_id, original.event_timestamp, original.billing_amount_chf_cents
ORDER BY refund.event_timestamp DESC
LIMIT $limit;
