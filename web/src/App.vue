<template>
  <div class="app-shell" :data-mode="mode">
    <a class="skip-link" :href="`#${titleId}`">跳到主要内容</a>
    <header class="product-header">
      <a class="identity" :href="catalogHref" aria-label="陶陶，餐桌手记" @click="handlePageLink">
        <img class="brand-stamp" src="/taotao-mark.png" width="38" height="41" alt="" />
        <span><span class="brand-name">陶陶</span><span class="brand-sub">GustoBot · Kitchen notes</span></span>
      </a>
      <a class="admin-link" href="/admin.html">后台管理<UiIcon name="arrow" /></a>
    </header>
    <RecipeCatalog v-show="mode === 'catalog'" :filters="route.filters" @filter="updateFilters" @navigate="handlePageLink" />
    <main v-if="mode === 'reading' && (detailLoading || detailError)" class="recipe-detail-status" aria-labelledby="detail-status-title">
      <a :href="catalogHref" @click="handlePageLink">返回菜谱目录</a>
      <h1 id="detail-status-title" tabindex="-1">{{ detailLoading ? '正在翻开这份菜谱…' : '暂时无法读取菜谱' }}</h1>
      <p v-if="detailError" role="status">{{ detailError }}</p>
      <button v-if="!detailLoading" type="button" @click="loadSelectedRecipe">重试读取菜谱</button>
    </main>
    <LandingPage v-if="mode === 'reading' && recipe && !detailLoading && !detailError" :key="recipe.id + recipe.version" v-model:checked-ids="checkedIds" v-model:servings="servings" v-model:active-step="activeStep" :recipe="recipe" :catalog-href="catalogHref" @navigate="handlePageLink" @ask="askQuestion" />
    <ChatWidget
      v-show="isChatOpen && !detailLoading && !detailError"
      ref="chatWidget"
      :state="state"
      :recipe="recipe"
      :servings="servings"
      @close="closeChat"
      @update-draft="updateDraft"
      @submit="sendMessage"
      @ask="askQuestion"
      @upload="onFileSelected"
      @remove-attachment="removeAttachment"
      @reset="resetSession"
    />
    <div v-if="!isChatOpen && !detailLoading && !detailError" class="launcher-wrap">
      <div v-if="!hintDismissed" class="launcher-hint">
        <span>{{ hasDraft ? '问题还在，接着聊' : '做饭拿不准，问问陶陶' }}</span>
        <button type="button" class="hint-dismiss" aria-label="隐藏陶陶提示" title="隐藏提示" @click="dismissHint"><UiIcon name="close" /></button>
      </div>
      <button ref="launcher" type="button" class="robot-launcher" :data-has-draft="hasDraft" :aria-label="hasDraft ? '继续编辑未发送的问题' : '打开陶陶对话'" :title="hasDraft ? '继续编辑问题' : '问问陶陶'" aria-controls="chat-panel" :aria-expanded="isChatOpen" @click="openChat">
        <img src="/taotao-mark.png" width="32" height="32" alt="" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import ChatWidget from "./components/ChatWidget.vue";
import LandingPage from "./components/LandingPage.vue";
import RecipeCatalog from "./components/RecipeCatalog.vue";
import UiIcon from "./components/UiIcon.vue";
import { useChat } from "./composables/useChat";
import type { RecipeDetail, RecipeFilters } from "./data/recipe";
import { readRecipe } from "./lib/recipes";

type Page = "catalog" | "reading";
interface PublicRoute { page: Page; recipeId: string | null; filters: RecipeFilters }
interface RecipePreferences { draft: string; servings: number | null; checkedIds: string[]; activeStep: string }

