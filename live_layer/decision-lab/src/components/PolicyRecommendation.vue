<script setup lang="ts">
import type { PolicyRecommendation } from "../types";

defineProps<{ recommendation: PolicyRecommendation }>();
const emit = defineEmits<{ apply: [recommendation: PolicyRecommendation]; dismiss: [recommendationId: string] }>();
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
      <p>Draft only — based on approved purchase evidence. Past declines are context, not inferred preferences.</p>
      <div>
        <button type="button" class="policy-recommendation__dismiss" @click="emit('dismiss', recommendation.recommendation_id)">Not now</button>
        <button type="button" class="policy-recommendation__add" @click="emit('apply', recommendation)">Apply recommendation</button>
      </div>
    </div>
  </section>
</template>
