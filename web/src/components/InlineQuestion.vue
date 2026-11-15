<template>
  <button
    type="button"
    class="inline-ask"
    :data-tooltip="question"
    :data-tip-dismissed="tipDismissed ? 'true' : undefined"
    :aria-label="`追问：${question}`"
    @click="emit('ask', question)"
    @pointerleave="tipDismissed = false"
    @blur="tipDismissed = false"
    @keydown.esc="dismissTip"
  >
    <UiIcon name="ask" />
  </button>
</template>

<script setup lang="ts">
import { ref } from "vue";
import UiIcon from "./UiIcon.vue";

defineProps<{ question: string }>();
const emit = defineEmits<{ (event: "ask", question: string): void }>();
const tipDismissed = ref(false);

function dismissTip(event: KeyboardEvent): void {
  if (tipDismissed.value) {
    return;
  }
  tipDismissed.value = true;
  event.preventDefault();
  event.stopPropagation();
}
</script>
