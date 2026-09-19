<script lang="ts">
import { ref } from "vue";

const openExplanations = ref(new Set<string>());
</script>

<script setup lang="ts">
import { computed } from "vue";
import { Handle, Position } from "@vue-flow/core";
import type { NodeProps } from "@vue-flow/core";

export type WorkflowNodeState = "waiting" | "active" | "complete" | "approved" | "declined" | "review";

export interface WorkflowNodeData {
  step: string;
  system?: string;
  orientation?: "horizontal" | "vertical";
  title: string;
  annotation: string;
  explanation: string[];
  state: WorkflowNodeState;
}

const props = defineProps<NodeProps<WorkflowNodeData>>();

const explanationOpen = computed(() => openExplanations.value.has(props.id));

function toggleExplanation(): void {
  openExplanations.value = openExplanations.value.has(props.id) ? new Set() : new Set([props.id]);
}
</script>

<template>
  <div class="workflow-node" :class="[`is-${data.state}`, { 'workflow-node--vertical': data.orientation === 'vertical' }]">
    <Handle type="target" :position="data.orientation === 'vertical' ? Position.Top : Position.Left" />
    <span class="workflow-node__step">{{ data.step }}</span>
    <span v-if="data.system" class="workflow-node__system">{{ data.system }}</span>
    <strong>{{ data.title }}</strong>
    <p>{{ data.annotation }}</p>
    <div class="workflow-node__details nodrag" @mousedown.stop @pointerdown.stop>
      <button
        class="workflow-node__details-toggle nodrag"
        type="button"
        :aria-expanded="explanationOpen"
        @click.stop="toggleExplanation"
      >
        Why this step? <span aria-hidden="true">{{ explanationOpen ? "⌃" : "⌄" }}</span>
      </button>
      <ul v-if="explanationOpen">
        <li v-for="item in data.explanation" :key="item">{{ item }}</li>
      </ul>
    </div>
    <span class="workflow-node__state" aria-hidden="true">
      <template v-if="data.state === 'complete' || data.state === 'approved'">✓</template>
      <template v-else-if="data.state === 'declined'">×</template>
      <template v-else-if="data.state === 'review'">!</template>
      <template v-else-if="data.state === 'active'"><span class="workflow-node__pulse"></span></template>
      <template v-else>•</template>
    </span>
    <Handle type="source" :position="data.orientation === 'vertical' ? Position.Bottom : Position.Right" />
  </div>
</template>
