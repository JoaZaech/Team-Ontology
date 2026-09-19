<script setup lang="ts">
export type PolicyRecommendation = {
  id: string;
  name: string;
  description: string;
  category: "Spending" | "Security" | "Cards" | "Notifications";
  rule: string;
  signals: Array<{ value: string; label: string }>;
};

defineProps<{ recommendation: PolicyRecommendation }>();
const emit = defineEmits<{ add: [recommendation: PolicyRecommendation]; dismiss: [recommendationId: string] }>();
</script>

<template>
  <section class="policy-recommendation" aria-labelledby="policy-recommendation-title">
    <div class="policy-recommendation__content">
      <div class="policy-recommendation__heading">
        <span class="policy-recommendation__spark" aria-hidden="true">✦</span>
        <div>
          <p class="policy-eyebrow">POLICY SUGGESTION</p>
          <h2 id="policy-recommendation-title">{{ recommendation.name }}</h2>
          <p class="policy-recommendation__description">{{ recommendation.description }}</p>
          <p class="policy-recommendation__rule"><strong>Suggested rule:</strong> {{ recommendation.rule }}</p>
          <div class="policy-recommendation__signals" aria-label="Why this policy was recommended">
            <span v-for="signal in recommendation.signals" :key="signal.label"><b>{{ signal.value }}</b>{{ signal.label }}</span>
          </div>
        </div>
      </div>
    </div>
    <div class="policy-recommendation__actions">
      <p>Draft only — based on approved activity and familiar merchant relationships.</p>
      <div>
        <button type="button" class="policy-recommendation__dismiss" @click="emit('dismiss', recommendation.id)">Not now</button>
        <button type="button" class="policy-recommendation__add" @click="emit('add', recommendation)">Add policy</button>
      </div>
    </div>
  </section>
</template>
