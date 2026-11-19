<template>
  <article class="paper-note">
    <p class="note-heading">当前食谱</p>
    <img class="note-photo" :src="recipe.photo" alt="浅色瓷碗里的番茄炒蛋" />
    <h2 class="note-title">{{ recipe.title }}</h2>
    <RecipeMeta :servings="servings" />
    <IngredientList :servings="servings" :checked-ids="checkedIds" :show-questions="false" @update:checked-ids="emit('update:checkedIds', $event)" />
    <p class="pantry-note">另备少许食用油和盐，喜欢的话加一点葱花。</p>
    <details class="note-details">
      <summary>{{ recipe.steps.length }} 步做法<UiIcon name="down" /></summary>
      <ol><li v-for="step in recipe.steps" :key="step.id">{{ step.summary }}</li></ol>
    </details>
    <button type="button" class="return-button" @click="emit('return')">返回食谱<UiIcon name="arrow" /></button>
  </article>
</template>

<script setup lang="ts">
import { recipe } from "../data/recipe";
import IngredientList from "./IngredientList.vue";
import RecipeMeta from "./RecipeMeta.vue";
import UiIcon from "./UiIcon.vue";

defineProps<{ checkedIds: readonly string[]; servings: number }>();
const emit = defineEmits<{
  (event: "update:checkedIds", ids: string[]): void;
  (event: "return"): void;
}>();
</script>
