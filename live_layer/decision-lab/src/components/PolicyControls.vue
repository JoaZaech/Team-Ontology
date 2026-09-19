<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import visecaLogo from "../assets/viseca-logo.svg";
import DynamicWalletPolicy from "./DynamicWalletPolicy.vue";
import PolicyRecommendationCard from "./PolicyRecommendation.vue";
import {
  createLivePolicyRepository,
  type DynamicWalletPolicy as DynamicWalletPolicyDocument,
  type DynamicWalletPolicyPatch,
} from "../policy-settings";
import { getPolicyRecommendations } from "../api";
import type { PolicyRecommendation } from "../types";

const emit = defineEmits<{ openWorkflow: []; openCards: []; openActivity: [] }>();

type Policy = {
  id: number;
  name: string;
  description: string;
  category: "Spending" | "Security" | "Cards" | "Notifications";
  enabled: boolean;
  updated: string;
  icon: "wallet" | "shield" | "card" | "bell";
};

const policies = ref<Policy[]>([
  { id: 1, name: "Daily spending limit", description: "Decline purchases that take daily card spending above CHF 1,500.", category: "Spending", enabled: true, updated: "Updated today, 10:42", icon: "wallet" },
  { id: 2, name: "Online purchase check", description: "Ask for an additional confirmation for online purchases over CHF 250.", category: "Security", enabled: true, updated: "Updated yesterday", icon: "shield" },
  { id: 3, name: "International payments", description: "Allow card payments outside Switzerland and Liechtenstein.", category: "Cards", enabled: false, updated: "Updated 12 Sep 2026", icon: "card" },
  { id: 4, name: "Instant payment alerts", description: "Send a notification as soon as a card payment is approved.", category: "Notifications", enabled: true, updated: "Updated 08 Sep 2026", icon: "bell" },
  { id: 5, name: "Contactless limit", description: "Require PIN verification when contactless payments exceed CHF 80.", category: "Security", enabled: false, updated: "Updated 02 Sep 2026", icon: "shield" },
]);

const selectedCategory = ref<"All" | Policy["category"]>("All");
const search = ref("");
const showOnlyActive = ref(false);
const lastAction = ref("");
const dynamicPolicy = ref<DynamicWalletPolicyDocument>();
const policySaving = ref(false);
const policyError = ref("");
const recommendationFeedback = ref("");
const policyRepository = createLivePolicyRepository();
const categories: Array<"All" | Policy["category"]> = ["All", "Spending", "Security", "Cards", "Notifications"];
const policyRecommendations = ref<PolicyRecommendation[]>([]);

const filteredPolicies = computed(() => {
  const query = search.value.trim().toLowerCase();
  return policies.value.filter((policy) => {
    const matchesCategory = selectedCategory.value === "All" || policy.category === selectedCategory.value;
    const matchesSearch = !query || `${policy.name} ${policy.description}`.toLowerCase().includes(query);
    return matchesCategory && matchesSearch && (!showOnlyActive.value || policy.enabled);
  });
});
const activeCount = computed(() => policies.value.filter((policy) => policy.enabled).length + Number(dynamicPolicy.value?.enabled));

function togglePolicy(policy: Policy): void {
  recommendationFeedback.value = "";
  policy.enabled = !policy.enabled;
  policy.updated = "Updated just now";
  lastAction.value = `${policy.name} ${policy.enabled ? "enabled" : "disabled"}`;
}

function dismissRecommendedPolicy(recommendationId: string): void {
  policyRecommendations.value = policyRecommendations.value.filter(
    (recommendation) => recommendation.recommendation_id !== recommendationId,
  );
  recommendationFeedback.value = "Recommendation hidden. Your current policies have not changed.";
}

async function loadDynamicPolicy(): Promise<void> {
  policySaving.value = true;
  policyError.value = "";
  try {
    dynamicPolicy.value = await policyRepository.getDynamicWalletPolicy();
    try {
      policyRecommendations.value = (await getPolicyRecommendations()).recommendations;
    } catch {
      policyRecommendations.value = [];
    }
  } catch (error) {
    policyError.value = error instanceof Error
      ? error.message
      : "Unable to load the policy used by the decision service.";
  } finally {
    policySaving.value = false;
  }
}

