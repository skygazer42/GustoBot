<template>
  <main class="recipe-page" aria-labelledby="recipe-title">
    <p class="breadcrumb"><span>餐桌手记</span><UiIcon name="chevron" /><span>家常菜</span></p>
    <div class="recipe-heading">
      <div><h1 id="recipe-title" class="recipe-title" tabindex="-1">{{ recipe.title }}</h1><p class="recipe-deck">{{ recipe.description }}</p></div>
      <RecipeMeta />
    </div>
    <div class="recipe-overview">
      <section class="ingredients" aria-labelledby="ingredients-title">
        <h2 id="ingredients-title" class="ingredients-heading">备好食材</h2>
        <p class="ingredients-intro">手边有了，就轻轻勾一下。</p>
        <IngredientList :checked-ids="checkedIds" @update:checked-ids="emit('update:checkedIds', $event)" @ask="emit('ask', $event)" />
        <p class="pantry-note">另备少许食用油和盐，<br />喜欢的话，加一点葱花。</p>
        <p class="ingredient-progress" role="status" aria-live="polite">{{ progress }}</p>
      </section>
      <figure>
        <img class="recipe-photo" :src="recipe.photo" alt="浅色瓷碗里，金黄鸡蛋与鲜红番茄拌成一盘家常菜" fetchpriority="high" />
        <figcaption class="photo-caption">家常的味道，趁热吃。</figcaption>
      </figure>
    </div>
    <section class="steps-section" aria-labelledby="steps-title">
      <div class="section-heading"><h2 id="steps-title">慢慢做</h2><p>两步，就可以上桌。</p></div>
      <div class="steps-grid">
        <article v-for="(step, index) in recipe.steps" :key="step.id" class="step">
          <span class="step-number">{{ String(index + 1).padStart(2, '0') }}</span>
          <div class="step-content">
            <h3>{{ step.title }}</h3>
            <p><template v-if="step.lead">{{ step.lead }}<br /></template>{{ step.before }}<mark>{{ step.highlight }}</mark>{{ step.after }}</p>
          </div>
          <InlineQuestion :question="step.question" @ask="emit('ask', $event)" />
        </article>
      </div>
    </section>
    <footer class="recipe-footer"><UiIcon name="leaf" />不用复杂，也能好好吃饭。</footer>
  </main>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { recipe } from "../data/recipe";
import IngredientList from "./IngredientList.vue";
import InlineQuestion from "./InlineQuestion.vue";
import RecipeMeta from "./RecipeMeta.vue";
import UiIcon from "./UiIcon.vue";

const props = defineProps<{ checkedIds: readonly string[] }>();
const emit = defineEmits<{
  (event: "update:checkedIds", ids: string[]): void;
  (event: "ask", question: string): void;
}>();
const progress = computed(() => props.checkedIds.length === recipe.ingredients.length
  ? "两样都备好了，可以开火啦。"
  : `已备好 ${props.checkedIds.length} / ${recipe.ingredients.length} 样食材`);
</script>
