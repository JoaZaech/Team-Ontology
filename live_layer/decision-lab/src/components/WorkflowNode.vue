<script setup lang="ts">
import { Handle, Position } from "@vue-flow/core";
import type { NodeProps } from "@vue-flow/core";

export type WorkflowNodeState = "waiting" | "active" | "complete" | "approved" | "declined" | "review";

export interface WorkflowNodeData {
  step: string;
  title: string;
  annotation: string;
  state: WorkflowNodeState;
}

defineProps<NodeProps<WorkflowNodeData>>();
</script>

<template>
  <div class="workflow-node" :class="`is-${data.state}`">
    <Handle type="target" :position="Position.Left" />
    <span class="workflow-node__step">{{ data.step }}</span>
    <strong>{{ data.title }}</strong>
    <p>{{ data.annotation }}</p>
    <span class="workflow-node__state" aria-hidden="true">
      <template v-if="data.state === 'complete' || data.state === 'approved'">✓</template>
      <template v-else-if="data.state === 'declined'">×</template>
      <template v-else-if="data.state === 'review'">!</template>
      <template v-else-if="data.state === 'active'"><span class="workflow-node__pulse"></span></template>
      <template v-else>•</template>
    </span>
    <Handle type="source" :position="Position.Right" />
  </div>
</template>
