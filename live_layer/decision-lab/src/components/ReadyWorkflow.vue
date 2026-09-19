<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { evaluateRequest, pullRequest, resetRequestRun, resolveDecision, submitDecision } from "../api";
import type { Decision, DecisionEnvelope, EvaluationResult } from "../types";
import visecaLogo from "../assets/viseca-logo.svg";
import DecisionReceipt from "./DecisionReceipt.vue";

const emit = defineEmits<{ openSettings: [] }>();

type FlowStage = "request" | "analysis" | "combine" | "approved" | "declined" | "review" | "error";

const stage = ref<FlowStage>("request");
const purchase = ref<DecisionEnvelope | null>(null);
const evaluation = ref<EvaluationResult | null>(null);
const recording = ref(false);
const error = ref<string | null>(null);
const declinedByCustomer = ref(false);
const approvedByCustomer = ref(false);
const decisionDialog = ref<HTMLElement | null>(null);
const declineButton = ref<HTMLButtonElement | null>(null);
let mounted = true;
let runSequence = 0;

const reviewChecks = computed(() => evaluation.value?.checks.filter((check) => check.outcome === "review") ?? []);
const authorization = computed(() => purchase.value?.data.authorization ?? null);

function isCurrentRun(sequence: number): boolean {
  return mounted && sequence === runSequence;
}

const pause = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function recordEngineDecision(decision: Decision): Promise<boolean> {
  if (!evaluation.value || recording.value) return false;
  recording.value = true;
  error.value = null;
  try {
    await submitDecision({
      authorizationId: evaluation.value.authorization_id,
      decision,
      reasonCodes: evaluation.value.reason_codes,
    });
    if (mounted) {
      declinedByCustomer.value = false;
      approvedByCustomer.value = false;
      if (decision !== "step_up") stage.value = decision === "approve" ? "approved" : "declined";
    }
    return true;
  } catch {
    if (mounted) error.value = "We could not record this decision. No payment was approved.";
    return false;
  } finally {
    if (mounted) recording.value = false;
  }
}

async function resolveCustomerDecision(decision: Exclude<Decision, "step_up">): Promise<boolean> {
  if (!evaluation.value || recording.value) return false;
  recording.value = true;
  error.value = null;
  try {
    await resolveDecision({
      authorizationId: evaluation.value.authorization_id,
      decision,
    });
    if (mounted) {
      declinedByCustomer.value = decision === "decline";
      approvedByCustomer.value = decision === "approve";
      stage.value = decision === "approve" ? "approved" : "declined";
    }
    return true;
  } catch {
    if (mounted) error.value = "We could not record your response. No payment was approved.";
    return false;
  } finally {
    if (mounted) recording.value = false;
  }
}

async function requestHumanDecision(): Promise<void> {
  stage.value = "review";
  await nextTick();
  declineButton.value?.focus();
}

function cycleDialogFocus(event: KeyboardEvent): void {
  const focusable = decisionDialog.value?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)");
  if (!focusable?.length) return;
  const currentIndex = Array.from(focusable).indexOf(document.activeElement as HTMLButtonElement);
  const nextIndex = event.shiftKey
    ? (currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1)
    : (currentIndex >= focusable.length - 1 ? 0 : currentIndex + 1);
  focusable[nextIndex].focus();
}

async function runWorkflow(): Promise<void> {
  const sequence = ++runSequence;
  try {
    declinedByCustomer.value = false;
    approvedByCustomer.value = false;
    purchase.value = null;
    evaluation.value = null;
    error.value = null;
    stage.value = "request";
    await resetRequestRun();
    if (!isCurrentRun(sequence)) return;
    const request = await pullRequest();
    if (!request) throw new Error("request_unavailable");
    if (!isCurrentRun(sequence)) return;
    purchase.value = request;
    stage.value = "analysis";
    const result = await evaluateRequest();
    if (!isCurrentRun(sequence)) return;
    evaluation.value = result;
    stage.value = "combine";
    await pause(450);
    if (!isCurrentRun(sequence)) return;
    if (result.checks.some((check) => check.outcome === "fail")) {
      const recorded = await recordEngineDecision("decline");
      if (!recorded && isCurrentRun(sequence)) stage.value = "error";
    } else if (result.checks.some((check) => check.outcome === "review")) {
      const recorded = await recordEngineDecision("step_up");
      if (recorded && isCurrentRun(sequence)) await requestHumanDecision();
      if (!recorded && isCurrentRun(sequence)) stage.value = "error";
    } else {
      const recorded = await recordEngineDecision("approve");
      if (!recorded && isCurrentRun(sequence)) stage.value = "error";
    }
  } catch {
    if (isCurrentRun(sequence)) {
      stage.value = "error";
      error.value = "We could not evaluate this purchase. Nothing was approved or recorded.";
    }
  }
}

