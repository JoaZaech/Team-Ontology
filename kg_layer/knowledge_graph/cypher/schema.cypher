// Identity constraints
CREATE CONSTRAINT customer_id_unique IF NOT EXISTS
FOR (node:Customer) REQUIRE node.customer_id IS UNIQUE;

CREATE CONSTRAINT account_id_unique IF NOT EXISTS
FOR (node:Account) REQUIRE node.account_id IS UNIQUE;

CREATE CONSTRAINT card_id_unique IF NOT EXISTS
FOR (node:Card) REQUIRE node.card_id IS UNIQUE;

CREATE CONSTRAINT merchant_id_unique IF NOT EXISTS
FOR (node:Merchant) REQUIRE node.merchant_id IS UNIQUE;

CREATE CONSTRAINT device_id_unique IF NOT EXISTS
FOR (node:Device) REQUIRE node.device_id IS UNIQUE;

CREATE CONSTRAINT merchant_category_name_unique IF NOT EXISTS
FOR (node:MerchantCategory) REQUIRE node.name IS UNIQUE;

CREATE CONSTRAINT authorization_id_unique IF NOT EXISTS
FOR (node:Authorization) REQUIRE node.authorization_id IS UNIQUE;

// Access patterns for the historical graph and cache-rebuild jobs
CREATE INDEX authorization_card_time IF NOT EXISTS
FOR (node:Authorization) ON (node.card_id, node.event_timestamp);

CREATE INDEX authorization_merchant_time IF NOT EXISTS
FOR (node:Authorization) ON (node.merchant_id, node.event_timestamp);

CREATE INDEX authorization_customer_time IF NOT EXISTS
FOR (node:Authorization) ON (node.customer_id, node.event_timestamp);

CREATE INDEX authorization_status IF NOT EXISTS
FOR (node:Authorization) ON (node.status);

CREATE INDEX authorization_type IF NOT EXISTS
FOR (node:Authorization) ON (node.transaction_type);
