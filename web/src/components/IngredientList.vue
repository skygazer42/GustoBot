<template>
  <div class="ingredient-list">
    <div v-for="ingredient in recipe.ingredients" :key="ingredient.id" class="ingredient-row">
      <label class="ingredient-check">
        <input type="checkbox" :checked="checkedIds.includes(ingredient.id)" @change="toggleIngredient(ingredient.id, $event)" />
        <span class="ingredient-name">{{ ingredient.name }}</span>
        <span class="amount">{{ scaleQuantity(ingredient.quantity, servings) }}<small>{{ ingredient.unit }}</small></span>
      </label>
      <InlineQuestion v-if="showQuestions" :question="ingredient.question" @ask="emit('ask', $event)" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { recipe, scaleQuantity } from "../data/recipe";
import InlineQuestion from "./InlineQuestion.vue";

const props = withDefaults(defineProps<{ checkedIds: readonly string[]; servings: number; showQuestions?: boolean }>(), { showQuestions: true });
const emit = defineEmits<{
  (event: "update:checkedIds", ids: string[]): void;
  (event: "ask", question: string): void;
}>();

function toggleIngredient(id: string, event: Event): void {
  if (!(event.target instanceof HTMLInputElement)) {
    return;
  }
  emit("update:checkedIds", event.target.checked ? [...props.checkedIds, id] : props.checkedIds.filter((checkedId) => checkedId !== id));
}
</script>