onMounted(() => {
  void runWorkflow();
});

onBeforeUnmount(() => {
  mounted = false;
  runSequence += 1;
});
</script>

<template>
  <main class="ready-page">
    <header class="ready-page__topbar">
      <img class="ready-page__brand" :src="visecaLogo" alt="Viseca" />
      <div class="ready-page__topbar-actions">
        <button class="ready-page__settings" type="button" @click="emit('openSettings')">Wallet policies</button>
        <span class="ready-page__section">AI Shopping Assistant</span>
      </div>
    </header>

    <section class="ready-page__intro" aria-labelledby="workflow-title">
      <p class="ready-page__eyebrow">WALLET DECISION</p>
      <h1 id="workflow-title">A clear answer, with the reasons behind it.</h1>
      <p>Every purchase is checked against your saved wallet policy. The outcome, why it was reached and the evidence behind it stay together in one receipt.</p>
    </section>

    <DecisionReceipt
      :stage="stage"
      :purchase="purchase"
      :evaluation="evaluation"
      :declined-by-customer="declinedByCustomer"
      :approved-by-customer="approvedByCustomer"
      @retry="runWorkflow"
    />

    <div
      v-if="stage === 'review'"
      class="decision-dialog-backdrop"
      @keydown.esc.prevent
      @keydown.tab.prevent="cycleDialogFocus"
    >
      <section
        ref="decisionDialog"
        class="decision-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="decision-dialog-title"
        aria-describedby="decision-dialog-description"
      >
        <div class="decision-dialog__signal" aria-hidden="true">!</div>
        <p class="decision-dialog__eyebrow">HUMAN INTERVENTION IS NEEDED</p>
        <h2 id="decision-dialog-title">Review this purchase</h2>
        <p id="decision-dialog-description" class="decision-dialog__intro">
          The automated process has paused because one part of this purchase needs your confirmation. It will not decide for you.
        </p>

        <dl v-if="authorization" class="decision-dialog__facts">
          <div><dt>Merchant</dt><dd>{{ authorization.merchant.merchant_name }}</dd></div>
          <div><dt>Amount</dt><dd>CHF {{ authorization.billing_amount_chf.toFixed(2) }}</dd></div>
          <div><dt>Card</dt><dd>{{ authorization.card_id }}</dd></div>
        </dl>

        <div v-if="reviewChecks.length" class="decision-dialog__reason">
          <span aria-hidden="true">!</span>
          <p><strong>What needs your confirmation</strong>{{ reviewChecks[0].detail }}</p>
        </div>

        <p v-if="error" class="decision-dialog__error" role="alert">{{ error }}</p>
        <div class="decision-dialog__actions">
          <button
            ref="declineButton"
            class="decision-dialog__button decision-dialog__button--decline"
            type="button"
            :disabled="recording"
            @click="resolveCustomerDecision('decline')"
          >
            {{ recording ? "Recording decision…" : "Do not approve" }}
          </button>
          <button
            class="decision-dialog__button decision-dialog__button--approve"
            type="button"
            :disabled="recording"
            @click="resolveCustomerDecision('approve')"
          >
            Approve purchase
          </button>
        </div>
        <p class="decision-dialog__footnote">Your choice will be recorded as the final decision for this purchase.</p>
      </section>
    </div>
  </main>
</template>
