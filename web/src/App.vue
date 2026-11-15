<template>
  <div class="app-shell" :data-mode="mode">
    <a class="skip-link" :href="`#${currentPage.titleId}`">跳到主要内容</a>
    <header class="product-header">
      <a class="identity" href="?" aria-label="陶陶，餐桌手记" @click="handlePageLink">
        <span class="brand-stamp">陶</span><span><span class="brand-name">陶陶</span><span class="brand-sub">GustoBot · Kitchen notes</span></span>
      </a>
      <nav class="product-nav" aria-label="主导航">
        <a v-for="page in pages" :key="page.id" :href="page.href" :aria-current="mode === page.id ? 'page' : undefined" @click="handlePageLink">{{ page.label }}</a>
      </nav>
      <div class="header-right">
        <button v-if="mode === 'workspace'" type="button" class="return-link" @click="returnToRecipe"><UiIcon name="back" />回到食谱</button>
        <span class="avatar" aria-label="我的厨房">我</span>
      </div>
    </header>
    <LandingPage v-if="mode === 'reading'" v-model:checked-ids="checkedIds" @ask="askQuestion" />
    <TechnologyPage v-else-if="mode === 'technology'" @navigate="handlePageLink" />
    <AboutPage v-else-if="mode === 'about'" @navigate="handlePageLink" />
    <div v-show="mode === 'reading' || mode === 'workspace'" class="workspace-layout" :class="{ 'is-reading': mode === 'reading' }" :role="mode === 'workspace' ? 'main' : undefined">
      <section class="workspace-conversation" :aria-labelledby="mode === 'workspace' ? 'conversation-title' : undefined">
        <header v-if="mode === 'workspace'" class="conversation-heading">
          <div><p class="eyebrow">餐桌对话<span class="mobile-recipe-name"> · {{ recipe.title }}</span></p><h1 id="conversation-title" tabindex="-1">把火候，聊明白。</h1></div>
          <span class="conversation-topic">{{ recipe.title }}<br />接着这道菜聊</span>
        </header>
        <ChatWidget
          v-show="mode === 'workspace' || isChatOpen"
          ref="chatWidget"
          :variant="mode === 'workspace' ? 'workspace' : 'widget'"
          :state="state"
          @close="closeChat"
          @expand="openWorkspace"
          @update-draft="updateDraft"
          @submit="sendMessage"
          @ask="askQuestion"
          @upload="onFileSelected"
          @remove-attachment="removeAttachment"
          @reset="resetSession"
        />
      </section>
      <aside v-if="mode === 'workspace'" class="workspace-aside" aria-label="当前食谱"><RecipeNote v-model:checked-ids="checkedIds" @return="returnToRecipe" /></aside>
    </div>
    <div v-if="mode === 'reading' && !isChatOpen" class="launcher-wrap">
      <div v-if="!hintDismissed" class="launcher-hint">
        <span>{{ hasDraft ? '问题还在，接着聊' : '做饭拿不准，问问陶陶' }}</span>
        <button type="button" class="hint-dismiss" aria-label="隐藏机器人提示" title="隐藏提示" @click="dismissHint"><UiIcon name="close" /></button>
      </div>
      <button ref="launcher" type="button" class="robot-launcher" :data-has-draft="hasDraft" :aria-label="hasDraft ? '继续编辑未发送的问题' : '打开陶陶对话'" :title="hasDraft ? '继续编辑问题' : '问问陶陶'" aria-controls="chat-panel" :aria-expanded="isChatOpen" @click="openChat"><UiIcon name="bot" /></button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import AboutPage from "./components/AboutPage.vue";
import ChatWidget from "./components/ChatWidget.vue";
import LandingPage from "./components/LandingPage.vue";
import RecipeNote from "./components/RecipeNote.vue";
import TechnologyPage from "./components/TechnologyPage.vue";
import UiIcon from "./components/UiIcon.vue";
import { useChat } from "./composables/useChat";
import { recipe, recipeContext } from "./data/recipe";

