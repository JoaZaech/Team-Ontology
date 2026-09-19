<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { DemoScenario } from "../fixtures";
import type { Check, DecisionEnvelope, EvaluationResult } from "../types";

type ReceiptStage = "request" | "analysis" | "combine" | "approved" | "declined" | "review" | "error";
type TraceId = "request" | "policy" | "context" | "decision";
type TraceState = "waiting" | "active" | "complete" | "approved" | "declined" | "review" | "error";

interface TraceItem {
  id: TraceId;
  label: string;
  helper: string;
  state: TraceState;
  result: string;
}

const props = defineProps<{
  stage: ReceiptStage;
  purchase: DecisionEnvelope | null;
  evaluation: EvaluationResult | null;
  selectedScenario: DemoScenario;
  declinedByCustomer: boolean;
  approvedByCustomer: boolean;
}>();

const emit = defineEmits<{
  retry: [];
  selectScenario: [scenario: DemoScenario];
}>();

const activeTrace = ref<TraceId>("request");

const authorization = computed(() => props.purchase?.data.authorization ?? null);
const mandate = computed(() => props.purchase?.data.mandate ?? null);
const passedChecks = computed(() => props.evaluation?.checks.filter((check) => check.outcome === "pass") ?? []);
const failedChecks = computed(() => props.evaluation?.checks.filter((check) => check.outcome === "fail") ?? []);
const reviewChecks = computed(() => props.evaluation?.checks.filter((check) => check.outcome === "review") ?? []);
const policyChecks = computed(() => props.evaluation?.checks.filter((check) => isPolicyCheck(check)) ?? []);
const contextChecks = computed(() => props.evaluation?.checks.filter((check) => !isPolicyCheck(check)) ?? []);

const status = computed(() => {
  if (props.stage === "approved") {
    return {
      tone: "approved",
      kicker: props.approvedByCustomer ? "APPROVED BY YOU" : "AUTOMATICALLY APPROVED",
      title: props.approvedByCustomer ? "Approved. You confirmed this purchase." : "Approved. Ready to continue.",
      summary: props.approvedByCustomer
        ? "You approved this purchase after the automated process paused for your review."
        : "This order follows your saved wallet policy and its purchase context looks normal.",
    };
  }
  if (props.stage === "declined") {
    return {
      tone: "declined",
      kicker: "SAFELY STOPPED",
      title: "Declined. No payment was approved.",
      summary: props.declinedByCustomer
        ? "You chose not to approve this purchase after it was paused for your review."
        : "A required safeguard did not pass, so the payment was not authorised.",
    };
  }
  if (props.stage === "review") {
    return {
      tone: "review",
      kicker: "YOUR APPROVAL IS NEEDED",
      title: "This purchase is paused for you.",
      summary: "One fact needs confirmation. The system has not made a payment decision on your behalf.",
    };
  }
  if (props.stage === "error") {
    return {
      tone: "error",
      kicker: "NOT RECORDED",
      title: "We could not complete this decision.",
      summary: "Nothing was approved or recorded. You can check the purchase again.",
    };
  }
  if (props.stage === "combine") {
    return {
      tone: "processing",
      kicker: "CREATING A CLEAR DECISION",
      title: "Bringing the checks together.",
      summary: "We are turning the policy and context checks into one clear outcome.",
    };
  }
  if (props.stage === "analysis") {
    return {
      tone: "processing",
      kicker: "CHECKING THE PURCHASE",
      title: "Comparing it with your saved policy.",
      summary: "We are checking the basket, amount, merchant and recent purchase activity.",
    };
  }
  return {
    tone: "processing",
    kicker: "PURCHASE RECEIVED",
    title: "Preparing a clear decision.",
    summary: "We will show what was checked, why it mattered and what happens next.",
  };
});

