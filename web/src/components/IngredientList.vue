<template>
  <div class="ingredient-list">
    <div v-for="(ingredient, index) in recipe.ingredients" :key="index" class="ingredient-row">
      <label class="ingredient-check" :class="{ 'has-long-amount': ingredientQuantity(ingredient, servings, recipe.servings_count).length > 14 }"><input type="checkbox" :checked="checkedIds.includes(String(index))" @change="toggleIngredient(String(index), $event)" /><span class="ingredient-name">{{ ingredient.name }}</span><span class="amount">{{ ingredientQuantity(ingredient, servings, recipe.servings_count) }}</span></label>
      <InlineQuestion v-if="showQuestions" :question="`这份做法中，${ingredient.name}的用量和处理有什么要注意？`" @ask="emit('ask', $event)" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ingredientQuantity, type RecipeDetail } from "../data/recipe";
import InlineQuestion from "./InlineQuestion.vue";

const props = withDefaults(defineProps<{ recipe: RecipeDetail; checkedIds: readonly string[]; servings: number | null; showQuestions?: boolean }>(), { showQuestions: true });
const emit = defineEmits<{
  (event: "update:checkedIds", ids: string[]): void;
  (event: "ask", question: string): void;
}>();

function toggleIngredient(id: string, event: Event): void {
  if (event.target instanceof HTMLInputElement) {
    emit("update:checkedIds", event.target.checked ? [...props.checkedIds, id] : props.checkedIds.filter((checkedId) => checkedId !== id));
  }
}
</script>

<style scoped>
.ingredient-check { grid-template-columns: 18px minmax(0, 1fr) minmax(0, auto); gap: 9px; padding-block: 9px; }
.ingredient-name { overflow-wrap: anywhere; font-size: 14px; }
.amount { max-width: 100px; white-space: normal; overflow-wrap: anywhere; text-align: right; font-size: 13px; font-weight: 400; }
.has-long-amount { grid-template-columns: 18px minmax(0, 1fr); row-gap: 3px; }
.has-long-amount .amount { grid-column: 2; max-width: none; justify-self: start; text-align: left; color: var(--muted); }
</style>
