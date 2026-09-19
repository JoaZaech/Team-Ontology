<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import visecaLogo from "./assets/viseca-logo.svg";
import PolicyControls from "./components/PolicyControls.vue";
import ReadyWorkflow from "./components/ReadyWorkflow.vue";
import CardManagement from "./components/CardManagement.vue";

type ResearchCall = {
  tool: string;
  input: string;
  result: string;
  state: "queued" | "running" | "complete";
};

const landingStage = ref<"loading" | "blank">("loading");
const screen = ref<"workflow" | "settings" | "cards">("workflow");
const loadMessage = ref("Agent simulation is retrieving purchase and policy context.");
const researchCalls = ref<ResearchCall[]>([
  { tool: "purchase.get_request", input: "authorization_id: MOCK_AU0001", result: "Purchase request found · CHF 20.00", state: "running" },
  { tool: "card.get_context", input: "card: CA0001", result: "Card is active · no spend recorded today", state: "queued" },
  { tool: "policies.search", input: "scope: online payment", result: "Active wallet policy retrieved", state: "queued" },
  { tool: "merchant.lookup_history", input: "merchant: Alpine Basket", result: "26 prior approved purchases found", state: "queued" },
]);
let landingTimer: ReturnType<typeof setTimeout> | undefined;
let messageTimer: ReturnType<typeof setTimeout> | undefined;
const researchTimers: Array<ReturnType<typeof setTimeout>> = [];

function showBlankDestination(): void {
  landingStage.value = "blank";
  const destination = window.location.hash.slice(1);
  screen.value = destination === "cards" || destination === "settings" ? destination : "workflow";
  window.history.replaceState({}, "", `#${screen.value}`);
}

function openSettings(): void {
  screen.value = "settings";
  window.history.replaceState({}, "", "#settings");
}

function openCards(): void {
  screen.value = "cards";
  window.history.replaceState({}, "", "#cards");
}

function openWorkflow(): void {
  screen.value = "workflow";
  window.history.replaceState({}, "", "#workflow");
}

onMounted(() => {
  const loadDuration = 1500;
  messageTimer = setTimeout(() => {
    loadMessage.value = "Retrieval complete. Preparing the rulebook checks.";
  }, loadDuration / 2);
  [260, 560, 860, 1160].forEach((delay, index) => {
    researchTimers.push(setTimeout(() => {
      researchCalls.value[index].state = "complete";
      if (researchCalls.value[index + 1]) researchCalls.value[index + 1].state = "running";
    }, delay));
  });
  landingTimer = setTimeout(showBlankDestination, loadDuration);
});

onBeforeUnmount(() => {
  if (landingTimer) clearTimeout(landingTimer);
  if (messageTimer) clearTimeout(messageTimer);
  researchTimers.forEach(clearTimeout);
});
</script>

<template>
  <main v-if="landingStage === 'loading'" class="assistant-loading" aria-live="polite">
    <div class="assistant-loading__topbar">
      <img class="assistant-loading__logo" :src="visecaLogo" alt="Viseca" />
      <span class="assistant-loading__section">AI Shopping Assistant</span>
    </div>

    <section class="assistant-loading__content" aria-label="Agent simulation is retrieving context">
      <p class="assistant-loading__eyebrow">AGENT SIMULATION · RETRIEVAL</p>
      <h1>Retrieving the context<br />for this purchase.</h1>
      <p class="assistant-loading__copy">{{ loadMessage }}</p>
      <div class="assistant-loading__progress" aria-hidden="true"><span></span></div>
      <p class="assistant-loading__status">Connecting purchase, card and policy signals</p>

      <section class="assistant-research" aria-label="Simulated assistant research activity">
        <div class="assistant-research__heading">
          <span>RETRIEVAL TRACE</span>
          <small>SIMULATED</small>
        </div>
        <ol class="assistant-research__calls">
          <li v-for="call in researchCalls" :key="call.tool" :class="`is-${call.state}`">
            <span class="assistant-research__state" aria-hidden="true">{{ call.state === "complete" ? "✓" : call.state === "running" ? "" : "·" }}</span>
            <div>
              <p><code>{{ call.tool }}</code><span>{{ call.input }}</span></p>
              <small>{{ call.state === "complete" ? call.result : call.state === "running" ? "Querying simulated context…" : "Queued" }}</small>
            </div>
          </li>
        </ol>
        <p class="assistant-research__note">Mock retrieval only — no external systems are contacted.</p>
      </section>
    </section>
  </main>

  <ReadyWorkflow v-else-if="screen === 'workflow'" @open-settings="openSettings" />
  <PolicyControls v-else-if="screen === 'settings'" @open-workflow="openWorkflow" @open-cards="openCards" />
  <CardManagement v-else @open-workflow="openWorkflow" @open-settings="openSettings" />
</template>
