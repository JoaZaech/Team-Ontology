/**
 * Contract for customer-editable wallet settings.
 *
 * This is deliberately separate from a payment decision. The API that owns
 * this document may validate, version, audit and distribute it to a rule
 * engine, while the rule engine remains the only component that executes it.
 */

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
  updatedBy: "customer" | "system";
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
  getDynamicWalletPolicy(subject: DynamicWalletPolicy["subject"]): Promise<DynamicWalletPolicy>;
  updateDynamicWalletPolicy(request: PolicyUpdateRequest): Promise<DynamicWalletPolicy>;
}

export class PolicyConflictError extends Error {
  constructor() {
    super("This policy changed elsewhere. Reload it before saving again.");
    this.name = "PolicyConflictError";
  }
}

const defaultProfiles: Record<SpendCategory, AdaptiveSpendProfile> = {
  Groceries: { maximumChf: 180, typicalRange: "CHF 35–180", explanation: "Your recent grocery purchases are usually within this range, and this leaves room in today’s daily budget." },
  Transport: { maximumChf: 90, typicalRange: "CHF 12–90", explanation: "This reflects your typical local transport and fuel spending, while retaining a buffer in today’s daily budget." },
  Dining: { maximumChf: 140, typicalRange: "CHF 25–140", explanation: "This matches your usual restaurant and takeaway amounts, with a buffer for an occasional higher bill." },
  Shopping: { maximumChf: 250, typicalRange: "CHF 40–250", explanation: "This is based on your recent retail spending and stays below the amount that would be unusual for this category." },
};

export function createPreviewPolicy(): DynamicWalletPolicy {
  return {
    policyId: "wallet-policy_CA0001_default",
    schemaVersion: "2026-09-01",
    revision: 1,
    subject: { customerId: "CU0001", cardId: "CA0001" },
    enabled: true,
    dailySpendingLimitChf: 1500,
    adaptiveSpendProfiles: defaultProfiles,
    reviewTriggers: ["new_merchant", "online_purchase", "unusual_activity"],
    assistantAuthority: "trusted",
    effectiveFrom: "2026-09-19T00:00:00.000Z",
    updatedAt: "2026-09-19T10:42:00.000Z",
    updatedBy: "customer",
  };
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function validatePatch(patch: PolicyUpdateRequest["patch"]): void {
  if (patch.dailySpendingLimitChf !== undefined && (!Number.isFinite(patch.dailySpendingLimitChf) || patch.dailySpendingLimitChf < 0)) {
    throw new Error("The daily spending limit must be a non-negative number.");
  }
  if (patch.reviewTriggers && patch.reviewTriggers.some((trigger) => !REVIEW_TRIGGERS.includes(trigger))) {
    throw new Error("The policy contains an unsupported review trigger.");
  }
  if (patch.assistantAuthority && !ASSISTANT_AUTHORITIES.includes(patch.assistantAuthority)) {
    throw new Error("The policy contains an unsupported approval authority.");
  }
}

/**
 * Temporary adapter for the static demo. It mirrors the future API semantics
 * (read, versioned write, validation) but does not call a backend or execute
 * a payment rule. Replace this implementation with an HTTP PolicyRepository.
 */
export function createPreviewPolicyRepository(initial = createPreviewPolicy()): PolicyRepository {
  let stored = clone(initial);
  return {
    async getDynamicWalletPolicy(subject) {
      if (subject.customerId !== stored.subject.customerId || subject.cardId !== stored.subject.cardId) {
        throw new Error("Policy not found for the requested card.");
      }
      return clone(stored);
    },
    async updateDynamicWalletPolicy(request) {
      validatePatch(request.patch);
      if (request.policyId !== stored.policyId) throw new Error("Policy not found.");
      if (request.expectedRevision !== stored.revision) throw new PolicyConflictError();
      stored = {
        ...stored,
        ...clone(request.patch),
        revision: stored.revision + 1,
        updatedAt: new Date().toISOString(),
        updatedBy: "customer",
      };
      return clone(stored);
    },
  };
}