const route = ref<PublicRoute>(readRoute(window.location.search));
const mode = computed(() => route.value.page);
const recipe = ref<RecipeDetail | null>(null);
const servings = ref<number | null>(null);
const checkedIds = ref<string[]>([]);
const activeStep = ref("");
const detailLoading = ref(false);
const detailError = ref("");
const isChatOpen = ref(new URLSearchParams(window.location.search).get("page") === "workspace" && route.value.recipeId !== null);
const hintDismissed = ref(false);
const chatWidget = ref<InstanceType<typeof ChatWidget> | null>(null);
const launcher = ref<HTMLButtonElement | null>(null);
const preferences = new Map<string, RecipePreferences>();
const pageScroll = new Map<string, number>();
const previousScrollRestoration = window.history.scrollRestoration;
let detailController: AbortController | null = null;
let activeRecipeKey = "";
const { state, sendMessage, addQuestion, resetSession, onFileSelected, removeAttachment } = useChat(() => recipe.value
  ? { id: recipe.value.id, version: recipe.value.version, ...(servings.value !== null ? { servings: servings.value } : {}) }
  : null);
const hasDraft = computed(() => Boolean(state.userInput.trim() || state.attachedFileName));
const titleId = computed(() => mode.value === "catalog" ? "catalog-title" : detailLoading.value || detailError.value ? "detail-status-title" : "recipe-title");
const catalogHref = computed(() => routeHref("catalog"));

function readRoute(search: string): PublicRoute {
  const params = new URLSearchParams(search);
  const recipeId = params.get("recipe") || null;
  const offset = Number(params.get("offset") ?? 0);
  return {
    page: recipeId ? "reading" : "catalog",
    recipeId,
    filters: { q: (params.get("q") ?? "").slice(0, 200), category: params.get("category") ?? "", offset: Number.isInteger(offset) && offset >= 0 ? offset : 0, limit: 12 }
  };
}

function routeHref(page: Page, recipeId: string | null = null, filters = route.value.filters): string {
  const params = new URLSearchParams();
  if (recipeId && page === "reading") params.set("recipe", recipeId);
  if (filters.q) params.set("q", filters.q);
  if (filters.category) params.set("category", filters.category);
  if (filters.offset) params.set("offset", String(filters.offset));
  return `?${params}`;
}

function savePreferences(): void {
  preferences.set(activeRecipeKey, { draft: state.userInput, servings: servings.value, checkedIds: [...checkedIds.value], activeStep: activeStep.value });
}

function clearSelectedRecipe(): void {
  savePreferences();
  resetSession();
  recipe.value = null;
  activeRecipeKey = "";
  servings.value = null;
  checkedIds.value = [];
  activeStep.value = "";
  state.userInput = preferences.get("")?.draft ?? "";
}

async function loadSelectedRecipe(): Promise<void> {
  const id = route.value.recipeId;
  detailController?.abort();
  if (!id) return;
  if (recipe.value?.id !== id) clearSelectedRecipe();
  const controller = new AbortController();
  detailController = controller;
  detailLoading.value = true;
  detailError.value = "";
  try {
    const result = await readRecipe(id, controller.signal);
    if (detailController !== controller || route.value.recipeId !== id) return;
    const key = `${result.id}:${result.version}`;
    if (activeRecipeKey !== key) {
      savePreferences();
      resetSession();
      const saved = preferences.get(key);
      servings.value = saved?.servings ?? result.servings_count;
      checkedIds.value = saved?.checkedIds ?? [];
      activeStep.value = saved?.activeStep ?? "";
      state.userInput = saved?.draft ?? "";
      activeRecipeKey = key;
    }
    recipe.value = result;
  } catch {
    if (detailController === controller) detailError.value = "这份菜谱可能已移除，或服务暂时不可用。请重试，或返回目录选菜。";
  } finally {
    if (detailController === controller) {
      detailLoading.value = false;
      await nextTick();
      if (detailController !== controller || route.value.recipeId !== id) return;
      window.scrollTo(0, pageScroll.get(routeHref(route.value.page, id)) ?? 0);
      if (isChatOpen.value) await chatWidget.value?.focusInput();
      else document.getElementById(titleId.value)?.focus({ preventScroll: true });
    }
  }
}

