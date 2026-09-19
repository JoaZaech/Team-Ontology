<script setup lang="ts">
import { computed, ref } from "vue";
import {
  ASSISTANT_AUTHORITIES,
  SPEND_CATEGORIES,
  type AssistantAuthority,
  type DynamicWalletPolicy,
  type DynamicWalletPolicyPatch,
  type ReviewTrigger,
  type SpendCategory,
} from "../policy-settings";

const props = defineProps<{ policy: DynamicWalletPolicy; saving: boolean }>();
const emit = defineEmits<{ change: [patch: Partial<DynamicWalletPolicyPatch>] }>();

const selectedCategory = ref<SpendCategory>("Groceries");

const authorityCopy: Record<AssistantAuthority, { title: string; description: string; summary: string; expected: string }> = {
  review: {
    title: "Ask me every time",
    description: "The assistant prepares a decision, then waits for your approval.",
    summary: "Every eligible purchase still needs your approval.",
    expected: "You will be asked, even when the purchase matches your usual behaviour.",
  },
  trusted: {
    title: "Approve trusted purchases",
    description: "The assistant may approve familiar, low-risk purchases that meet every rule you set.",
    summary: "Trusted purchases can be approved; anything new is sent to you.",
    expected: "A familiar, normal purchase can be approved automatically when no prompt applies.",
  },
  autopilot: {
    title: "Full approval access",
    description: "The assistant may approve purchases within your guardrails without asking first.",
    summary: "The assistant can act automatically, but never outside your guardrails.",
    expected: "Any purchase within your rules can be approved automatically unless you kept a prompt for it.",
  },
};

const enabledStatus = computed(() => props.policy.enabled ? "Enabled" : "Disabled");
const authoritySummary = computed(() => authorityCopy[props.policy.assistantAuthority].summary);
const expectedDecision = computed(() => authorityCopy[props.policy.assistantAuthority].expected);
const categoryLimit = computed(() => props.policy.adaptiveSpendProfiles[selectedCategory.value]);
const promptReasons = computed(() => [
  hasPrompt("new_merchant") ? "a new merchant" : "",
  hasPrompt("online_purchase") ? "an online purchase" : "",
  hasPrompt("unusual_activity") ? "unusual spending" : "",
].filter(Boolean).join(", "));

function setEnabled(enabled: boolean): void {
  emit("change", { enabled });
}

function setAuthority(level: AssistantAuthority): void {
  emit("change", { assistantAuthority: level });
}

function setDailyLimit(event: Event): void {
  const input = event.target as HTMLInputElement;
  const dailySpendingLimitChf = Number(input.value);
  if (Number.isFinite(dailySpendingLimitChf) && dailySpendingLimitChf >= 0) emit("change", { dailySpendingLimitChf });
}

function selectCategory(category: SpendCategory): void {
  selectedCategory.value = category;
}

function hasPrompt(trigger: ReviewTrigger): boolean {
  return props.policy.reviewTriggers.includes(trigger);
}

function togglePrompt(trigger: ReviewTrigger): void {
  const reviewTriggers = hasPrompt(trigger)
    ? props.policy.reviewTriggers.filter((item) => item !== trigger)
    : [...props.policy.reviewTriggers, trigger];
  emit("change", { reviewTriggers });
}
</script>

