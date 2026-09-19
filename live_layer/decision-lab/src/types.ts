export interface Merchant {
  merchant_id: string;
  merchant_name: string;
  merchant_category: string;
  merchant_mcc: string;
  merchant_country: string;
  merchant_city: string;
  availability: string;
  recurring_capable: string;
}

export interface OrderItem {
  line_no: number;
  item_id: string;
  item_name: string;
  item_category: string;
  item_details: string;
  quantity: number;
  unit_price: number;
  currency: string;
}

export interface Authorization {
  authorization_id: string;
  source_authorization_id: string;
  scenario_id: string;
  replay_order: number;
  mandate_id: string;
  profile_id: string;
  card_id: string;
  initiator_type: string;
  merchant: Merchant;
  timestamp: string;
  amount: number;
  currency: string;
  billing_amount_chf: number;
  items_subtotal: number;
  delivery_fee: number;
  channel: string;
  customer_device_id: string;
  authority_status: string;
  card_status_at_attempt: string;
  fulfillment_method: string;
  delivery_by: string;
  order_returnable: string;
  order_cancellable: string;
  purchase_description: string;
  items: OrderItem[];
}

export interface Mandate {
  mandate_id: string;
  status: string;
  customer_id: string;
  card_id: string;
  instruction: string;
  hard_rules: Array<Record<string, unknown>>;
  uncertainty_policy: string;
  profile_id: string;
}

export interface DecisionRequestData {
  type: string;
  request_id: string;
  deadline_at: string;
  authorization: Authorization;
  mandate: Mandate;
  context: { approved_spend_in_period_chf: number; recent_authorizations: unknown[] };
  runtime: Record<string, unknown>;
}

export interface DecisionEnvelope {
  run_id: string;
  event_id: string;
  type: string;
  authorization_id: string;
  status: string;
  occurred_at: string;
  data: DecisionRequestData;
}

export type CheckOutcome = "pass" | "fail" | "review";

export interface Check {
  name: string;
  outcome: CheckOutcome;
  reason_code: string;
  detail: string;
}

export type Decision = "approve" | "decline" | "step_up";

export interface EvaluationResult {
  authorization_id: string;
  recommended_decision: Decision;
  reason_codes: string[];
  checks: Check[];
  engine_version: string;
}

export interface DecisionRecordResult {
  authorization_id: string;
  status: string;
  decision?: string;
}

export interface ApiError {
  error: string;
}
