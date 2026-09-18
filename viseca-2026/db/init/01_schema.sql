-- Agent on a Leash / Viseca 2026 data pack — schema
-- Mirrors data/data_dictionary.md and data/README.md exactly:
-- customers -< accounts -< cards -< {authorization_history, purchase_attempts}
-- merchants -< {authorization_history, purchase_attempts}
-- scenario_catalogue -< purchase_attempts >- scenario_authorities
-- purchase_attempts -< purchase_attempt_items >- items

CREATE SCHEMA IF NOT EXISTS viseca;
SET search_path TO viseca, public;

-- ---------------------------------------------------------------------
-- Reference / catalogue tables
-- ---------------------------------------------------------------------

CREATE TABLE customers (
    customer_id           text PRIMARY KEY,
    persona_name          text NOT NULL,
    home_region           text NOT NULL,
    background            text,
    shopping_preferences  text,
    typical_spending      text,
    budget_style          text,
    travel_pattern        text
);

CREATE TABLE accounts (
    account_id                 text PRIMARY KEY,
    customer_id                text NOT NULL REFERENCES customers (customer_id),
    account_type                text NOT NULL,
    account_purpose             text NOT NULL,
    base_currency                char(3) NOT NULL,
    status                       text NOT NULL,
    opened_on                    date NOT NULL,
    per_transaction_limit_chf    numeric(12, 2) NOT NULL,
    monthly_limit_chf            numeric(12, 2) NOT NULL
);
CREATE INDEX idx_accounts_customer_id ON accounts (customer_id);

CREATE TABLE cards (
    card_id                 text PRIMARY KEY,
    account_id               text NOT NULL REFERENCES accounts (account_id),
    card_type                text NOT NULL,
    card_purpose              text NOT NULL,
    status                    text NOT NULL,
    first_used_on             date,
    expires_on                date NOT NULL,
    online_enabled            boolean NOT NULL,
    international_enabled     boolean NOT NULL,
    virtual_card              boolean NOT NULL
);
CREATE INDEX idx_cards_account_id ON cards (account_id);

CREATE TABLE merchants (
    merchant_id         text PRIMARY KEY,
    merchant_name        text NOT NULL,
    merchant_category     text NOT NULL,
    merchant_mcc          integer NOT NULL,
    merchant_country      char(2) NOT NULL,
    merchant_city         text NOT NULL,
    availability          text NOT NULL,
    recurring_capable     boolean NOT NULL
);

CREATE TABLE items (
    item_id                  text PRIMARY KEY,
    item_name                 text NOT NULL,
    item_category              text NOT NULL,
    item_description           text,
    unit_price_min_chf          numeric(12, 2) NOT NULL,
    unit_price_typical_chf      numeric(12, 2) NOT NULL,
    unit_price_max_chf          numeric(12, 2) NOT NULL
);

CREATE TABLE fx_rates (
    from_currency   char(3) NOT NULL,
    to_currency      char(3) NOT NULL,
    rate              numeric(12, 6) NOT NULL,
    rate_date         date NOT NULL,
    source            text NOT NULL,
    PRIMARY KEY (from_currency, to_currency, rate_date)
);

-- ---------------------------------------------------------------------
-- Historical authorizations (flat, chronology-safe, TR... namespace)
-- ---------------------------------------------------------------------

CREATE TABLE authorization_history (
    authorization_id       text PRIMARY KEY,
    customer_id             text NOT NULL REFERENCES customers (customer_id),
    account_id               text NOT NULL REFERENCES accounts (account_id),
    card_id                  text NOT NULL REFERENCES cards (card_id),
    initiator_type            text NOT NULL CHECK (initiator_type IN ('human', 'agent', 'merchant')),
    "timestamp"               timestamptz NOT NULL,
    transaction_type          text NOT NULL CHECK (transaction_type IN ('purchase', 'cash_withdrawal', 'refund')),
    status                    text NOT NULL CHECK (status IN ('approved', 'declined')),
    amount                    numeric(12, 2) NOT NULL,
    currency                  char(3) NOT NULL,
    billing_amount_chf         numeric(12, 2) NOT NULL,
    merchant_id                text NOT NULL REFERENCES merchants (merchant_id),
    merchant_name               text NOT NULL,
    merchant_category            text NOT NULL,
    merchant_mcc                 integer NOT NULL,
    merchant_country              text NOT NULL,
    merchant_city                 text NOT NULL,
    channel                       text NOT NULL CHECK (channel IN ('atm', 'ecommerce', 'in_store', 'mobile_wallet', 'recurring')),
    card_present                  boolean NOT NULL,
    recurring                     boolean NOT NULL,
    customer_device_id            text,
    description                    text,
    related_transaction_id          text REFERENCES authorization_history (authorization_id),
    account_type                    text NOT NULL,
    account_purpose                  text NOT NULL,
    base_currency                     char(3) NOT NULL,
    per_transaction_limit_chf          numeric(12, 2) NOT NULL,
    monthly_limit_chf                   numeric(12, 2) NOT NULL,
    card_purpose                         text NOT NULL,
    card_status                           text NOT NULL,
    online_enabled                        boolean NOT NULL,
    international_enabled                 boolean NOT NULL,
    virtual_card                          boolean NOT NULL,
    customer_home_region                  text NOT NULL,
    customer_budget_style                 text NOT NULL,
    customer_persona_name                 text NOT NULL,
    approved_spend_before_chf              numeric(12, 2) NOT NULL,
    approved_merchant_transaction_count_before  integer NOT NULL,
    approved_device_transaction_count_before    integer NOT NULL,
    last_approved_at                       timestamptz
);
CREATE INDEX idx_hist_card_id ON authorization_history (card_id);
CREATE INDEX idx_hist_customer_id ON authorization_history (customer_id);
CREATE INDEX idx_hist_account_id ON authorization_history (account_id);
CREATE INDEX idx_hist_merchant_id ON authorization_history (merchant_id);
CREATE INDEX idx_hist_device_id ON authorization_history (customer_device_id);
CREATE INDEX idx_hist_card_timestamp ON authorization_history (card_id, "timestamp", authorization_id);
CREATE INDEX idx_hist_related_tx ON authorization_history (related_transaction_id);

