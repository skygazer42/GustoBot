<template>
  <main class="recipe-page" aria-labelledby="recipe-title">
    <a class="recipe-back-link" :href="catalogHref" @click="emit('navigate', $event)"><UiIcon name="arrow" />返回菜谱目录</a>
    <div class="recipe-hero" :class="{ 'without-photo': !recipe.cover_image || failedCover }">
      <header class="recipe-heading"><p class="breadcrumb"><span>餐桌手记</span><UiIcon name="chevron" /><span>{{ recipe.categories.join(' / ') || '菜谱' }}</span></p><h1 id="recipe-title" class="recipe-title" tabindex="-1">{{ recipe.name }}</h1><p class="recipe-deck"><a href="#ingredients-title">{{ recipe.ingredients.length }} 样用料</a><span aria-hidden="true"> · </span><a href="#steps-title">{{ recipe.steps.length }} 步做法</a></p><RecipeMeta :recipe="recipe" :servings="servings" adjustable @update:servings="emit('update:servings', $event)" /><details v-if="recipe.description" class="recipe-description"><summary>原文简介</summary><p>{{ recipe.description }}</p></details></header>
      <figure v-if="recipe.cover_image && !failedCover"><img class="recipe-photo" :src="recipe.cover_image.url" :alt="recipe.cover_image.alt || `${recipe.name}的原文配图`" fetchpriority="high" @error="failedCover = true" /><figcaption class="photo-caption">原文配图<span v-if="recipe.cover_image.author"> · {{ recipe.cover_image.author }}</span><span v-if="recipe.cover_image.license"> · {{ recipe.cover_image.license }}</span></figcaption></figure>
      <div v-else class="detail-text-cover"><span>{{ recipe.categories[0] || '餐桌手记' }}</span><p>{{ recipe.name }}</p><small>原文未提供可用封面，以做法为准。</small></div>
    </div>
    <div class="recipe-workspace">
      <section class="ingredients" aria-labelledby="ingredients-title"><h2 id="ingredients-title" class="ingredients-heading">备好食材</h2><IngredientList :recipe="recipe" :servings="servings" :checked-ids="checkedIds" @update:checked-ids="emit('update:checkedIds', $event)" @ask="emit('ask', $event)" /><p v-if="servings !== null && servings !== recipe.servings_count" class="pantry-note">明确数值的用量已按份数换算；“适量”等原文用量保持原样。</p><p v-if="recipe.ingredients.length" class="ingredient-progress" role="status" aria-live="polite">{{ progress }}</p><p v-else class="pantry-note">原文未单独列出食材，请结合做法确认。</p></section>
      <section class="steps-section" aria-labelledby="steps-title"><div class="section-heading"><h2 id="steps-title">做法</h2><p>照着原文，慢慢做。</p></div><div class="steps-stream"><article v-for="(step, index) in recipe.steps" :key="index" class="step" :class="{ 'is-active': activeStep === String(index) }"><div class="step-heading"><h3><button type="button" class="step-focus" :aria-label="`专注第 ${index + 1} 步`" :aria-pressed="activeStep === String(index)" @click="emit('update:activeStep', activeStep === String(index) ? '' : String(index))"><span class="step-number">{{ index + 1 }}.</span><span class="sr-only">专注这一步</span></button></h3><InlineQuestion :question="`这份做法的第 ${index + 1} 步应该怎么做？请解释：${step.slice(0, 160)}`" @ask="emit('ask', $event)" /></div><div class="step-content"><p>{{ step }}</p><figure v-for="image in stepImages(index + 1)" :key="image.url" class="step-image"><img :src="image.url" :alt="image.alt || `第 ${index + 1} 步原文配图`" loading="lazy" /><figcaption>{{ image.author || '原文配图' }}<span v-if="image.license"> · {{ image.license }}</span></figcaption></figure></div><span v-if="activeStep === String(index)" class="step-active-note">正在做这一步</span></article></div><p v-if="!recipe.steps.length" class="pantry-note">原文未提供分步做法。</p><section v-if="recipe.tips.length" class="recipe-tips" aria-labelledby="tips-title"><h2 id="tips-title">原文提示</h2><ul><li v-for="(tip, index) in recipe.tips" :key="index">{{ tip }}</li></ul></section></section>
    </div>
    <footer class="recipe-provenance"><div><p class="eyebrow">做法的来处</p><p>{{ recipe.source.attribution || recipe.source.provider }}<span v-if="recipe.source.license"> · {{ recipe.source.license }}</span></p><p class="provenance-note">按原始资料整理，用量与操作以原文为依据；资料开放许可由上游声明。</p></div><div class="provenance-links"><a v-if="originalUrl" :href="originalUrl" target="_blank" rel="noopener noreferrer">查看菜谱原文<UiIcon name="expand" /></a><a v-if="licenseUrl" :href="licenseUrl" target="_blank" rel="noopener noreferrer">许可说明</a></div></footer>
  </main>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { sourceUrl, type RecipeDetail } from "../data/recipe";
