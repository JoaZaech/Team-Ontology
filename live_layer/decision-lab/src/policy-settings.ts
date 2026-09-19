/**
 * Contract for customer-editable wallet settings.
 *
 * This is deliberately separate from a payment decision. The API that owns
 * this document may validate, version, audit and distribute it to a rule
 * engine, while the rule engine remains the only component that executes it.
 */

import { getWalletPolicy, updateWalletPolicy } from "./api";

export const REVIEW_TRIGGERS = ["new_merchant", "online_purchase", "unusual_activity"] as const;
export const SPEND_CATEGORIES = ["Groceries", "Transport", "Dining", "Shopping"] as const;
export const ASSISTANT_AUTHORITIES = ["review", "trusted", "autopilot"] as const;

export type ReviewTrigger = typeof REVIEW_TRIGGERS[number];
export type SpendCategory = typeof SPEND_CATEGORIES[number];
export type AssistantAuthority = typeof ASSISTANT_AUTHORITIES[number];

export interface AdaptiveSpendProfile {
  maximumChf: number;
  typicalRange: string;
  explanation: string;
}

export interface DynamicWalletPolicy {
  /** Stable identifier used by a settings API and audit log. */
  policyId: string;
  /** Enables additive evolution of this document independent of UI releases. */
  schemaVersion: "2026-09-01";
  /** Optimistic-concurrency token; incremented by the policy service. */
  revision: number;
  subject: { customerId: string; cardId: string };
  enabled: boolean;
  dailySpendingLimitChf: number;
  adaptiveSpendProfiles: Record<SpendCategory, AdaptiveSpendProfile>;
  reviewTriggers: ReviewTrigger[];
  assistantAuthority: AssistantAuthority;
  effectiveFrom: string;
  updatedAt: string;
  updatedBy: "customer" | "system" | "knowledge-graph";
}

export type DynamicWalletPolicyPatch = Pick<
  DynamicWalletPolicy,
  "enabled" | "dailySpendingLimitChf" | "adaptiveSpendProfiles" | "reviewTriggers" | "assistantAuthority"
>;

export interface PolicyUpdateRequest {
  policyId: string;
  expectedRevision: number;
  patch: Partial<DynamicWalletPolicyPatch>;
}

export interface PolicyRepository {
  getDynamicWalletPolicy(): Promise<DynamicWalletPolicy>;
  updateDynamicWalletPolicy(request: PolicyUpdateRequest): Promise<DynamicWalletPolicy>;
}

export class PolicyConflictError extends Error {
  constructor() {
    super("This policy changed elsewhere. Reload it before saving again.");
    this.name = "PolicyConflictError";
  }
}

/**
 * Adapter for the local decision service. The service validates, versions, and
 * supplies the exact snapshot used by the deterministic rulebook; the browser
 * never evaluates a policy itself.
 */
export function createLivePolicyRepository(): PolicyRepository {
  return {
    async getDynamicWalletPolicy() {
      return getWalletPolicy();
    },
    async updateDynamicWalletPolicy(request) {
      try {
        return await updateWalletPolicy(request);
      } catch (error) {
        if (error instanceof Error && error.message === "policy revision conflict") {
          throw new PolicyConflictError();
        }
        throw error;
      }
    },
  };
}
