<script setup lang="ts">
import type { Decision, EvaluationResult } from "../types";

const props = defineProps<{
  envelope: unknown;
  evaluation: EvaluationResult | null;
  decision: Decision | null;
  evaluating: boolean;
  submitting: boolean;
  submitted: boolean;
}>();

const emit = defineEmits<{
  evaluate: [];
  submit: [];
  "update:decision": [value: Decision];
}>();

const LABELS: Record<Decision, string> = {
  approve: "Approved",
  decline: "Not approved",
  step_up: "Human requested",
};

function label(value: Decision): string {
  return LABELS[value];
}

function outcomeMark(outcome: string): string {
  return outcome === "pass" ? "✓" : outcome === "fail" ? "×" : "?";
}

function selectDecision(value: Decision): void {
  emit("update:decision", value);
}
</script>

<template>
  <section class="card">
    <h2>Rulebook decision</h2>
    <p class="sub">The server checks the confirmed mandate, basket, amount, merchant familiarity, and attempt rate.</p>

    <div class="rule-wrap" :class="{ processing: evaluating }">
      <div class="rule-content">
        <div v-if="!evaluation" class="empty">Pull a request to start evaluation.</div>
        <div v-else>
          <div class="recommendation">Rulebook recommendation: {{ label(evaluation.recommended_decision) }}</div>
          <div v-for="check in evaluation.checks" :key="check.name" class="check" :class="check.outcome">
            <span class="mark">{{ outcomeMark(check.outcome) }}</span>
            <div>
              <strong>{{ check.name }}</strong>
              <p>{{ check.detail }}</p>
            </div>
          </div>
          <div class="choices" role="radiogroup" aria-label="Decision options">
            <label
              v-for="value in (['approve', 'decline', 'step_up'] as Decision[])"
              :key="value"
              class="choice"
              :class="{ checked: decision === value }"
            >
              <input
                type="radio"
                name="decision"
                :value="value"
                :checked="decision === value"
                @change="selectDecision(value)"
              />
              {{ label(value) }}
            </label>
          </div>
        </div>
      </div>
      <div class="busy" role="status">
        <div><span class="spinner"></span>Evaluating request…</div>
      </div>
    </div>

    <div class="actions">
      <button class="primary" :disabled="!envelope || !!evaluation || evaluating" @click="emit('evaluate')">
        Evaluate request
      </button>
      <button class="complete" :disabled="!evaluation || !decision || submitting || submitted" @click="emit('submit')">
        Submit decision
      </button>
    </div>
  </section>
</template>
