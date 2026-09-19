<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { getActivity } from "../api";
import type { ActivitySnapshot, ActivityTransaction } from "../types";
import visecaLogo from "../assets/viseca-logo.svg";

const emit = defineEmits<{ openWorkflow: []; openSettings: []; openCards: [] }>();

const activity = ref<ActivitySnapshot | null>(null);
const error = ref("");
const loading = ref(true);
let refreshTimer: ReturnType<typeof setInterval> | undefined;

const transactions = computed(() => activity.value?.transactions ?? []);

function formatTimestamp(value: string): string {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return value;
  return new Intl.DateTimeFormat("en-CH", { dateStyle: "medium", timeStyle: "short" }).format(timestamp);
}

function outcomeLabel(transaction: ActivityTransaction): string {
  if (transaction.status === "awaiting_customer") return "Awaiting your decision";
  if (transaction.status === "recording_error") return "Recording needs attention";
  if (transaction.final_decision === "approve") return "Approved by customer";
  if (transaction.final_decision === "decline") return "Declined by customer";
  if (transaction.agent_decision === "approve") return "Approved automatically";
  if (transaction.agent_decision === "decline") return "Declined automatically";
  return "Agent proposal recorded";
}

async function loadActivity(): Promise<void> {
  try {
    activity.value = await getActivity();
    error.value = "";
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Unable to load transaction activity.";
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void loadActivity();
  refreshTimer = setInterval(() => void loadActivity(), 1000);
});

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer);
});
</script>

<template>
  <main class="policy-page activity-page">
    <header class="policy-topbar">
      <button class="policy-brand" type="button" aria-label="Return to agent simulation" @click="emit('openWorkflow')"><img :src="visecaLogo" alt="Viseca" /><span></span><strong>Settings</strong></button>
      <div class="policy-topbar__right"><button class="policy-workflow-link" type="button" aria-label="Open agent simulation" @click="emit('openWorkflow')"><span class="policy-workflow-link__full" aria-hidden="true">Agent simulation</span><span class="policy-workflow-link__short" aria-hidden="true">Simulation</span></button><button class="policy-help" type="button">Help centre</button><button class="policy-avatar" type="button" aria-label="Open account menu">JM</button></div>
    </header>
    <div class="policy-shell">
      <aside class="policy-sidebar" aria-label="Main navigation">
        <p class="policy-sidebar__label">CARD MANAGEMENT</p>
        <nav><a href="#" class="policy-nav-link">Overview</a><button type="button" class="policy-nav-link" @click="emit('openSettings')">Wallet policies</button><button type="button" class="policy-nav-link" @click="emit('openCards')">Cards</button><button type="button" class="policy-nav-link policy-nav-link--active" aria-current="page">Activity</button></nav>
        <button type="button" class="policy-nav-link policy-nav-link--bottom" @click="emit('openSettings')">Settings</button>
      </aside>
      <section class="policy-workspace activity-workspace" aria-labelledby="activity-title">
        <div class="policy-breadcrumb"><span>Settings</span><i>/</i> Activity</div>
        <div class="activity-heading"><div><p class="policy-eyebrow">DECISION HISTORY</p><h1 id="activity-title">Activity</h1><p>Every agent proposal, policy result and final customer response is kept together as a transaction record.</p></div><button type="button" class="activity-refresh" :disabled="loading" @click="loadActivity">Refresh</button></div>
        <p v-if="error" class="policy-error" role="alert">{{ error }}</p>
        <p v-else class="activity-status" aria-live="polite">{{ activity?.processing ? "Updating decision history…" : "Decision history is up to date." }}</p>

        <section class="activity-list" aria-label="Transaction activity">
          <p v-if="loading" class="activity-empty">Loading transaction activity…</p>
          <p v-else-if="transactions.length === 0" class="activity-empty">No agent proposals have been recorded yet.</p>
          <article v-for="transaction in transactions" :key="transaction.authorization_id" class="activity-item">
            <div class="activity-item__outcome" :class="`activity-item__outcome--${transaction.status}`">{{ outcomeLabel(transaction) }}</div>
            <div class="activity-item__details"><h2>{{ transaction.merchant_name }}</h2><p>{{ transaction.proposal_summary }}</p><span>{{ formatTimestamp(transaction.updated_at) }} · {{ transaction.merchant_category }}</span></div>
            <div class="activity-item__amount"><strong>CHF {{ transaction.amount_chf.toFixed(2) }}</strong><small>{{ transaction.reason_codes.join(", ") || "No exception reason" }}</small></div>
          </article>
        </section>
      </section>
    </div>
    <nav class="policy-mobile-nav" aria-label="Mobile navigation"><button type="button" @click="emit('openWorkflow')">Simulation</button><button type="button" @click="emit('openSettings')">Policies</button><button type="button" @click="emit('openCards')">Cards</button><button type="button" aria-current="page">Activity</button></nav>
  </main>
</template>