const primaryReason = computed(() => {
  const failure = failedChecks.value[0];
  const review = reviewChecks.value[0];
  if (failure) {
    return {
      label: "PRIMARY REASON",
      title: readableCheckName(failure),
      detail: failure.detail,
      source: sourceFor(failure),
    };
  }
  if (props.stage === "declined" && props.declinedByCustomer) {
    return {
      label: "FINAL DECISION",
      title: "You chose not to approve this purchase.",
      detail: "The automated process paused for your review, and your decision safely stopped the payment.",
      source: "Your confirmation",
    };
  }
  if (props.stage === "approved" && props.approvedByCustomer) {
    return {
      label: "FINAL DECISION",
      title: "You confirmed this purchase.",
      detail: "The automated process paused for your review, and you chose to approve the payment.",
      source: "Your confirmation",
    };
  }
  if (review) {
    return {
      label: "WHAT NEEDS YOUR CONFIRMATION",
      title: readableCheckName(review),
      detail: review.detail,
      source: sourceFor(review),
    };
  }
  if (props.stage === "approved") {
    return {
      label: "WHY IT WAS APPROVED",
      title: "The purchase matches your wallet policy.",
      detail: "The basket, total and card authority matched your saved instruction, and the merchant activity looked familiar.",
      source: "Saved wallet policy, purchase request and merchant history",
    };
  }
  if (props.stage === "error") {
    return {
      label: "WHAT HAPPENED",
      title: "The decision was not recorded.",
      detail: "We keep the purchase unapproved when a decision cannot be completed safely.",
      source: "Decision service",
    };
  }
  return {
    label: "WHAT WE ARE CHECKING",
    title: "Your policy is applied before a payment can continue.",
    detail: "Only the order, your saved wallet policy and limited purchase context are used for this decision.",
    source: "Saved wallet policy and purchase request",
  };
});

const trace = computed<TraceItem[]>(() => [
  {
    id: "request",
    label: "Purchase received",
    helper: "Order and policy snapshot",
    state: traceState("request"),
    result: props.purchase ? "Ready" : "Preparing",
  },
  {
    id: "policy",
    label: "Matches your rules",
    helper: "Authority, basket, total and limit",
    state: traceState("policy"),
    result: groupResult(policyChecks.value),
  },
  {
    id: "context",
    label: "Purchase context",
    helper: "Merchant history and recent activity",
    state: traceState("context"),
    result: groupResult(contextChecks.value),
  },
  {
    id: "decision",
    label: "Decision receipt",
    helper: "Outcome and audit record",
    state: traceState("decision"),
    result: decisionResult(),
  },
]);

const activeItem = computed(() => trace.value.find((item) => item.id === activeTrace.value) ?? trace.value[0]);
const activeChecks = computed(() => {
  if (activeTrace.value === "policy") return policyChecks.value;
  if (activeTrace.value === "context") return contextChecks.value;
  return [];
});

const nextStep = computed(() => {
  if (props.stage === "approved") {
    return {
      label: "WHAT HAPPENS NEXT",
      title: props.approvedByCustomer ? "Your approval has been recorded." : "No action is needed.",
      detail: props.approvedByCustomer
        ? "The payment can continue because you confirmed this purchase. Your decision stays attached to this receipt."
        : "The approval and the reasons for it have been recorded for this purchase.",
    };
  }
  if (props.stage === "declined") {
    return {
      label: "WHAT HAPPENS NEXT",
      title: "This payment will not continue.",
      detail: props.declinedByCustomer
        ? "No money was taken. Your decision stays attached to this receipt."
        : "No money was taken. The failed safeguard stays visible in this receipt.",
    };
  }
  if (props.stage === "review") {
    return {
      label: "YOUR CHOICE",
      title: "Review the purchase and decide.",
      detail: "The automated process is paused until you approve or decline the purchase.",
    };
  }
  if (props.stage === "error") {
    return {
      label: "SAFE NEXT STEP",
      title: "Check the purchase again.",
      detail: "We will not make a payment decision until a new evaluation can be completed safely.",
    };
  }
  return {
    label: "NEXT",
    title: "We will show the result here.",
    detail: "Each completed check stays visible with its plain-language evidence.",
  };
});

const scenarios: Array<{ id: DemoScenario; label: string; hint: string }> = [
  { id: "approve", label: "All checks pass", hint: "Automatic approval" },
  { id: "decline", label: "Over the limit", hint: "Automatic decline" },
  { id: "review", label: "New merchant", hint: "Your confirmation" },
];

watch(
  () => props.stage,
  (stage) => {
    if (stage === "analysis") activeTrace.value = "policy";
    if (["combine", "approved", "declined", "review", "error"].includes(stage)) activeTrace.value = "decision";
  },
);

function isPolicyCheck(check: Check): boolean {
  return ["buyer authority", "requested basket", "order total", "Spend limit"].includes(check.name);
}

