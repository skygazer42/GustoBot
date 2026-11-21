<template>
  <div class="recipe-meta">
    <span v-if="duration"><UiIcon name="clock" />{{ duration }}</span>
    <div v-if="adjustable && servings !== null && recipe.servings_count !== null" class="servings-control" role="group" aria-label="调整食谱份量"><UiIcon name="people" /><button type="button" aria-label="减少一人份" :disabled="servings <= 1" @click="emit('update:servings', servings - 1)">−</button><output aria-live="polite">{{ servings }} 人份</output><button type="button" aria-label="增加一人份" :disabled="servings >= 100" @click="emit('update:servings', servings + 1)">+</button></div>
    <span v-else><UiIcon name="people" />{{ servings !== null ? `${servings} 人份` : recipe.servings || '按原文用量' }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { recipeDuration, type RecipeSummary } from "../data/recipe";
import UiIcon from "./UiIcon.vue";

const props = withDefaults(defineProps<{ recipe: RecipeSummary; servings: number | null; adjustable?: boolean }>(), { adjustable: false });
const duration = computed(() => recipeDuration(props.recipe));
const emit = defineEmits<{ (event: "update:servings", value: number): void }>();
</script>
