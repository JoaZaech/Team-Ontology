import type { DecisionEnvelope, EvaluationResult } from "./types";

/**
 * Historical UI fixture retained for isolated component development. Runtime
 * workflow data comes from `live_layer/viseca_mock.py`; these values are not a
 * decision source in the shipped application.
 */
export const AUTHORIZATION_ID = "MOCK_AU0001";

export const FIXTURE_ENVELOPE: DecisionEnvelope = {
  run_id: "RUN_MOCK_0001",
  event_id: "EVT_MOCK_0001",
  type: "authorization.request",
  authorization_id: AUTHORIZATION_ID,
  status: "pending",
  occurred_at: "2026-08-09T10:04:00Z",
  data: {
    type: "authorization.request",
    request_id: "req_mock_0001",
    deadline_at: "2026-08-09T10:04:08Z",
    authorization: {
      authorization_id: AUTHORIZATION_ID,
      source_authorization_id: "AU0001",
      scenario_id: "SCEN0000",
      replay_order: 1,
      mandate_id: "TM_MOCK_0001",
      profile_id: "PROFILE_MOCK_0001",
      card_id: "CA0001",
      initiator_type: "agent",
      merchant: {
        merchant_id: "ME0001",
        merchant_name: "Alpine Basket",
        merchant_category: "groceries",
        merchant_mcc: "5411",
        merchant_country: "CH",
        merchant_city: "Zurich",
        availability: "store_and_online",
        recurring_capable: "false",
      },
      timestamp: "2026-08-09T10:04:00Z",
      amount: 20.0,
      currency: "CHF",
      billing_amount_chf: 20.0,
      items_subtotal: 13.0,
      delivery_fee: 7.0,
      channel: "ecommerce",
      customer_device_id: "DVC-13A598",
      authority_status: "active",
      card_status_at_attempt: "active",
      fulfillment_method: "delivery",
      delivery_by: "2026-08-10",
      order_returnable: "false",
      order_cancellable: "unknown",
      purchase_description: "Grocery delivery order",
      items: [
        {
          line_no: 1,
          item_id: "IT0001",
          item_name: "Fresh produce selection",
          item_category: "groceries",
          item_details: "One small basket of seasonal fruit and vegetables",
          quantity: 1,
          unit_price: 13.0,
          currency: "CHF",
        },
      ],
    },
    mandate: {
      mandate_id: "TM_MOCK_0001",
      status: "active",
      customer_id: "CU0001",
      card_id: "CA0001",
      instruction:
        "Buy one ordinary grocery item for CHF 20 or less from a shop I use regularly. Ask me when uncertain.",
      hard_rules: [
        {
          field: "authorization.billing_amount_chf",
          operator: "<=",
          value: 20,
          currency: "CHF",
          scope: "purchase",
        },
      ],
      uncertainty_policy: "ask",
      profile_id: "PROFILE_MOCK_0001",
    },
    agent_proposal: {
      summary: "Grocery delivery order",
      merchant_name: "Alpine Basket",
      items: [{
        line_no: 1,
        item_id: "IT0001",
        item_name: "Fresh produce selection",
        item_category: "groceries",
        item_details: "One small basket of seasonal fruit and vegetables",
        quantity: 1,
        unit_price: 13.0,
        currency: "CHF",
      }],
      items_subtotal_chf: 13.0,
      delivery_fee_chf: 7.0,
      total_chf: 20.0,
    },
    applied_policies: {
      confirmed_mandate: {
        mandate_id: "TM_MOCK_0001",
        instruction: "Buy one ordinary grocery item for CHF 20 or less from a shop I use regularly. Ask me when uncertain.",
        hard_rules: [{
          field: "authorization.billing_amount_chf",
          operator: "<=",
          value: 20,
          currency: "CHF",
          scope: "purchase",
        }],
      },
      wallet_policy: {
        policy_id: "wallet-policy_CA0001_default",
        revision: 1,
        enabled: true,
        daily_spending_limit_chf: 1500,
        adaptive_spend_profiles: {
          Groceries: { maximumChf: 180, typicalRange: "CHF 35-180", explanation: "Derived from supplied card history." },
        },
        review_triggers: ["new_merchant"],
        assistant_authority: "trusted",
        rules: [{
          id: "daily-spending-limit",
          label: "Daily spending limit",
          detail: "Up to CHF 1500.00 per day.",
          enforcement: "The purchase amount is added to today’s completed spending. Approval stops when that combined amount would exceed the daily limit.",
        }],
      },
    },
    context: { approved_spend_in_period_chf: 0.0, recent_authorizations: [] },
    runtime: {
      received_at: "2026-08-09T10:04:00Z",
      history_window_minutes: 10,
      context_basis: "run_decisions_and_scenario_timestamps",
    },
  },
};