-- ---------------------------------------------------------------------
-- Scenario contract (AU... namespace)
-- ---------------------------------------------------------------------

CREATE TABLE scenario_catalogue (
    scenario_id          text PRIMARY KEY,
    scenario_name          text NOT NULL,
    cardholder_instruction  text NOT NULL,
    control_question         text NOT NULL,
    control_theme             text NOT NULL,
    event_count                integer NOT NULL,
    short_rationale             text
);

CREATE TABLE scenario_authorities (
    authority_id    text PRIMARY KEY,
    customer_id      text NOT NULL REFERENCES customers (customer_id),
    card_id           text NOT NULL REFERENCES cards (card_id),
    valid_from         timestamptz NOT NULL,
    valid_until          timestamptz NOT NULL,
    initial_status        text NOT NULL
);
CREATE INDEX idx_auth_customer_id ON scenario_authorities (customer_id);
CREATE INDEX idx_auth_card_id ON scenario_authorities (card_id);

CREATE TABLE purchase_attempts (
    authorization_id            text PRIMARY KEY,
    scenario_id                   text NOT NULL REFERENCES scenario_catalogue (scenario_id),
    replay_order                    integer NOT NULL,
    authority_id                     text NOT NULL REFERENCES scenario_authorities (authority_id),
    card_id                           text NOT NULL REFERENCES cards (card_id),
    merchant_id                        text NOT NULL REFERENCES merchants (merchant_id),
    "timestamp"                        timestamptz NOT NULL,
    amount                              numeric(12, 2) NOT NULL,
    currency                             char(3) NOT NULL,
    billing_amount_chf                    numeric(12, 2) NOT NULL,
    items_subtotal                         numeric(12, 2) NOT NULL,
    delivery_fee                            numeric(12, 2) NOT NULL,
    channel                                  text NOT NULL,
    customer_device_id                        text,
    authority_status                           text NOT NULL,
    card_status_at_attempt                      text NOT NULL,
    spend_in_period_before_chf                   numeric(12, 2),
    recent_attempt_count_10m                      integer NOT NULL,
    fulfillment_method                             text NOT NULL,
    delivery_by                                     date,
    order_returnable                                 text NOT NULL,
    order_cancellable                                 text NOT NULL,
    related_authorization_id                           text REFERENCES purchase_attempts (authorization_id),
    related_authorization_status                        text,
    purchase_description                                 text,
    UNIQUE (scenario_id, replay_order)
);
CREATE INDEX idx_attempts_authority_id ON purchase_attempts (authority_id);
CREATE INDEX idx_attempts_card_id ON purchase_attempts (card_id);
CREATE INDEX idx_attempts_merchant_id ON purchase_attempts (merchant_id);

CREATE TABLE purchase_attempt_items (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    authorization_id    text NOT NULL REFERENCES purchase_attempts (authorization_id),
    line_no               integer NOT NULL,
    item_id                text NOT NULL REFERENCES items (item_id),
    item_name                text NOT NULL,
    item_category              text NOT NULL,
    quantity                    integer NOT NULL,
    unit_price                   numeric(12, 2) NOT NULL,
    currency                      char(3) NOT NULL,
    item_details                   text,
    UNIQUE (authorization_id, line_no)
);
CREATE INDEX idx_items_authorization_id ON purchase_attempt_items (authorization_id);
CREATE INDEX idx_items_item_id ON purchase_attempt_items (item_id);

ALTER DATABASE viseca SET search_path TO viseca, public;