async function applyRecommendedPolicy(recommendation: PolicyRecommendation): Promise<void> {
  if (policySaving.value || !dynamicPolicy.value) return;
  recommendationFeedback.value = "";
  policySaving.value = true;
  policyError.value = "";
  try {
    const adaptiveSpendProfiles = {
      ...dynamicPolicy.value.adaptiveSpendProfiles,
      [recommendation.profile_category]: recommendation.profile,
    };
    dynamicPolicy.value = await policyRepository.updateDynamicWalletPolicy({
      policyId: dynamicPolicy.value.policyId,
      expectedRevision: dynamicPolicy.value.revision,
      patch: { adaptiveSpendProfiles },
    });
    policyRecommendations.value = policyRecommendations.value.filter(
      (item) => item.recommendation_id !== recommendation.recommendation_id,
    );
    lastAction.value = `${recommendation.name} is now enforced by the rule engine.`;
    recommendationFeedback.value = `${recommendation.name} was applied to your versioned wallet policy.`;
  } catch (error) {
    policyError.value = error instanceof Error ? error.message : "Unable to apply the recommendation.";
  } finally {
    policySaving.value = false;
  }
}

async function updateDynamicPolicy(patch: Partial<DynamicWalletPolicyPatch>): Promise<void> {
  if (policySaving.value || !dynamicPolicy.value) return;
  recommendationFeedback.value = "";
  policySaving.value = true;
  policyError.value = "";
  try {
    dynamicPolicy.value = await policyRepository.updateDynamicWalletPolicy({
      policyId: dynamicPolicy.value.policyId,
      expectedRevision: dynamicPolicy.value.revision,
      patch,
    });
    lastAction.value = "Dynamic wallet policy updated. New purchase requests will use this revision.";
  } catch (error) {
    policyError.value = error instanceof Error ? error.message : "Unable to save the policy.";
  } finally {
    policySaving.value = false;
  }
}

onMounted(() => {
  void loadDynamicPolicy();
});

function iconPath(icon: Policy["icon"]): string {
  return {
    wallet: "M4 7.5A2.5 2.5 0 0 1 6.5 5H19a1 1 0 0 1 1 1v1.5M4 7.5v9A2.5 2.5 0 0 0 6.5 19H20V8H6.5A2.5 2.5 0 0 1 4 5.5v2Zm12 5.5h2",
    shield: "M12 3.5 19 6v5.3c0 4.1-2.7 7.8-7 9.2-4.3-1.4-7-5.1-7-9.2V6l7-2.5Zm-3 8.2 2 2 4-4",
    card: "M3.5 6.5h17v11h-17v-11Zm0 4h17M7 14h3",
    bell: "M18 10a6 6 0 0 0-12 0c0 7-2.5 7-2.5 8h17c0-1-2.5-1-2.5-8ZM10 21h4",
  }[icon];
}
</script>

