<script setup lang="ts">
import { computed } from "vue";
import type { DecisionEnvelope } from "../types";

const props = defineProps<{
  envelope: DecisionEnvelope | null;
  pulling: boolean;
}>();

const emit = defineEmits<{
  pull: [];
  reset: [];
}>();

const authorization = computed(() => props.envelope?.data.authorization ?? null);

const basketSummary = computed(() => {
  if (!authorization.value) return "";
  return authorization.value.items.map((item) => `${item.quantity} × ${item.item_name}`).join(", ");
});

const rawRequest = computed(() => (props.envelope ? JSON.stringify(props.envelope, null, 2) : "—"));
</script>

<template>
  <section class="card">
    <h2>Purchase request</h2>
    <p class="sub">Buyer, merchant, basket, and amount from the Viseca connection-check fixture.</p>

    <div v-if="!authorization" class="empty">No request loaded yet.</div>
    <div v-else class="facts">
      <div class="fact">
        <span>Buyer card</span>
        <strong>{{ authorization.card_id }}</strong>
      </div>
      <div class="fact">
        <span>Merchant</span>
        <strong>{{ authorization.merchant.merchant_name }}</strong>
      </div>
      <div class="fact">
        <span>Amount</span>
        <strong>CHF {{ authorization.billing_amount_chf.toFixed(2) }}</strong>
      </div>
      <div class="fact">
        <span>Basket</span>
        <strong>{{ basketSummary }}</strong>
      </div>
    </div>

    <div class="actions">
      <button class="primary" :disabled="!!envelope || pulling" @click="emit('pull')">Pull request</button>
      <button class="secondary" @click="emit('reset')">Reset demo</button>
    </div>

    <details v-if="envelope">
      <summary>View full request JSON</summary>
      <pre>{{ rawRequest }}</pre>
    </details>
  </section>
</template>
