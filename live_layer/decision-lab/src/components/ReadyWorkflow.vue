<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, onMounted, ref } from "vue";
import { VueFlow } from "@vue-flow/core";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import WorkflowNode from "./WorkflowNode.vue";
import type { WorkflowNodeData, WorkflowNodeState } from "./WorkflowNode.vue";

const emit = defineEmits<{ openSettings: [] }>();

type FlowStage = "request" | "rules" | "approved" | "declined" | "review";

const stage = ref<FlowStage>("request");
let runTimer: ReturnType<typeof setTimeout> | undefined;

const nodeTypes = { workflow: markRaw(WorkflowNode) };

const stageCopy: Record<FlowStage, { badge: string; headline: string; body: string }> = {
  request: {
    badge: "Step 1 of 3 · Incoming request",
    headline: "A purchase enters the control flow.",
    body: "We read the proposed basket, amount, merchant, and confirmed customer policy before anything can be approved.",
  },
  rules: {
    badge: "Step 2 of 3 · Safeguards running",
    headline: "The rulebook checks the facts.",
    body: "Amount, basket, merchant familiarity, and recent activity are evaluated independently from the shopping assistant.",
  },
  approved: {
    badge: "Step 3 of 3 · Completed",
    headline: "Approved and recorded.",
    body: "All safeguards passed. The decision can be recorded with the evidence used to reach it.",
  },
  declined: {
    badge: "Step 3 of 3 · Safely stopped",
    headline: "Declined before payment.",
    body: "A confirmed restriction was not met, so the purchase is blocked and the reason remains visible.",
  },
  review: {
    badge: "Step 3 of 3 · Customer control",
    headline: "Paused for customer approval.",
    body: "The system cannot establish permission with confidence, so the customer—not the AI—makes the final choice.",
  },
};

const currentCopy = computed(() => stageCopy[stage.value]);

function stateFor(node: "request" | "rules" | "decision"): WorkflowNodeState {
  if (node === "request") return stage.value === "request" ? "active" : "complete";
  if (node === "rules") {
    if (stage.value === "request") return "waiting";
    return stage.value === "rules" ? "active" : "complete";
  }
  if (stage.value === "approved") return "approved";
  if (stage.value === "declined") return "declined";
  if (stage.value === "review") return "review";
  return "waiting";
}

const nodes = computed(() => [
  {
    id: "request",
    type: "workflow",
    position: { x: 0, y: 48 },
    draggable: false,
    selectable: false,
    data: {
      step: "01 · REQUEST",
      title: "Purchase received",
      annotation: stage.value === "request" ? "A new purchase is ready to be assessed." : "Purchase and policy facts are loaded.",
      state: stateFor("request"),
    } satisfies WorkflowNodeData,
  },
  {
    id: "rules",
    type: "workflow",
    position: { x: 305, y: 48 },
    draggable: false,
    selectable: false,
    data: {
      step: "02 · RULEBOOK",
      title: "Evaluate safeguards",
      annotation:
        stage.value === "rules"
          ? "Checking mandate, basket, amount, merchant, and activity."
          : "Every check creates a visible pass, fail, or review result.",
      state: stateFor("rules"),
    } satisfies WorkflowNodeData,
  },
  {
    id: "decision",
    type: "workflow",
    position: { x: 610, y: 48 },
    draggable: false,
    selectable: false,
    data: {
      step: "03 · OUTCOME",
      title:
        stage.value === "approved"
          ? "Approved"
          : stage.value === "declined"
            ? "Declined"
            : stage.value === "review"
              ? "Human review"
              : "Decision ready",
      annotation:
        stage.value === "approved"
          ? "All applicable safeguards passed."
          : stage.value === "declined"
            ? "A policy restriction safely stopped this purchase."
            : stage.value === "review"
              ? "The customer decides when evidence is uncertain."
              : "The final result appears after evaluation.",
      state: stateFor("decision"),
    } satisfies WorkflowNodeData,
  },
]);

const edges = computed(() => [
  {
    id: "request-rules",
    source: "request",
    target: "rules",
    type: "smoothstep",
    animated: stage.value === "request" || stage.value === "rules",
    class: stage.value === "request" ? "workflow-edge" : "workflow-edge workflow-edge--complete",
  },
  {
    id: "rules-decision",
    source: "rules",
    target: "decision",
    type: "smoothstep",
    animated: stage.value === "rules",
    class: ["approved", "declined", "review"].includes(stage.value)
      ? "workflow-edge workflow-edge--complete"
      : "workflow-edge",
  },
]);

function runExample(outcome: Exclude<FlowStage, "request" | "rules"> = "approved"): void {
  if (runTimer) clearTimeout(runTimer);
  stage.value = "request";
  runTimer = setTimeout(() => {
    stage.value = "rules";
    runTimer = setTimeout(() => {
      stage.value = outcome;
      runTimer = undefined;
    }, 1350);
  }, 900);
}

onMounted(() => runExample());
onBeforeUnmount(() => {
  if (runTimer) clearTimeout(runTimer);
});
</script>

<template>
  <main class="ready-page">
    <header class="ready-page__topbar">
      <span class="ready-page__brand">Viseca</span>
      <div class="ready-page__topbar-actions">
        <button class="ready-page__settings" type="button" @click="emit('openSettings')">Wallet policies</button>
        <span class="ready-page__section">AI Shopping Assistant</span>
      </div>
    </header>

    <section class="ready-page__intro" aria-labelledby="workflow-title">
      <p class="ready-page__eyebrow">DECISION FLOW</p>
      <h1 id="workflow-title">A clear path from purchase to decision.</h1>
      <p>{{ currentCopy.body }}</p>
    </section>

    <section class="ready-workflow" aria-labelledby="workflow-state">
      <div class="ready-workflow__caption">
        <div>
          <span>{{ currentCopy.badge }}</span>
          <h2 id="workflow-state">{{ currentCopy.headline }}</h2>
        </div>
        <p>Example workflow</p>
      </div>

      <div class="ready-workflow__canvas" aria-label="Three step automated purchase decision workflow">
        <VueFlow
          :nodes="nodes"
          :edges="edges"
          :node-types="nodeTypes"
          :nodes-draggable="false"
          :nodes-connectable="false"
          :elements-selectable="false"
          :zoom-on-scroll="false"
          :zoom-on-pinch="false"
          :pan-on-drag="false"
          :min-zoom="0.72"
          :max-zoom="1.1"
          :default-viewport="{ x: 18, y: 0, zoom: 1 }"
          fit-view-on-init
        >
          <Background :gap="20" :size="1" pattern-color="#ececec" />
          <Controls :show-interactive="false" />
        </VueFlow>
      </div>

      <div class="ready-workflow__actions" aria-label="Play workflow outcomes">
        <button class="ready-workflow__button" type="button" @click="runExample('approved')">Play approval</button>
        <button class="ready-workflow__button" type="button" @click="runExample('declined')">Show decline</button>
        <button class="ready-workflow__button" type="button" @click="runExample('review')">Show human review</button>
      </div>
    </section>
  </main>
</template>
