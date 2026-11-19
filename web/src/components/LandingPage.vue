<template>
  <main class="recipe-page" aria-labelledby="recipe-title">
    <div class="recipe-hero">
      <header class="recipe-heading">
        <p class="breadcrumb"><span>餐桌手记</span><UiIcon name="chevron" /><span>家常菜</span></p>
        <h1 id="recipe-title" class="recipe-title" tabindex="-1">{{ recipe.title }}</h1>
        <p class="recipe-deck">{{ recipe.description }}</p>
        <RecipeMeta :servings="servings" adjustable @update:servings="emit('update:servings', $event)" />
      </header>
      <figure>
        <img class="recipe-photo" :src="recipe.photo" alt="浅色瓷碗里，金黄鸡蛋与鲜红番茄拌成一盘家常菜" fetchpriority="high" />
        <figcaption class="photo-caption">家常的味道，趁热吃。</figcaption>
      </figure>
    </div>
    <div class="recipe-workspace">
      <section class="ingredients" aria-labelledby="ingredients-title">
        <h2 id="ingredients-title" class="ingredients-heading">备好食材</h2>
        <IngredientList :servings="servings" :checked-ids="checkedIds" @update:checked-ids="emit('update:checkedIds', $event)" @ask="emit('ask', $event)" />
        <p class="pantry-note">另备少许食用油和盐，<br />喜欢的话，加一点葱花。</p>
        <p class="ingredient-progress" role="status" aria-live="polite">{{ progress }}</p>
      </section>
      <section class="steps-section" aria-labelledby="steps-title">
        <div class="section-heading"><h2 id="steps-title">慢慢做</h2><p>{{ recipe.steps.length }} 步，按自己的节奏来。</p></div>
        <div class="steps-stream">
          <article v-for="(step, index) in recipe.steps" :key="step.id" class="step" :class="{ 'is-active': activeStep === step.id }">
            <div class="step-heading">
              <h3><button type="button" class="step-focus" :aria-label="`专注第 ${index + 1} 步：${step.title}`" :aria-pressed="activeStep === step.id" @click="emit('update:activeStep', activeStep === step.id ? '' : step.id)"><span class="step-number">{{ String(index + 1).padStart(2, '0') }}</span>{{ step.title }}</button></h3>
              <InlineQuestion :question="step.question" @ask="emit('ask', $event)" />
            </div>
            <div class="step-content"><p><template v-if="step.lead">{{ step.lead }}<br /></template>{{ step.before }}<mark>{{ step.highlight }}</mark>{{ step.after }}</p></div>
            <span v-if="activeStep === step.id" class="step-active-note">正在做这一步</span>
          </article>
        </div>
      </section>
    </div>
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

const props = defineProps<{ checkedIds: readonly string[]; servings: number; activeStep: string }>();
const emit = defineEmits<{
  (event: "update:checkedIds", ids: string[]): void;
  (event: "update:servings", value: number): void;
  (event: "update:activeStep", id: string): void;
  (event: "ask", question: string): void;
}>();
const progress = computed(() => props.checkedIds.length === recipe.ingredients.length
  ? "都备好了，可以开火啦。"
  : `已备好 ${props.checkedIds.length} / ${recipe.ingredients.length} 样食材`);
</script>
