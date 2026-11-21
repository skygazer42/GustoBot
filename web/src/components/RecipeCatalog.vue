<template>
  <main class="recipe-catalog" aria-labelledby="catalog-title">
    <header class="catalog-heading">
      <h1 id="catalog-title" tabindex="-1">菜谱</h1>
      <span v-if="page" class="catalog-count">{{ page.total }} 份做法</span>
    </header>
    <form class="catalog-search" role="search" @submit.prevent="submitSearch">
      <label class="catalog-query"><span>搜索菜名或食材</span><input v-model="query" type="search" name="q" maxlength="200" placeholder="想吃什么，或看看手边的食材" autocomplete="off" /></label>
      <label class="catalog-category"><span>菜谱分类</span><select :value="filters.category" @change="changeCategory"><option value="">全部分类</option><option v-for="category in categories" :key="category.name" :value="category.name">{{ category.name }} · {{ category.count }}</option></select></label>
      <button class="catalog-submit" type="submit">找菜<UiIcon name="arrow" /></button>
    </form>
    <div v-if="filters.q || filters.category" class="catalog-results-heading"><h2>筛选结果</h2><button type="button" class="catalog-clear" @click="clearFilters">清除筛选</button></div>
    <div v-if="loading" class="catalog-status" role="status"><span class="spinner" aria-hidden="true"></span>正在翻开菜谱…</div>
    <div v-else-if="error" class="catalog-status" role="status"><h2>菜谱暂时无法加载</h2><p>{{ error }}</p><button type="button" @click="loadRecipes">重试菜谱目录</button></div>
    <div v-else-if="page && page.items.length === 0" class="catalog-status" role="status"><h2>{{ filters.q || filters.category ? '没有找到菜谱' : '还没有菜谱' }}</h2><p>{{ filters.q || filters.category ? '试试其他菜名、食材，或清除筛选再看看。' : '目录准备好后，做法会出现在这里。' }}</p><button v-if="filters.q || filters.category" type="button" @click="clearFilters">清除筛选</button></div>
    <div v-else-if="page" class="recipe-grid">
      <a v-for="recipe in page.items" :key="recipe.id" class="recipe-card" :href="recipeHref(recipe.id)" :aria-label="`查看做法：${recipe.name}`" @click="emit('navigate', $event)">
        <div class="catalog-cover" :class="{ 'is-text-cover': !recipe.cover_image || failedImages.includes(recipe.id) }">
          <img v-if="recipe.cover_image && !failedImages.includes(recipe.id)" :src="recipe.cover_image.url" :alt="recipe.cover_image.alt || `${recipe.name}的原文配图`" loading="lazy" @error="failedImages.push(recipe.id)" />
          <template v-else><span class="cover-category">{{ recipe.categories[0] || '餐桌手记' }}</span><span class="cover-name">{{ recipe.name }}</span><span class="cover-caption">原文未提供可用封面</span></template>
          <span v-if="recipe.cover_image && !failedImages.includes(recipe.id)" class="cover-image-label">原文配图</span>
        </div>
        <div class="catalog-card-copy"><p class="catalog-card-category">{{ recipe.categories.slice(0, 2).join(' / ') || '菜谱' }}</p><h3>{{ recipe.name }}<UiIcon name="arrow" /></h3><p class="catalog-ingredients">{{ recipe.ingredient_names.slice(0, 4).join(' · ') || '查看原文用料' }}</p><div class="catalog-card-meta"><span>{{ recipe.step_count }} 步做法</span><span v-if="recipeDuration(recipe)">{{ recipeDuration(recipe) }}</span><span v-if="recipe.servings">{{ recipe.servings }}</span></div></div>
      </a>
    </div>
    <nav v-if="page && page.total > page.limit && !loading && !error" class="catalog-pagination" aria-label="菜谱分页"><button type="button" aria-label="上一页菜谱" :disabled="filters.offset === 0" @click="changePage(-1)">上一页</button><span>{{ Math.floor(filters.offset / page.limit) + 1 }} / {{ Math.ceil(page.total / page.limit) }}</span><button type="button" aria-label="下一页菜谱" :disabled="filters.offset + page.limit >= page.total" @click="changePage(1)">下一页</button></nav>
    <footer class="catalog-footer">依原始资料整理，保留每份做法的出处与许可。烹饪时请结合食材状况判断。</footer>
  </main>
