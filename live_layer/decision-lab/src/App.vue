<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import visecaLogo from "./assets/viseca-logo.svg";
import PolicyControls from "./components/PolicyControls.vue";
import ReadyWorkflow from "./components/ReadyWorkflow.vue";

const landingStage = ref<"loading" | "blank">("loading");
const screen = ref<"workflow" | "settings">("workflow");
const loadMessage = ref("Agent simulation is retrieving purchase and policy context.");
let landingTimer: ReturnType<typeof setTimeout> | undefined;
let messageTimer: ReturnType<typeof setTimeout> | undefined;

function showBlankDestination(): void {
  landingStage.value = "blank";
  screen.value = "workflow";
  window.history.replaceState({}, "", "#workflow");
}

function openSettings(): void {
  screen.value = "settings";
  window.history.replaceState({}, "", "#settings");
}

function openWorkflow(): void {
  screen.value = "workflow";
  window.history.replaceState({}, "", "#workflow");
}

onMounted(() => {
  const loadDuration = 5000;
  messageTimer = setTimeout(() => {
    loadMessage.value = "Retrieval complete. Preparing the rulebook checks.";
  }, loadDuration / 2);
  landingTimer = setTimeout(showBlankDestination, loadDuration);
});

onBeforeUnmount(() => {
  if (landingTimer) clearTimeout(landingTimer);
  if (messageTimer) clearTimeout(messageTimer);
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
    </section>
  </main>

  <ReadyWorkflow v-else-if="screen === 'workflow'" @open-settings="openSettings" />
  <PolicyControls v-else @open-workflow="openWorkflow" />
</template>