const { state, sendMessage, addQuestion, resetSession, onFileSelected, removeAttachment } = useChat(recipeContext);
const pages = [
  { id: "reading", label: "餐桌手记", href: "?", titleId: "recipe-title" },
  { id: "workspace", label: "餐桌对话", href: "?page=workspace", titleId: "conversation-title" },
  { id: "technology", label: "技术路线", href: "?page=technology", titleId: "technology-title" },
  { id: "about", label: "关于", href: "?page=about", titleId: "about-title" }
] as const;
type Page = typeof pages[number]["id"];
const mode = ref<Page>(readPage(window.location.search));
const currentPage = computed(() => pages.find((page) => page.id === mode.value) ?? pages[0]);
const isChatOpen = ref(window.matchMedia("(min-width: 768px)").matches);
const checkedIds = ref<string[]>([]);
const hintDismissed = ref(false);
const hasDraft = computed(() => Boolean(state.userInput.trim() || state.attachedFileName));
const chatWidget = ref<InstanceType<typeof ChatWidget> | null>(null);
const launcher = ref<HTMLButtonElement | null>(null);
const pageScroll = new Map<Page, number>();
const previousScrollRestoration = window.history.scrollRestoration;

function readPage(search: string): Page {
  const requestedPage = new URLSearchParams(search).get("page");
  return pages.find((page) => page.id === requestedPage)?.id ?? "reading";
}

async function navigate(nextPage: Page, recordHistory = true): Promise<void> {
  const changed = mode.value !== nextPage;
  if (changed) {
    pageScroll.set(mode.value, window.scrollY);
    if (recordHistory) {
      const url = new URL(window.location.href);
      url.hash = "";
      if (nextPage === "reading") {
        url.searchParams.delete("page");
      } else {
        url.searchParams.set("page", nextPage);
      }
      window.history.pushState(null, "", url);
    }
    mode.value = nextPage;
  }
  await nextTick();
  window.scrollTo(0, changed ? pageScroll.get(nextPage) ?? 0 : 0);
  document.getElementById(currentPage.value.titleId)?.focus({ preventScroll: true });
}

function handlePageLink(event: MouseEvent): void {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    return;
  }
  const link = event.currentTarget;
  if (!(link instanceof HTMLAnchorElement)) {
    return;
  }
  event.preventDefault();
  const nextPage = readPage(new URL(link.href).search);
  if (nextPage === "workspace") {
    void openWorkspace();
  } else {
    void navigate(nextPage);
  }
}

function handlePopState(): void {
  void navigate(readPage(window.location.search), false);
}

watch(currentPage, (page) => {
  document.title = `陶陶 · ${page.label} — GustoBot`;
}, { immediate: true });

async function openChat(): Promise<void> {
  isChatOpen.value = true;
  await nextTick();
  await chatWidget.value?.focusInput();
}

async function closeChat(): Promise<void> {
  isChatOpen.value = false;
  await nextTick();
  launcher.value?.focus({ preventScroll: true });
}

async function openWorkspace(): Promise<void> {
  await navigate("workspace");
  await chatWidget.value?.focusInput();
}

async function returnToRecipe(): Promise<void> {
  await navigate("reading");
}

async function askQuestion(question: string): Promise<void> {
  addQuestion(question);
  if (mode.value === "reading") {
    await openChat();
  } else {
    await chatWidget.value?.focusInput();
  }
}

function updateDraft(value: string): void {
  state.userInput = value;
  state.error = "";
}

async function dismissHint(): Promise<void> {
  hintDismissed.value = true;
  await nextTick();
  launcher.value?.focus({ preventScroll: true });
}

function handleEscape(event: KeyboardEvent): void {
  if (event.key !== "Escape" || event.isComposing || event.defaultPrevented) {
    return;
  }
  if (mode.value === "reading" && isChatOpen.value) {
    event.preventDefault();
    void closeChat();
  }
}

onMounted(() => {
  window.history.scrollRestoration = "manual";
  window.addEventListener("keydown", handleEscape);
  window.addEventListener("popstate", handlePopState);
});
onBeforeUnmount(() => {
  window.history.scrollRestoration = previousScrollRestoration;
  window.removeEventListener("keydown", handleEscape);
  window.removeEventListener("popstate", handlePopState);
});
</script>
