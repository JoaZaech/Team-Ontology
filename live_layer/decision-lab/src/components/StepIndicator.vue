<script setup lang="ts">
interface Step {
  title: string;
  detail: string;
}

const props = defineProps<{
  steps: Step[];
  stage: number;
}>();

function stepClass(index: number): string {
  if (index < props.stage) return "done";
  if (index === props.stage) return "active";
  return "";
}
</script>

<template>
  <div class="steps" aria-label="Demo progress">
    <div v-for="(step, index) in steps" :key="step.title" class="step" :class="stepClass(index)">
      <div class="number">{{ index + 1 }}</div>
      <div>
        <strong>{{ step.title }}</strong>
        <small>{{ step.detail }}</small>
      </div>
    </div>
  </div>
</template>