<template>
  <main class="policy-page">
    <header class="policy-topbar">
      <button class="policy-brand" type="button" aria-label="Return to agent simulation" @click="emit('openWorkflow')"><img :src="visecaLogo" alt="Viseca" /><span></span><strong>Settings</strong></button>
      <div class="policy-topbar__right"><button class="policy-workflow-link" type="button" aria-label="Open agent simulation" @click="emit('openWorkflow')"><span class="policy-workflow-link__full" aria-hidden="true">Agent simulation</span><span class="policy-workflow-link__short" aria-hidden="true">Simulation</span></button><button class="policy-help" type="button">Help centre</button><button class="policy-avatar" type="button" aria-label="Open account menu">JM</button></div>
    </header>
    <div class="policy-shell">
      <aside class="policy-sidebar" aria-label="Main navigation">
        <p class="policy-sidebar__label">CARD MANAGEMENT</p>
        <nav><a href="#" class="policy-nav-link">Overview</a><a href="#" class="policy-nav-link policy-nav-link--active" aria-current="page">Wallet policies</a><button type="button" class="policy-nav-link" @click="emit('openCards')">Cards</button><button type="button" class="policy-nav-link" @click="emit('openActivity')">Activity</button></nav>
        <a href="#" class="policy-nav-link policy-nav-link--bottom">Settings</a>
      </aside>
      <section class="policy-workspace">
        <div class="policy-breadcrumb"><span>Settings</span><i>/</i> Wallet policies</div>
        <div class="policy-heading"><div><p class="policy-eyebrow">YOUR CARD, YOUR RULES</p><h1>Wallet policies</h1><p class="policy-intro">Choose the rules that help keep your card use simple and secure.</p></div><div class="policy-summary" aria-label="Number of active policies"><span>{{ activeCount }}</span><p>active<br />policies</p></div></div>
        <section class="policy-notice" aria-label="Policy information"><div class="policy-notice__icon">i</div><p>These settings are versioned by the local decision service and applied to the next incoming purchase request alongside the confirmed mandate.</p></section>
        <DynamicWalletPolicy v-if="dynamicPolicy" :policy="dynamicPolicy" :saving="policySaving" @change="updateDynamicPolicy" />
        <p v-if="policyError" class="policy-error" role="alert">{{ policyError }}</p>
        <div class="policy-controls">
          <div class="policy-tabs" role="tablist" aria-label="Policy categories"><button v-for="category in categories" :key="category" type="button" :class="['policy-tab', { 'policy-tab--active': selectedCategory === category }]" :aria-selected="selectedCategory === category" @click="selectedCategory = category">{{ category }}</button></div>
          <div class="policy-control-actions"><label class="policy-search"><span>⌕</span><input v-model="search" type="search" placeholder="Search policies" /></label><button type="button" :class="['policy-filter', { 'policy-filter--on': showOnlyActive }]" @click="showOnlyActive = !showOnlyActive">☰&nbsp; Active only</button></div>
        </div>
        <p v-if="lastAction" class="policy-feedback" role="status">{{ lastAction }}</p>
        <div class="policy-grid">
          <article v-for="policy in filteredPolicies" :key="policy.id" class="policy-card" :class="{ 'policy-card--off': !policy.enabled }">
            <div class="policy-card__top"><span class="policy-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path :d="iconPath(policy.icon)" /></svg></span><span class="policy-category">{{ policy.category }}</span><button type="button" class="policy-switch" :class="{ 'policy-switch--on': policy.enabled }" role="switch" :aria-checked="policy.enabled" :aria-label="`${policy.enabled ? 'Disable' : 'Enable'} ${policy.name}`" @click="togglePolicy(policy)"><span></span></button></div>
            <h2>{{ policy.name }}</h2><p class="policy-card__description">{{ policy.description }}</p>
            <div class="policy-card__footer"><span :class="['policy-status', { 'policy-status--off': !policy.enabled }]"><i></i>{{ policy.enabled ? "Enabled" : "Disabled" }}</span><span class="policy-updated">{{ policy.updated }}</span></div>
          </article>
        </div>
        <div v-if="filteredPolicies.length === 0" class="policy-empty"><p>No policies match your filters.</p><button type="button" @click="search = ''; selectedCategory = 'All'; showOnlyActive = false">Clear filters</button></div>
        <PolicyRecommendationCard v-for="recommendation in policyRecommendations" :key="recommendation.recommendation_id" :recommendation="recommendation" @apply="applyRecommendedPolicy" @dismiss="dismissRecommendedPolicy" />
        <p v-if="recommendationFeedback" class="policy-recommendation-feedback" role="status">{{ recommendationFeedback }}</p>
      </section>
    </div>
    <nav class="policy-mobile-nav" aria-label="Mobile navigation">
      <button type="button" @click="emit('openWorkflow')">Simulation</button>
      <button type="button" aria-current="page">Policies</button>
      <button type="button" @click="emit('openCards')">Cards</button>
    </nav>
  </main>
</template>