</template>

<script setup lang="ts">
import { onScopeDispose, ref, watch } from "vue";
import { recipeDuration, type RecipeFilters, type RecipePage } from "../data/recipe";
import { listRecipes } from "../lib/recipes";
import UiIcon from "./UiIcon.vue";

const props = defineProps<{ filters: RecipeFilters }>();
const emit = defineEmits<{
  (event: "filter", filters: RecipeFilters): void;
  (event: "navigate", eventObject: MouseEvent): void;
}>();
const query = ref(props.filters.q);
const page = ref<RecipePage | null>(null);
const categories = ref<RecipePage["categories"]>([]);
const loading = ref(false);
const error = ref("");
const failedImages = ref<string[]>([]);
let controller: AbortController | null = null;

async function loadRecipes(): Promise<void> {
  controller?.abort();
  const request = new AbortController();
  controller = request;
  loading.value = true;
  error.value = "";
  try {
    const result = await listRecipes(props.filters, request.signal);
    if (controller !== request) return;
    page.value = result;
    categories.value = result.categories;
  } catch {
    if (controller === request) error.value = "请稍后重试，或检查服务是否可用。";
  } finally {
    if (controller === request) loading.value = false;
  }
}

function submitSearch(): void {
  emit("filter", { ...props.filters, q: query.value.trim(), offset: 0 });
}

function changeCategory(event: Event): void {
  if (event.target instanceof HTMLSelectElement) emit("filter", { ...props.filters, category: event.target.value, offset: 0 });
}

function clearFilters(): void {
  query.value = "";
  emit("filter", { ...props.filters, q: "", category: "", offset: 0 });
}

function changePage(direction: number): void {
  emit("filter", { ...props.filters, offset: Math.max(0, props.filters.offset + direction * props.filters.limit) });
}

function recipeHref(id: string): string {
  const params = new URLSearchParams();
  if (props.filters.q) params.set("q", props.filters.q);
  if (props.filters.category) params.set("category", props.filters.category);
  if (props.filters.offset) params.set("offset", String(props.filters.offset));
  params.set("recipe", id);
  return `?${params}`;
}

watch(() => JSON.stringify(props.filters), () => { query.value = props.filters.q; void loadRecipes(); }, { immediate: true });
onScopeDispose(() => { const previous = controller; controller = null; previous?.abort(); });
</script>

