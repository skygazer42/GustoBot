<template>
  <div class="recipe-meta">
    <span><UiIcon name="clock" />{{ recipe.minutes }} 分钟</span>
    <div v-if="adjustable" class="servings-control" role="group" aria-label="调整食谱份量">
      <UiIcon name="people" />
      <button type="button" aria-label="减少一人份" :disabled="servings <= 1" @click="emit('update:servings', servings - 1)">−</button>
      <output aria-live="polite">{{ servings }} 人份</output>
      <button type="button" aria-label="增加一人份" :disabled="servings >= 8" @click="emit('update:servings', servings + 1)">+</button>
    </div>
    <span v-else><UiIcon name="people" />{{ servings }} 人份</span>
  </div>
</template>

<script setup lang="ts">
import { recipe } from "../data/recipe";
import UiIcon from "./UiIcon.vue";

withDefaults(defineProps<{ servings: number; adjustable?: boolean }>(), { adjustable: false });
const emit = defineEmits<{ (event: "update:servings", value: number): void }>();
</script>