<template>
  <section class="dynamic-policy" :class="{ 'dynamic-policy--disabled': !policy.enabled }" aria-labelledby="dynamic-policy-title">
    <header class="dynamic-policy__header">
      <div class="dynamic-policy__heading">
        <span class="dynamic-policy__icon" aria-hidden="true">✦</span>
        <div>
          <p class="policy-eyebrow">ADAPTIVE CONTROL</p>
          <h2 id="dynamic-policy-title">Dynamic wallet policy</h2>
          <p>Set the boundaries once, then decide how much approval authority your assistant receives.</p>
        </div>
      </div>
      <div class="dynamic-policy__status">
        <span :class="['dynamic-policy__state', { 'dynamic-policy__state--off': !policy.enabled }]">{{ saving ? "Saving…" : enabledStatus }}</span>
        <button
          type="button"
          class="policy-switch"
          :class="{ 'policy-switch--on': policy.enabled }"
          role="switch"
          :aria-checked="policy.enabled"
          aria-label="Enable dynamic wallet policy"
          :disabled="saving"
          @click="setEnabled(!policy.enabled)"
        ><span></span></button>
      </div>
    </header>

    <div v-if="policy.enabled" class="dynamic-policy__body">
      <div class="dynamic-policy__precedence"><span>✓</span><p><strong>Your rules take priority.</strong> The assistant and the decision engine can only approve a purchase after it meets every boundary below.</p></div>

      <section class="dynamic-step" aria-labelledby="guardrails-title">
        <div class="dynamic-step__number">01</div>
        <div class="dynamic-step__content">
          <div class="dynamic-step__intro"><h3 id="guardrails-title">Set your guardrails</h3><p>Your daily limit is a hard boundary. The per-purchase maximum is calculated dynamically in the next step.</p></div>
          <div class="dynamic-limits">
            <label><span>Daily spending limit</span><div><b>CHF</b><input :value="policy.dailySpendingLimitChf" min="0" step="50" type="number" aria-label="Daily spending limit in CHF" :disabled="saving" @change="setDailyLimit" /></div></label>
          </div>
        </div>
      </section>

      <section class="dynamic-step" aria-labelledby="behaviour-title">
        <div class="dynamic-step__number">02</div>
        <div class="dynamic-step__content">
          <div class="dynamic-step__intro"><h3 id="behaviour-title">Calculate a maximum for each category</h3><p>The policy learns from your card activity and calculates a maximum instead of asking you to set one amount for every purchase.</p></div>
          <div class="dynamic-behaviour">
            <article><span>▣</span><div><strong>Familiar merchants</strong><small>Places you have previously paid with this card.</small></div></article>
            <article><span>CHF</span><div><strong>Usual amount</strong><small>The range changes with each transaction category.</small></div></article>
            <article><span>◷</span><div><strong>Usual timing</strong><small>Most purchases happen during the day.</small></div></article>
          </div>
          <div class="dynamic-category-limit">
            <div><span>Dynamic maximum preview</span><h4>{{ selectedCategory }} <b>CHF {{ categoryLimit.maximumChf }}</b></h4><p>Typical range: {{ categoryLimit.typicalRange }}</p></div>
            <div class="dynamic-category-limit__choices" role="radiogroup" aria-label="Transaction category">
              <button v-for="category in SPEND_CATEGORIES" :key="category" type="button" :class="{ 'dynamic-category-limit__choice--selected': selectedCategory === category }" role="radio" :aria-checked="selectedCategory === category" @click="selectCategory(category)">{{ category }}</button>
            </div>
            <p class="dynamic-category-limit__why"><strong>Why this maximum?</strong> {{ categoryLimit.explanation }}</p>
          </div>
          <div class="dynamic-expectation"><span>Expected behaviour</span><p>A daytime, in-store purchase from a familiar merchant within the calculated category maximum matches your usual card activity.</p><small>The maximum is recalculated as your spending pattern and remaining daily budget change. A request outside it is explained and handled according to your approval settings.</small></div>
        </div>
      </section>

      <section class="dynamic-step" aria-labelledby="prompts-title">
        <div class="dynamic-step__number">03</div>
        <div class="dynamic-step__content">
          <div class="dynamic-step__intro"><h3 id="prompts-title">Keep approval for important moments</h3><p>Choose the cases where the assistant must always come back to you.</p></div>
          <div class="dynamic-prompts">
            <label><input :checked="hasPrompt('new_merchant')" :disabled="saving" type="checkbox" @change="togglePrompt('new_merchant')" /><span><strong>New merchants</strong><small>Ask before a first purchase with a merchant.</small></span></label>
            <label><input :checked="hasPrompt('online_purchase')" :disabled="saving" type="checkbox" @change="togglePrompt('online_purchase')" /><span><strong>Online purchases</strong><small>Ask before a card-not-present purchase.</small></span></label>
            <label><input :checked="hasPrompt('unusual_activity')" :disabled="saving" type="checkbox" @change="togglePrompt('unusual_activity')" /><span><strong>Unusual activity</strong><small>Ask when spending does not match your usual pattern.</small></span></label>
          </div>
        </div>
      </section>

      <section class="dynamic-step" aria-labelledby="authority-title">
        <div class="dynamic-step__number">04</div>
        <div class="dynamic-step__content">
          <div class="dynamic-step__intro"><h3 id="authority-title">Choose assistant approval access</h3><p>Move between levels any time. More access never overrides steps 01–03.</p></div>
          <div class="dynamic-authority" role="radiogroup" aria-label="Assistant approval access">
            <button v-for="level in ASSISTANT_AUTHORITIES" :key="level" type="button" :class="['dynamic-authority__option', { 'dynamic-authority__option--selected': policy.assistantAuthority === level }]" role="radio" :aria-checked="policy.assistantAuthority === level" :disabled="saving" @click="setAuthority(level)"><span class="dynamic-authority__radio"></span><strong>{{ authorityCopy[level].title }}</strong><small>{{ authorityCopy[level].description }}</small></button>
          </div>
        </div>
      </section>

      <section class="dynamic-decision-explainer" aria-labelledby="decision-explainer-title">
        <div><p class="policy-eyebrow">WHAT DYNAMIC MEANS TODAY</p><h3 id="decision-explainer-title">Expected decisions, explained</h3></div>
        <div class="dynamic-decision-explainer__cards">
          <article class="dynamic-decision dynamic-decision--match"><span>Matches your pattern</span><strong>Familiar merchant · CHF 75 · daytime</strong><p>{{ expectedDecision }}</p></article>
          <article class="dynamic-decision dynamic-decision--review"><span>Needs your attention</span><strong>New online merchant · CHF 420</strong><p v-if="promptReasons">You will be asked because you chose to review {{ promptReasons }}.</p><p v-else>This will be handled using your selected approval access and hard limits.</p></article>
        </div>
      </section>

      <footer class="dynamic-policy__footer"><span class="dynamic-policy__live"><i></i>{{ authoritySummary }}</span><span>Revision {{ policy.revision }} · {{ saving ? "Saving" : "Preview only" }}</span></footer>
    </div>
    <div v-else class="dynamic-policy__disabled-copy"><span>Dynamic approval is off.</span> Turn it on to set user-first guardrails and assistant access.</div>
  </section>
</template>
