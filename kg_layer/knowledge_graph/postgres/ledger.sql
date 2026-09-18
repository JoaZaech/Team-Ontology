-- Optional authoritative store for live wallet policies and decisions.
-- Neo4j and Redis are read/projection stores; neither should be the sole
-- financial decision ledger in a production deployment.

CREATE TABLE IF NOT EXISTS wallet_policy (
    mandate_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    card_id TEXT NOT NULL,
    version BIGINT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'revoked', 'expired')),
    policy_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (mandate_id, version)
);

CREATE TABLE IF NOT EXISTS authorization_decision (
    run_id TEXT NOT NULL,
    authorization_id TEXT NOT NULL,
    mandate_id TEXT NOT NULL,
    policy_version BIGINT NOT NULL,
    simulated_at TIMESTAMPTZ NOT NULL,
    billing_amount_chf_cents BIGINT NOT NULL CHECK (billing_amount_chf_cents >= 0),
    decision TEXT NOT NULL CHECK (decision IN ('approve', 'decline', 'step_up')),
    explanation_json JSONB NOT NULL,
    request_hash TEXT NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, authorization_id),
    FOREIGN KEY (mandate_id) REFERENCES wallet_policy(mandate_id)
);

CREATE INDEX IF NOT EXISTS authorization_decision_run_time_idx
    ON authorization_decision (run_id, simulated_at, authorization_id);

CREATE TABLE IF NOT EXISTS decision_outbox (
    event_id UUID PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS decision_outbox_unpublished_idx
    ON decision_outbox (created_at) WHERE published_at IS NULL;