<style scoped>
.recipe-catalog { width: min(var(--container-max), calc(100% - 48px)); margin: 0 auto; padding: 28px 0 36px; }
.catalog-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 24px; margin-bottom: 18px; }
.catalog-heading h1 { margin: 0; font: 600 38px/1.5 var(--serif); }
.catalog-count { color: var(--clay); font-size: 13px; white-space: nowrap; padding-bottom: 5px; }
.catalog-search { display: grid; grid-template-columns: minmax(0, 1fr) 210px auto; gap: 18px; align-items: end; margin-bottom: 24px; padding: 20px 24px; border: 1px solid var(--line); background: var(--surface); border-radius: 8px; }
.catalog-search label { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.catalog-search label > span { font-size: 13px; color: var(--muted); }
.catalog-search input, .catalog-search select { width: 100%; min-width: 0; height: 46px; border: 1px solid var(--control-line); border-radius: 4px; color: var(--ink); background: var(--surface); padding: 0 12px; font-size: 14px; }
.catalog-search input::placeholder { color: var(--subtle); }
.catalog-submit { display: flex; gap: 16px; align-items: center; justify-content: center; min-height: 46px; padding: 0 24px; border: 1px solid var(--clay); border-radius: 4px; color: var(--surface); background: var(--clay); font-size: 14px; }
.catalog-submit:hover { background: var(--clay-hover); }
.catalog-results-heading { display: flex; align-items: baseline; gap: 16px; margin: -5px 0 16px; }
.catalog-results-heading h2 { margin: 0; font: 600 21px/1.6 var(--serif); }
.catalog-clear { margin-left: auto; min-height: 44px; border: 0; background: transparent; color: var(--clay); text-decoration: underline; font-size: 13px; }
.recipe-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 28px 24px; }
.recipe-card { display: block; min-width: 0; color: inherit; text-decoration: none; }
.catalog-cover { position: relative; height: 190px; overflow: hidden; border-radius: 6px; background: var(--panel); }
.catalog-cover img { display: block; width: 100%; height: 100%; object-fit: cover; transition: transform var(--duration) var(--ease); }
.recipe-card:hover .catalog-cover img { transform: scale(1.025); }
.is-text-cover { display: flex; flex-direction: column; justify-content: center; align-items: flex-start; gap: 9px; padding: 25px 28px; border: 1px solid var(--line); background: #f0e7db; }
.cover-category { font-size: 13px; color: var(--clay); }
.cover-name { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font: 600 25px/1.55 var(--serif); }
.cover-caption { font-size: 13px; color: var(--muted); }
.cover-image-label { position: absolute; bottom: 10px; left: 10px; padding: 2px 8px; border-radius: 3px; color: var(--ink); background: rgb(255 253 249 / 94%); font-size: 13px; }
.catalog-card-copy { padding: 13px 1px 0; }
.catalog-card-category { margin: 0 0 4px; font-size: 13px; color: var(--clay); }
.catalog-card-copy h3 { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin: 0; font: 600 21px/1.6 var(--serif); }
.catalog-card-copy h3 .ui-icon { width: 16px; height: 16px; color: var(--clay); transition: transform var(--duration) var(--ease); }
.recipe-card:hover h3 .ui-icon { transform: translateX(3px); }
.catalog-ingredients { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin: 6px 0 8px; color: var(--muted); font-size: 13px; }
.catalog-card-meta { display: flex; flex-wrap: wrap; gap: 5px 13px; font-size: 13px; color: var(--subtle); }
.catalog-status { display: flex; align-items: center; flex-direction: column; justify-content: center; min-height: 260px; gap: 12px; text-align: center; color: var(--muted); }
.catalog-status h2 { margin: 0; color: var(--ink); font: 600 24px/1.6 var(--serif); }
.catalog-status p { margin: 0; font-size: 14px; }
.catalog-status button, .catalog-pagination button { min-height: 44px; border: 1px solid var(--control-line); padding: 6px 18px; border-radius: 4px; color: var(--clay); background: var(--surface); font-size: 13px; }
.catalog-pagination { display: flex; align-items: center; justify-content: center; gap: 24px; margin-top: 38px; font-size: 13px; color: var(--muted); }
.catalog-pagination button:disabled { opacity: .4; }
.catalog-footer { margin-top: 36px; padding-top: 18px; border-top: 1px solid var(--line); color: var(--subtle); font-size: 13px; }
@media (max-width: 850px) { .recipe-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .catalog-search { grid-template-columns: minmax(0, 1fr) 170px auto; gap: 12px; padding: 16px; } .catalog-submit { padding-inline: 17px; } }
@media (max-width: 600px) { .recipe-catalog { width: calc(100% - 32px); padding-top: 20px; } .catalog-heading { margin-bottom: 16px; gap: 12px; } .catalog-heading h1 { font-size: 32px; } .catalog-search { grid-template-columns: minmax(0, 1fr) auto; padding: 16px; } .catalog-query { grid-column: 1 / -1; } .catalog-search input, .catalog-search select { font-size: 16px; } .catalog-results-heading { gap: 12px; } .recipe-grid { gap: 26px 16px; } .catalog-cover { height: 160px; } .is-text-cover { padding: 17px; gap: 7px; } .cover-name { font-size: 20px; } .catalog-card-copy h3 { font-size: 18px; } .catalog-ingredients { font-size: 13px; } .cover-caption { font-size: 13px; } }
@media (max-width: 380px) { .recipe-grid { grid-template-columns: minmax(0, 1fr); } .catalog-cover { height: 190px; } }
@media (prefers-reduced-motion: reduce) { .catalog-cover img, .catalog-card-copy h3 .ui-icon { transition: none; } }
</style>
