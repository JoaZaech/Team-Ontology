<script setup lang="ts">
import { computed, ref } from "vue";
import visecaLogo from "../assets/viseca-logo.svg";

const emit = defineEmits<{ openWorkflow: []; openSettings: [] }>();

type Card = {
  id: number;
  label: string;
  holder: string;
  ending: string;
  network: "mastercard" | "visa";
  type: string;
  color: "gold" | "slate";
  frozen: boolean;
};

const cards = ref<Card[]>([
  { id: 1, label: "Everyday card", holder: "JULIA MARTIN", ending: "1049", network: "mastercard", type: "World Mastercard Gold CHF", color: "gold", frozen: false },
  { id: 2, label: "Travel card", holder: "JULIA MARTIN", ending: "8812", network: "visa", type: "Visa Platinum EUR", color: "slate", frozen: false },
]);

const selectedId = ref(1);
const notificationEnabled = ref(true);
const lastAction = ref("");
const selectedCard = computed(() => cards.value.find((card) => card.id === selectedId.value) ?? cards.value[0]);

function toggleFreeze(): void {
  selectedCard.value.frozen = !selectedCard.value.frozen;
  lastAction.value = `${selectedCard.value.label} is now ${selectedCard.value.frozen ? "locked" : "ready to use"}.`;
}

function showAction(action: string): void {
  lastAction.value = `${action} request started for ${selectedCard.value.label}.`;
}
</script>

<template>
  <main class="policy-page cards-page">
    <header class="policy-topbar">
      <button class="policy-brand" type="button" aria-label="Return to agent simulation" @click="emit('openWorkflow')"><img :src="visecaLogo" alt="Viseca" /><span></span><strong>Settings</strong></button>
      <div class="policy-topbar__right"><button class="policy-workflow-link" type="button" aria-label="Open agent simulation" @click="emit('openWorkflow')"><span class="policy-workflow-link__full" aria-hidden="true">Agent simulation</span><span class="policy-workflow-link__short" aria-hidden="true">Simulation</span></button><button class="policy-help" type="button">Help centre</button><button class="policy-avatar" type="button" aria-label="Open account menu">JM</button></div>
    </header>
    <div class="policy-shell">
      <aside class="policy-sidebar" aria-label="Main navigation">
        <p class="policy-sidebar__label">CARD MANAGEMENT</p>
        <nav><a href="#" class="policy-nav-link">Overview</a><button type="button" class="policy-nav-link" @click="emit('openSettings')">Wallet policies</button><button type="button" class="policy-nav-link policy-nav-link--active" aria-current="page">Cards</button><a href="#" class="policy-nav-link">Activity</a></nav>
        <button type="button" class="policy-nav-link policy-nav-link--bottom" @click="emit('openSettings')">Settings</button>
      </aside>
      <section class="policy-workspace cards-workspace" aria-labelledby="cards-title">
        <div class="policy-breadcrumb"><span>Settings</span><i>/</i> Cards</div>
        <div class="cards-heading"><div><p class="policy-eyebrow">YOUR PAYMENT CARDS</p><h1 id="cards-title">Cards</h1><p>View your card details and take care of everyday card settings in one place.</p></div><button class="cards-add" type="button" @click="showAction('Additional card')">+ Add card</button></div>

        <div class="cards-layout">
          <section class="cards-selector" aria-label="Choose a card">
            <p>YOUR CARDS</p>
            <button v-for="card in cards" :key="card.id" type="button" :class="['card-choice', { 'card-choice--active': selectedId === card.id }]" @click="selectedId = card.id; lastAction = ''"><span class="card-choice__mark" :class="`card-choice__mark--${card.color}`"></span><span><strong>{{ card.label }}</strong><small>•••• {{ card.ending }}</small></span><i v-if="card.frozen">Locked</i></button>
          </section>

          <section class="cards-detail" aria-live="polite">
            <div class="payment-card" :class="[`payment-card--${selectedCard.color}`, { 'payment-card--locked': selectedCard.frozen }]">
              <div class="payment-card__top"><span>V</span><small>{{ selectedCard.frozen ? "LOCKED" : "CREDIT" }}</small></div>
              <div class="payment-card__chip" aria-hidden="true"></div>
              <div class="payment-card__number">•••• &nbsp;•••• &nbsp;•••• &nbsp;{{ selectedCard.ending }}</div>
              <div class="payment-card__bottom"><span>{{ selectedCard.holder }}</span><span v-if="selectedCard.network === 'mastercard'" class="mastercard-mark" aria-label="Mastercard"><i></i><i></i><b>mastercard</b></span><span v-else class="visa-mark" aria-label="Visa Platinum">VISA<small>Platinum</small></span></div>
            </div>
            <div class="cards-detail__meta"><div><p>{{ selectedCard.type }}</p><span>Expires 08/29 · •••• {{ selectedCard.ending }}</span></div><span :class="['card-state', { 'card-state--locked': selectedCard.frozen }]">{{ selectedCard.frozen ? "Locked" : "Active" }}</span></div>
            <div class="card-quick-actions" aria-label="Card quick actions"><button type="button" @click="toggleFreeze"><b>{{ selectedCard.frozen ? "↻" : "⌁" }}</b><span>{{ selectedCard.frozen ? "Unlock" : "Lock" }}</span></button><button type="button" @click="showAction('PIN reminder')"><b>••</b><span>View PIN</span></button><button type="button" @click="showAction('Card replacement')"><b>↻</b><span>Replace</span></button></div>
          </section>
        </div>

        <p v-if="lastAction" class="card-feedback" role="status">{{ lastAction }}</p>
        <section class="card-settings" aria-labelledby="card-settings-title"><h2 id="card-settings-title">Card settings</h2><div class="card-settings__rows"><button type="button" class="card-setting" @click="notificationEnabled = !notificationEnabled"><span class="card-setting__icon">♟</span><span><strong>Push notifications</strong><small>{{ notificationEnabled ? "On for every card payment" : "Turned off" }}</small></span><i :class="['setting-toggle', { 'setting-toggle--on': notificationEnabled }]"><b></b></i></button><button type="button" class="card-setting" @click="showAction('Security settings')"><span class="card-setting__icon">◇</span><span><strong>Security</strong><small>Online and contactless payment settings</small></span><i class="setting-arrow">›</i></button><button type="button" class="card-setting" @click="showAction('Apple Pay')"><span class="card-setting__icon card-setting__icon--pay">Pay</span><span><strong>Apple Pay</strong><small>Manage your card in Apple Wallet</small></span><i class="setting-arrow">›</i></button></div></section>
      </section>
    </div>
    <nav class="policy-mobile-nav" aria-label="Mobile navigation">
      <button type="button" @click="emit('openWorkflow')">Simulation</button>
      <button type="button" @click="emit('openSettings')">Policies</button>
      <button type="button" aria-current="page">Cards</button>
    </nav>
  </main>
</template>