function readableCheckName(check: Check): string {
  const names: Record<string, string> = {
    "buyer authority": "The card authority could not be confirmed",
    "requested basket": "The basket did not match the saved instruction",
    "order total": "The order total could not be verified",
    "Spend limit": "This purchase is above the allowed limit",
    "Merchant familiarity": "This merchant needs your confirmation",
    "Recent attempts": "Recent purchase activity needs review",
  };
  return names[check.name] ?? check.name;
}

function sourceFor(check: Check): string {
  if (isPolicyCheck(check)) return "Saved wallet policy + purchase request";
  if (check.name === "Merchant familiarity") return "Merchant history";
  return "Recent purchase activity";
}

function groupResult(checks: Check[]): string {
  if (!props.evaluation) return props.stage === "analysis" ? "Checking" : "Waiting";
  const failures = checks.filter((check) => check.outcome === "fail").length;
  const reviews = checks.filter((check) => check.outcome === "review").length;
  const passes = checks.filter((check) => check.outcome === "pass").length;
  if (failures) return `${failures} failed`;
  if (reviews) return `${reviews} needs review`;
  return `${passes} passed`;
}

function decisionResult(): string {
  if (props.stage === "approved") return "Recorded";
  if (props.stage === "declined") return "Recorded";
  if (props.stage === "review") return "Your choice";
  if (props.stage === "error") return "Not recorded";
  if (props.stage === "combine") return "Deciding";
  return "Waiting";
}

function traceState(id: TraceId): TraceState {
  if (id === "request") return props.purchase ? "complete" : "active";
  if (id === "policy" || id === "context") {
    if (props.stage === "request") return "waiting";
    if (props.stage === "analysis") return "active";
    if (props.evaluation) {
      const checks = id === "policy" ? policyChecks.value : contextChecks.value;
      if (checks.some((check) => check.outcome === "fail")) return "declined";
      if (checks.some((check) => check.outcome === "review")) return "review";
      return "complete";
    }
    return "waiting";
  }
  if (props.stage === "approved") return "approved";
  if (props.stage === "declined") return "declined";
  if (props.stage === "review") return "review";
  if (props.stage === "error") return "error";
  if (props.stage === "combine") return "active";
  return "waiting";
}

function stateIcon(state: TraceState): string {
  if (["complete", "approved"].includes(state)) return "✓";
  if (["declined", "error"].includes(state)) return "×";
  if (state === "review") return "!";
  if (state === "active") return "…";
  return "·";
}

function formatTime(value: string | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-CH", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(value));
}
</script>