export const FIXTURE_EVALUATION: EvaluationResult = {
  authorization_id: AUTHORIZATION_ID,
  recommended_decision: "approve",
  reason_codes: [],
  checks: [
    {
      name: "buyer authority",
      outcome: "pass",
      reason_code: "buyer_authorized",
      detail: "The active mandate is bound to this card.",
    },
    {
      name: "requested basket",
      outcome: "pass",
      reason_code: "basket_matches_instruction",
      detail: "The order contains one grocery item.",
    },
    {
      name: "order total",
      outcome: "pass",
      reason_code: "order_total_verified",
      detail: "CHF 13.00 in items plus CHF 7.00 delivery.",
    },
    {
      name: "Spend limit",
      outcome: "pass",
      reason_code: "purchase_within_limit",
      detail: "CHF 20.00 is within the CHF 20.00 purchase limit.",
    },
    {
      name: "Merchant familiarity",
      outcome: "pass",
      reason_code: "merchant_catalogue_match",
      detail: "Alpine Basket matches the catalogue; this card has 26 prior approved purchases there.",
    },
    {
      name: "Recent attempts",
      outcome: "pass",
      reason_code: "attempt_velocity_normal",
      detail: "0 earlier attempts in ten minutes; review starts at 3.",
    },
  ],
  engine_version: "viseca-mock-rulebook-v1",
};

export type DemoScenario = "approve" | "decline" | "review";

export interface DemoFixture {
  label: string;
  envelope: DecisionEnvelope;
  evaluation: EvaluationResult;
}

const DECLINE_ENVELOPE: DecisionEnvelope = {
  ...FIXTURE_ENVELOPE,
  run_id: "RUN_MOCK_0002",
  event_id: "EVT_MOCK_0002",
  data: {
    ...FIXTURE_ENVELOPE.data,
    request_id: "req_mock_0002",
    authorization: {
      ...FIXTURE_ENVELOPE.data.authorization,
      authorization_id: AUTHORIZATION_ID,
      source_authorization_id: "AU0002",
      amount: 46,
      billing_amount_chf: 46,
      items_subtotal: 39,
      delivery_fee: 7,
      purchase_description: "Large grocery delivery order",
      items: [{
        line_no: 1,
        item_id: "IT0002",
        item_name: "Family grocery basket",
        item_category: "groceries",
        item_details: "A larger basket of household groceries",
        quantity: 1,
        unit_price: 39,
        currency: "CHF",
      }],
    },
    agent_proposal: {
      ...FIXTURE_ENVELOPE.data.agent_proposal,
      summary: "Large grocery delivery order",
      items: [{
        line_no: 1,
        item_id: "IT0002",
        item_name: "Family grocery basket",
        item_category: "groceries",
        item_details: "A larger basket of household groceries",
        quantity: 1,
        unit_price: 39,
        currency: "CHF",
      }],
      items_subtotal_chf: 39,
      total_chf: 46,
    },
  },
};