async function navigate(href: string, recordHistory = true): Promise<void> {
  const url = new URL(href, window.location.href);
  const nextRoute = readRoute(url.search);
  const currentKey = routeHref(route.value.page, route.value.recipeId);
  const nextKey = routeHref(nextRoute.page, nextRoute.recipeId, nextRoute.filters);
  pageScroll.set(currentKey, window.scrollY);
  if (recordHistory && currentKey !== nextKey) window.history.pushState(null, "", nextKey);
  route.value = nextRoute;
  isChatOpen.value = url.searchParams.get("page") === "workspace" && nextRoute.recipeId !== null;
  await nextTick();
  if (routeHref(route.value.page, route.value.recipeId) !== nextKey || detailLoading.value) return;
  window.scrollTo(0, pageScroll.get(nextKey) ?? 0);
  document.getElementById(titleId.value)?.focus({ preventScroll: true });
}

function handlePageLink(event: MouseEvent): void {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const link = event.currentTarget;
  if (!(link instanceof HTMLAnchorElement)) return;
  event.preventDefault();
  void navigate(link.href);
}

function updateFilters(filters: RecipeFilters): void { void navigate(routeHref("catalog", null, filters)); }
function handlePopState(): void { void navigate(window.location.href, false); }

watch(() => route.value.recipeId, () => {
  if (route.value.recipeId) void loadSelectedRecipe();
  else {
    const previous = detailController;
    detailController = null;
    previous?.abort();
    detailLoading.value = false;
    detailError.value = "";
    if (recipe.value) clearSelectedRecipe();
  }
}, { immediate: true });
watch([mode, () => recipe.value?.name], () => { document.title = `陶陶 · ${mode.value === "reading" ? recipe.value?.name ?? "菜谱" : "菜谱"} — GustoBot`; }, { immediate: true });

async function openChat(): Promise<void> { isChatOpen.value = true; await nextTick(); await chatWidget.value?.focusInput(); }
async function closeChat(): Promise<void> { isChatOpen.value = false; await nextTick(); launcher.value?.focus({ preventScroll: true }); }
async function askQuestion(question: string): Promise<void> { addQuestion(question); await openChat(); }
function updateDraft(value: string): void { state.userInput = value; state.error = ""; }
async function dismissHint(): Promise<void> { hintDismissed.value = true; await nextTick(); launcher.value?.focus({ preventScroll: true }); }
function handleEscape(event: KeyboardEvent): void {
  if (event.key === "Escape" && !event.isComposing && !event.defaultPrevented && isChatOpen.value) { event.preventDefault(); void closeChat(); }
}

onMounted(() => {
  window.history.scrollRestoration = "manual";
  if (new URLSearchParams(window.location.search).has("page")) window.history.replaceState(null, "", routeHref(route.value.page, route.value.recipeId));
  window.addEventListener("keydown", handleEscape);
  window.addEventListener("popstate", handlePopState);
});
onBeforeUnmount(() => { const previous = detailController; detailController = null; previous?.abort(); window.history.scrollRestoration = previousScrollRestoration; window.removeEventListener("keydown", handleEscape); window.removeEventListener("popstate", handlePopState); });
</script>

<style scoped>
.admin-link { display: inline-flex; justify-self: end; align-items: center; gap: 8px; min-height: 44px; padding: 0 12px; border: 1px solid var(--line); border-radius: 6px; color: var(--muted); font-size: 13px; text-decoration: none; }
.admin-link:hover { color: var(--clay); background: var(--surface); }
.admin-link .ui-icon { width: 14px; height: 14px; }
.app-shell :deep(h1[tabindex="-1"]:focus-visible) { outline: none; }
.recipe-detail-status { width: min(var(--container-max), calc(100% - 48px)); margin: 32px auto; min-height: 360px; }
.recipe-detail-status a { display: inline-flex; align-items: center; min-height: 44px; color: var(--clay); font-size: 13px; }
.recipe-detail-status h1 { margin-top: 30px; font: 600 28px/1.6 var(--serif); }
.recipe-detail-status p { color: var(--muted); font-size: 14px; }
.recipe-detail-status button { min-height: 44px; margin-top: 12px; border: 1px solid var(--control-line); border-radius: 4px; padding: 8px 18px; color: var(--clay); background: var(--surface); }
</style>