<template>
  <section class="decision-receipt" :class="`decision-receipt--${status.tone}`" aria-labelledby="decision-receipt-title" aria-live="polite">
    <header class="decision-receipt__hero">
      <div class="decision-receipt__outcome">
        <span class="decision-receipt__mark" aria-hidden="true">{{ stateIcon(trace.find((item) => item.id === "decision")?.state ?? "waiting") }}</span>
        <div>
          <p>{{ status.kicker }}</p>
          <h2 id="decision-receipt-title">{{ status.title }}</h2>
          <span>{{ status.summary }}</span>
        </div>
      </div>

      <dl v-if="authorization" class="decision-receipt__purchase">
        <div><dt>Merchant</dt><dd>{{ authorization.merchant.merchant_name }}</dd></div>
        <div><dt>Amount</dt><dd>CHF {{ authorization.billing_amount_chf.toFixed(2) }}</dd></div>
        <div><dt>Card</dt><dd>{{ authorization.card_id }}</dd></div>
        <div><dt>Received</dt><dd>{{ formatTime(authorization.timestamp) }}</dd></div>
      </dl>
      <div v-else class="decision-receipt__purchase decision-receipt__purchase--pending">
        <span>Purchase details will appear here.</span>
      </div>
    </header>

    <section class="decision-receipt__reason" aria-labelledby="decision-reason-title">
      <div>
        <p>{{ primaryReason.label }}</p>
        <h3 id="decision-reason-title">{{ primaryReason.title }}</h3>
        <span>{{ primaryReason.detail }}</span>
      </div>
      <small><strong>Evidence source</strong>{{ primaryReason.source }}</small>
    </section>

    <section class="decision-receipt__trace" aria-labelledby="decision-trace-title">
      <div class="decision-receipt__section-heading">
        <div><p>GUIDED TRACE</p><h3 id="decision-trace-title">How this decision was made</h3></div>
        <span>{{ passedChecks.length }} of {{ evaluation?.checks.length ?? 0 }} checks passed</span>
      </div>

      <ol class="decision-receipt__steps">
        <li v-for="item in trace" :key="item.id" :class="[`is-${item.state}`, { 'is-selected': activeTrace === item.id }]">
          <button type="button" :aria-expanded="activeTrace === item.id" @click="activeTrace = item.id">
            <span class="decision-receipt__step-mark" aria-hidden="true">{{ stateIcon(item.state) }}</span>
            <span class="decision-receipt__step-copy"><strong>{{ item.label }}</strong><small>{{ item.helper }}</small></span>
            <span class="decision-receipt__step-result">{{ item.result }}</span>
          </button>
        </li>
      </ol>

      <div class="decision-receipt__evidence" :aria-label="`${activeItem.label} details`">
        <div>
          <p>{{ activeItem.label }}</p>
          <span v-if="activeTrace === 'request'">We use the proposed basket, merchant, amount and the policy snapshot that was active when this purchase arrived.</span>
          <span v-else-if="activeTrace === 'decision' && stage === 'approved'">{{ approvedByCustomer ? "You confirmed the purchase after it was paused for review. Your approval is now recorded." : "Every applicable check passed, so the approval was recorded automatically." }}</span>
          <span v-else-if="activeTrace === 'decision' && stage === 'declined'">{{ declinedByCustomer ? "You chose not to approve the purchase after it was paused for review. Your decision is now recorded." : "A failed rule stopped the payment. The reason remains attached to this receipt." }}</span>
          <span v-else-if="activeTrace === 'decision' && stage === 'review'">The system could not safely finish on its own. Your choice will be the final decision.</span>
          <span v-else-if="activeTrace === 'decision' && stage === 'error'">A decision record was not created, so the payment remains unapproved.</span>
          <span v-else-if="activeTrace === 'decision'">We are combining the completed checks into one outcome.</span>
          <span v-else>Each check shows the result, a plain-language explanation and where that evidence came from.</span>
        </div>

        <ul v-if="activeChecks.length">
          <li v-for="check in activeChecks" :key="check.name" :class="`is-${check.outcome}`">
            <span aria-hidden="true">{{ check.outcome === "pass" ? "✓" : check.outcome === "fail" ? "×" : "!" }}</span>
            <div><strong>{{ check.name }}</strong><p>{{ check.detail }}</p><small>{{ sourceFor(check) }}</small></div>
          </li>
        </ul>
      </div>
    </section>

    <section class="decision-receipt__next" :class="`is-${status.tone}`" aria-labelledby="decision-next-title">
      <div><p>{{ nextStep.label }}</p><h3 id="decision-next-title">{{ nextStep.title }}</h3><span>{{ nextStep.detail }}</span></div>
      <button v-if="stage === 'error'" type="button" @click="emit('retry')">Check purchase again</button>
    </section>

    <details v-if="purchase" class="decision-receipt__audit">
      <summary>Decision details for support and audit</summary>
      <dl>
        <div><dt>Receipt</dt><dd>{{ evaluation?.authorization_id ?? purchase.authorization_id }}</dd></div>
        <div><dt>Policy snapshot</dt><dd>{{ mandate?.mandate_id ?? "—" }} · {{ mandate?.status ?? "—" }}</dd></div>
        <div><dt>Engine</dt><dd>{{ evaluation?.engine_version ?? "Preparing" }}</dd></div>
        <div><dt>Run</dt><dd>{{ purchase.run_id }}</dd></div>
      </dl>
      <p v-if="mandate">{{ mandate.instruction }}</p>
    </details>

    <section v-if="['approved', 'declined', 'review', 'error'].includes(stage)" class="decision-receipt__examples" aria-label="Try another simulated outcome">
      <p>TRY ANOTHER SIMULATED OUTCOME</p>
      <div>
        <button v-for="scenario in scenarios" :key="scenario.id" type="button" :class="{ 'is-selected': selectedScenario === scenario.id }" @click="emit('selectScenario', scenario.id)">
          <strong>{{ scenario.label }}</strong><small>{{ scenario.hint }}</small>
        </button>
      </div>
    </section>
  </section>
</template>