const DECLINE_EVALUATION: EvaluationResult = {
  authorization_id: AUTHORIZATION_ID,
  recommended_decision: "decline",
  reason_codes: ["purchase_limit_exceeded"],
  checks: [
    {
      name: "buyer authority",
      outcome: "pass",
      reason_code: "buyer_authorized",
      detail: "The active mandate is bound to this card.",
    },
    {
      name: "requested basket",
      outcome: "pass",
      reason_code: "basket_matches_instruction",
      detail: "The order contains ordinary grocery items.",
    },
    {
      name: "order total",
      outcome: "pass",
      reason_code: "order_total_verified",
      detail: "CHF 39.00 in items plus CHF 7.00 delivery.",
    },
    {
      name: "Spend limit",
      outcome: "fail",
      reason_code: "purchase_limit_exceeded",
      detail: "CHF 46.00 is above the CHF 20.00 purchase limit.",
    },
    {
      name: "Merchant familiarity",
      outcome: "pass",
      reason_code: "merchant_catalogue_match",
      detail: "Alpine Basket matches the catalogue; this card has 26 prior approved purchases there.",
    },
    {
      name: "Recent attempts",
      outcome: "pass",
      reason_code: "attempt_velocity_normal",
      detail: "0 earlier attempts in ten minutes; review starts at 3.",
    },
  ],
  engine_version: "viseca-mock-rulebook-v1",
};

const REVIEW_ENVELOPE: DecisionEnvelope = {
  ...FIXTURE_ENVELOPE,
  run_id: "RUN_MOCK_0003",
  event_id: "EVT_MOCK_0003",
  data: {
    ...FIXTURE_ENVELOPE.data,
    request_id: "req_mock_0003",
    authorization: {
      ...FIXTURE_ENVELOPE.data.authorization,
      authorization_id: AUTHORIZATION_ID,
      source_authorization_id: "AU0003",
      merchant: {
        ...FIXTURE_ENVELOPE.data.authorization.merchant,
        merchant_id: "ME0002",
        merchant_name: "Fresh Basket Direct",
        merchant_city: "Bern",
      },
    },
    agent_proposal: {
      ...FIXTURE_ENVELOPE.data.agent_proposal,
      merchant_name: "Fresh Basket Direct",
    },
  },
};

const REVIEW_EVALUATION: EvaluationResult = {
  authorization_id: AUTHORIZATION_ID,
  recommended_decision: "step_up",
  reason_codes: ["merchant_unfamiliar_to_card"],
  checks: [
    {
      name: "buyer authority",
      outcome: "pass",
      reason_code: "buyer_authorized",
      detail: "The active mandate is bound to this card.",
    },
    {
      name: "requested basket",
      outcome: "pass",
      reason_code: "basket_matches_instruction",
      detail: "The order contains one grocery item.",
    },
    {
      name: "order total",
      outcome: "pass",
      reason_code: "order_total_verified",
      detail: "CHF 13.00 in items plus CHF 7.00 delivery.",
    },
    {
      name: "Spend limit",
      outcome: "pass",
      reason_code: "purchase_within_limit",
      detail: "CHF 20.00 is within the CHF 20.00 purchase limit.",
    },
    {
      name: "Merchant familiarity",
      outcome: "review",
      reason_code: "merchant_unfamiliar_to_card",
      detail: "Fresh Basket Direct is new for this card. Please confirm this merchant before the payment continues.",
    },
    {
      name: "Recent attempts",
      outcome: "pass",
      reason_code: "attempt_velocity_normal",
      detail: "0 earlier attempts in ten minutes; review starts at 3.",
    },
  ],
  engine_version: "viseca-mock-rulebook-v1",
};

export const DEFAULT_DEMO_SCENARIO: DemoScenario = "approve";

export const FIXTURE_SCENARIOS: Record<DemoScenario, DemoFixture> = {
  approve: { label: "All checks pass", envelope: FIXTURE_ENVELOPE, evaluation: FIXTURE_EVALUATION },
  decline: { label: "Over the limit", envelope: DECLINE_ENVELOPE, evaluation: DECLINE_EVALUATION },
  review: { label: "New merchant", envelope: REVIEW_ENVELOPE, evaluation: REVIEW_EVALUATION },
};
