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
  spend_in_period_before_chf?: number | null;
  recent_attempt_count_10m?: number;
  fulfillment_method: string;
  delivery_by: string;
  order_returnable: string;
  order_cancellable: string;
  related_authorization_id?: string | null;
  related_authorization_status?: "pending" | "approved" | "declined" | "cancelled" | null;
  purchase_description: string;
  items: OrderItem[];
}

export interface RecentAuthorization {
  authorization_id: string;
  timestamp: string;
  merchant_id: string;
  billing_amount_chf: number;
  status: "approved" | "declined" | "pending" | "cancelled";
}

export interface DecisionRuntime {
  received_at?: string;
  history_window_minutes?: number;
  context_basis?: string;
  [key: string]: unknown;
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

export interface PolicyRule {
  field: string;
  operator: string;
  value: number | string | boolean;
  currency?: string;
  scope?: string;
}

export interface AgentProposal {
  summary: string;
  merchant_name: string;
  items: OrderItem[];
  items_subtotal_chf: number;
  delivery_fee_chf: number;
  total_chf: number;
}

export interface AppliedPolicies {
  confirmed_mandate: {
    mandate_id: string;
    instruction: string;
    hard_rules: PolicyRule[];
  };
  wallet_policy: {
    policy_id: string;
    revision: number;
    enabled: boolean;
    daily_spending_limit_chf: number;
    adaptive_spend_profiles: Record<string, { maximumChf: number; typicalRange: string; explanation: string }>;
    review_triggers: string[];
    assistant_authority: string;
  };
}

export interface DecisionRequestData {
  type: string;
  request_id: string;
  deadline_at: string;
  authorization: Authorization;
  mandate: Mandate;
  agent_proposal: AgentProposal;
  applied_policies: AppliedPolicies;
  context: { approved_spend_in_period_chf: number | null; recent_authorizations: RecentAuthorization[] };
  runtime: DecisionRuntime;
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