import IngredientList from "./IngredientList.vue";
import InlineQuestion from "./InlineQuestion.vue";
import RecipeMeta from "./RecipeMeta.vue";
import UiIcon from "./UiIcon.vue";

const props = defineProps<{ recipe: RecipeDetail; checkedIds: readonly string[]; servings: number | null; activeStep: string; catalogHref: string }>();
const emit = defineEmits<{
  (event: "update:checkedIds", ids: string[]): void;
  (event: "update:servings", value: number): void;
  (event: "update:activeStep", id: string): void;
  (event: "ask", question: string): void;
  (event: "navigate", eventObject: MouseEvent): void;
}>();
const failedCover = ref(false);
const originalUrl = computed(() => sourceUrl(props.recipe.source));
const licenseUrl = computed(() => /^https?:\/\//i.test(props.recipe.source.license_url ?? "") ? props.recipe.source.license_url : null);
const progress = computed(() => props.checkedIds.length === props.recipe.ingredients.length ? "都备好了，可以开始做菜了。" : `已备好 ${props.checkedIds.length} / ${props.recipe.ingredients.length} 样食材`);
function stepImages(index: number) { return props.recipe.images.filter((image) => image.role === "step" && image.step_index === index); }
watch(() => props.recipe.version, () => { failedCover.value = false; });
</script>

<style scoped>
.recipe-deck a { display: inline-flex; align-items: center; min-height: 44px; color: var(--clay); text-decoration-thickness: 1px; text-underline-offset: 4px; }
.recipe-deck a:hover { color: var(--clay-hover); }
.recipe-workspace h2 { scroll-margin-top: 104px; }
.recipe-back-link { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; margin: -16px 0 20px; color: var(--muted); text-decoration: none; font-size: 13px; }
.recipe-back-link .ui-icon { width: 16px; transform: rotate(180deg); }
.recipe-back-link:hover { color: var(--clay); }
.recipe-description { margin-top: 16px; color: var(--muted); font-size: 13px; }
.recipe-description summary { min-height: 32px; }
.recipe-description p { margin: 8px 0 0; white-space: pre-wrap; }
.detail-text-cover { display: flex; flex-direction: column; justify-content: center; min-height: 220px; padding: 30px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); }
.detail-text-cover > span { color: var(--clay); font-size: 13px; }
.detail-text-cover p { margin: 10px 0; font: 600 29px/1.6 var(--serif); }
.detail-text-cover small { color: var(--muted); font-size: 13px; }
.step { padding-top: 20px; }
.step-heading { position: absolute; top: 19px; left: 22px; right: 18px; justify-content: space-between; pointer-events: none; }
.step-heading button { pointer-events: auto; }
.step-focus { justify-content: center; min-width: 28px; min-height: 44px; }
.step-content { max-width: none; padding-top: 5px; padding-right: 50px; }
.step-content p { white-space: pre-wrap; overflow-wrap: anywhere; }
.step-image { max-width: 540px; margin: 18px 0 0; }
.step-image img { display: block; width: 100%; max-height: 400px; object-fit: contain; border-radius: 4px; }
.step-image figcaption { margin-top: 6px; color: var(--muted); font-size: 13px; }
.recipe-tips { margin-top: 28px; }
.recipe-tips h2 { margin: 0 0 12px; font: 600 22px/1.6 var(--serif); }
.recipe-tips ul { padding-left: 20px; font-size: 14px; color: var(--muted); }
.recipe-tips li { white-space: pre-wrap; overflow-wrap: anywhere; margin-block: 9px; }
.recipe-provenance { display: flex; justify-content: space-between; gap: 24px; margin-top: 42px; padding-top: 24px; border-top: 1px solid var(--line); font-size: 13px; color: var(--muted); }
.recipe-provenance p { margin: 0 0 4px; }
.provenance-note { max-width: 580px; font-size: 13px; }
.provenance-links { display: flex; flex-wrap: wrap; align-items: start; gap: 16px; }
.provenance-links a { display: inline-flex; align-items: center; gap: 6px; min-height: 44px; color: var(--clay); white-space: nowrap; }
.provenance-links .ui-icon { width: 14px; }
@media (max-width: 680px) { .detail-text-cover { min-height: 160px; padding: 24px; } .detail-text-cover p { font-size: 24px; } .step-heading { left: 14px; right: 8px; } .step-content { padding-left: 38px; } .recipe-provenance { flex-direction: column; gap: 10px; } }
</style>
