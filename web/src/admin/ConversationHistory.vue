<template>
  <section class="conversation-workspace" :class="{ 'is-reading': reading }" aria-label="对话记录工作区">
    <section class="conversation-directory" aria-labelledby="conversation-list-title" :aria-busy="listBusy">
      <header class="conversation-directory-heading">
        <div><h2 id="conversation-list-title">已保存会话</h2><span v-if="page">{{ page.total }} 段对话</span></div>
        <button class="admin-text-button" type="button" :disabled="listBusy || detailBusy" @click="refreshRecords">
          <UiIcon name="refresh" />刷新记录
        </button>
      </header>
      <form class="conversation-search" role="search" @submit.prevent="applySearch">
        <label for="conversation-search" class="sr-only">搜索对话</label>
        <div><UiIcon name="search" /><input id="conversation-search" v-model="searchDraft" type="search" maxlength="200" placeholder="标题、消息内容或用户标识" /></div>
        <button class="admin-secondary" type="submit">搜索</button>
      </form>
      <div class="conversation-filters">
        <label for="conversation-state">会话状态</label>
        <select id="conversation-state" v-model="filters.state" @change="applyState">
          <option value="all">全部会话</option><option value="active">正常会话</option><option value="deleted">已删除会话</option>
        </select>
        <button v-if="isFiltered" class="admin-text-button" type="button" @click="clearFilters">清除筛选</button>
      </div>
      <div v-if="listError" class="conversation-feedback">
        <p class="admin-error" role="alert">{{ listError }}</p><button class="admin-secondary" type="button" @click="loadConversations()">重试会话列表</button>
      </div>
      <p v-else-if="listBusy" class="conversation-feedback" role="status">正在读取对话记录…</p>
      <ul v-else-if="page?.items.length" class="conversation-list" aria-label="会话列表">
        <li v-for="session in page.items" :key="session.id">
          <button type="button" :aria-label="`查看对话：${session.title}`" :aria-current="selected?.id === session.id ? 'true' : undefined" @click="selectConversation(session)">
            <span class="conversation-item-heading"><strong>{{ session.title }}</strong><span v-if="!session.is_active" class="conversation-deleted">已删除</span></span>
            <span class="conversation-preview">{{ session.last_message_preview === null ? '暂无消息' : session.last_message_preview }}</span>
            <span class="conversation-item-meta"><span>{{ session.message_count }} 条消息 · {{ session.user_id === null ? '匿名会话' : session.user_id }}</span><time :datetime="session.updated_at ?? session.created_at">{{ formatAdminDate(session.updated_at ?? session.created_at) }}</time></span>
          </button>
        </li>
      </ul>
      <div v-else class="conversation-feedback conversation-empty">
        <UiIcon name="clock" /><h3>{{ isFiltered ? '没有符合条件的对话' : '还没有对话记录' }}</h3>
        <p>{{ isFiltered ? '调整搜索内容或会话状态后再试。' : '用户发送问题后，已保存的会话会出现在这里。' }}</p>
      </div>
      <nav v-if="page && page.total > page.limit" class="conversation-pagination" aria-label="会话分页">
        <button class="admin-text-button" type="button" aria-label="前一页会话" :disabled="listBusy || page.offset === 0" @click="changeListPage(-1)">上一页</button>
        <span>{{ page.offset + 1 }}–{{ Math.min(page.offset + page.limit, page.total) }} / {{ page.total }}</span>
        <button class="admin-text-button" type="button" aria-label="后一页会话" :disabled="listBusy || page.offset + page.limit >= page.total" @click="changeListPage(1)">下一页</button>
      </nav>
    </section>

    <section class="conversation-detail" aria-label="会话详情" :aria-busy="detailBusy">
      <button v-if="selected" class="admin-text-button conversation-back" type="button" @click="returnToList"><UiIcon name="back" />返回会话列表</button>
      <template v-if="selected">
        <header class="conversation-detail-heading">
          <div><h2 id="conversation-title" ref="detailHeading" tabindex="-1">{{ selected.title }}</h2><p>{{ selected.message_count }} 条消息<span v-if="!selected.is_active"> · 已删除会话</span></p></div>
          <details class="conversation-identity"><summary>会话信息</summary><dl><dt>会话 ID</dt><dd>{{ selected.id }}</dd><dt>用户标识</dt><dd>{{ selected.user_id === null ? '匿名会话' : selected.user_id }}</dd><dt>创建时间</dt><dd>{{ formatAdminDate(selected.created_at) }}</dd><dt>最后更新</dt><dd>{{ selected.updated_at === null ? '未记录' : formatAdminDate(selected.updated_at) }}</dd></dl></details>
        </header>
        <div v-if="detailError" class="conversation-feedback"><p class="admin-error" role="alert">{{ detailError }}</p><button class="admin-secondary" type="button" @click="loadMessages">重试消息读取</button></div>
        <p v-else-if="detailBusy" class="conversation-feedback" role="status">正在读取消息…</p>
        <ol v-else-if="messages?.items.length" ref="messageList" class="conversation-messages" aria-label="对话消息">
          <li v-for="message in messages.items" :key="message.id">
            <article class="conversation-message" :class="{ 'is-user': message.message_type === 'user_query' }">
              <header><strong>{{ roleLabel(message.message_type) }}</strong><time :datetime="message.created_at">{{ formatAdminDate(message.created_at) }}</time></header>
              <div class="conversation-message-content">{{ message.content }}</div>
              <details v-if="message.message_metadata && Object.keys(message.message_metadata).length" class="conversation-metadata"><summary>来源与执行信息</summary><pre>{{ JSON.stringify(message.message_metadata, null, 2) }}</pre></details>
            </article>
          </li>
        </ol>
        <div v-else class="conversation-feedback conversation-empty"><h3>此会话暂无消息</h3><p>会话已建立，还没有保存消息。</p></div>
        <nav v-if="messages && messages.total > messages.limit" class="conversation-pagination conversation-message-pagination" aria-label="消息分页">
          <button class="admin-text-button" type="button" :disabled="detailBusy || messages.offset === 0" @click="changeMessagePage(-1)">更早消息</button>
          <span>{{ messages.offset + 1 }}–{{ Math.min(messages.offset + messages.limit, messages.total) }} / {{ messages.total }}</span>
          <button class="admin-text-button" type="button" :disabled="detailBusy || messages.offset + messages.limit >= messages.total" @click="changeMessagePage(1)">更晚消息</button>
        </nav>
      </template>
      <div v-else class="conversation-feedback conversation-detail-empty"><UiIcon name="ask" /><h2>选择一段对话</h2><p>查看按时间保存的提问、回答与来源信息。</p></div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import UiIcon from "../components/UiIcon.vue";
import { errorMessage, formatAdminDate, isCancelled, listConversations, readConversationMessages } from "./api";
import type { ConversationFilters, ConversationMessagePage, ConversationPage, ConversationSummary } from "./contracts";

const filters = reactive<ConversationFilters>({ q: "", state: "all", offset: 0, limit: 12 });
const searchDraft = ref("");
const page = ref<ConversationPage | null>(null);
const selected = ref<ConversationSummary | null>(null);
const messages = ref<ConversationMessagePage | null>(null);
const listBusy = ref(true);
const detailBusy = ref(false);
const listError = ref("");
const detailError = ref("");
const reading = ref(false);
const detailHeading = ref<HTMLElement | null>(null);
const messageList = ref<HTMLOListElement | null>(null);
const isFiltered = computed(() => filters.q.length > 0 || filters.state !== "all");
let listController: AbortController | null = null;
let detailController: AbortController | null = null;
let messageOffset = 0;
let disposed = false;

function clearSelection(): void {
  detailController?.abort();
  detailController = null;
  selected.value = null;
  messages.value = null;
  detailError.value = "";
  detailBusy.value = false;
  reading.value = false;
  messageOffset = 0;
}

async function loadConversations(preserveSelection = false): Promise<void> {
  if (disposed) return;
  listController?.abort();
  const controller = new AbortController();
  listController = controller;
  listBusy.value = true;
  listError.value = "";
  page.value = null;
  if (!preserveSelection) clearSelection();
  try {
    const result = await listConversations({ ...filters }, controller.signal);
    if (listController !== controller) return;
    page.value = result;
    if (result.total > 0 && result.items.length === 0 && filters.offset > 0) {
      filters.offset = Math.floor((result.total - 1) / result.limit) * result.limit;
      await loadConversations(preserveSelection);
    }
  } catch (failure) {
    if (listController === controller && !isCancelled(failure)) listError.value = errorMessage(failure);
  } finally {
    if (listController === controller) {
      listBusy.value = false;
      listController = null;
    }
  }
}

async function loadMessages(): Promise<void> {
  if (disposed || !selected.value) return;
  const sessionId = selected.value.id;
  detailController?.abort();
  const controller = new AbortController();
  detailController = controller;
  detailBusy.value = true;
  detailError.value = "";
  messages.value = null;
  try {
    const result = await readConversationMessages(sessionId, messageOffset, controller.signal);
    if (detailController !== controller || selected.value?.id !== sessionId) return;
    selected.value = result.session;
    messages.value = result;
    if (result.total > 0 && result.items.length === 0 && messageOffset > 0) {
      messageOffset = Math.floor((result.total - 1) / result.limit) * result.limit;
      await loadMessages();
      return;
    }
    await nextTick();
    if (detailController === controller) messageList.value?.scrollTo(0, 0);
  } catch (failure) {
    if (detailController === controller && !isCancelled(failure)) detailError.value = errorMessage(failure);
  } finally {
    if (detailController === controller) {
      detailBusy.value = false;
      detailController = null;
    }
  }
}

function applySearch(): void {
  filters.q = searchDraft.value.trim();
  filters.offset = 0;
  void loadConversations();
}

function applyState(): void {
  filters.offset = 0;
  void loadConversations();
}

function clearFilters(): void {
  searchDraft.value = "";
  filters.q = "";
  filters.state = "all";
  filters.offset = 0;
  void loadConversations();
}

function changeListPage(direction: number): void {
  filters.offset = Math.max(0, filters.offset + direction * filters.limit);
  void loadConversations();
}

function selectConversation(session: ConversationSummary): void {
  selected.value = session;
  messageOffset = 0;
  reading.value = true;
  void loadMessages();
  void nextTick(() => detailHeading.value?.focus());
}

function changeMessagePage(direction: number): void {
  if (!messages.value) return;
  messageOffset = Math.max(0, messages.value.offset + direction * messages.value.limit);
  void loadMessages();
}

function returnToList(): void {
  reading.value = false;
  void nextTick(() => {
    document.querySelector<HTMLButtonElement>(".conversation-list [aria-current='true']")?.focus();
  });
}

async function refreshRecords(): Promise<void> {
  await loadConversations(true);
  if (!disposed && selected.value) await loadMessages();
}

function roleLabel(messageType: string): string {
  const labels: Record<string, string> = { user_query: "用户", agent_response: "助手", knowledge: "知识信息", error: "错误信息", system: "系统" };
  return labels[messageType] ?? messageType;
}

onMounted(() => { void loadConversations(); });
onBeforeUnmount(() => {
  disposed = true;
  listController?.abort();
  detailController?.abort();
  listController = null;
  detailController = null;
});
</script>

<style scoped lang="scss">
.conversation-workspace { display: grid; grid-template-columns: minmax(300px, 360px) minmax(0, 1fr); min-height: 560px; height: calc(100dvh - 148px); gap: 20px; }
.conversation-directory, .conversation-detail { min-width: 0; min-height: 0; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); }
.conversation-directory { display: flex; flex-direction: column; overflow: hidden; }
.conversation-directory-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 18px 10px; }
.conversation-directory-heading > div { display: flex; align-items: baseline; gap: 10px; }
.conversation-directory-heading h2 { margin: 0; font: 600 17px/1.5 var(--serif); }
.conversation-directory-heading span { color: var(--muted); font-size: 12px; white-space: nowrap; }
.conversation-directory-heading button { gap: 5px; font-size: 12px; white-space: nowrap; }
.conversation-search { display: flex; gap: 8px; padding: 0 18px; }
.conversation-search > div { display: flex; flex: 1; min-width: 0; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid var(--line); border-radius: 6px; }
.conversation-search .ui-icon { flex: none; width: 16px; color: var(--muted); }
.conversation-search input { width: 100%; min-width: 0; height: 40px; padding: 0; border: 0; outline-offset: 4px; background: transparent; color: var(--ink); font: inherit; font-size: 13px; }
.conversation-search button { padding-inline: 12px; }
.conversation-filters { display: flex; align-items: center; gap: 8px; padding: 10px 18px 12px; border-bottom: 1px solid var(--line); font-size: 12px; }
.conversation-filters label { flex: none; color: var(--muted); }
.conversation-filters select { min-width: 0; min-height: 36px; padding: 0 24px 0 8px; border: 1px solid var(--line); border-radius: 4px; background: var(--surface); color: var(--ink); font: inherit; }
.conversation-filters button { margin-left: auto; padding: 0; font-size: 12px; }
.conversation-list { flex: 1; min-height: 0; margin: 0; padding: 0; overflow: auto; list-style: none; }
.conversation-list li + li { border-top: 1px solid var(--line); }
.conversation-list button { display: flex; flex-direction: column; gap: 7px; width: 100%; min-height: 110px; padding: 15px 18px; border: 0; border-left: 2px solid transparent; background: transparent; color: var(--ink); text-align: left; cursor: pointer; }
.conversation-list button:hover { background: var(--paper); }
.conversation-list button[aria-current='true'] { border-left-color: var(--clay); background: var(--wash); }
.conversation-item-heading { display: flex; align-items: baseline; gap: 8px; width: 100%; }
.conversation-item-heading strong { display: -webkit-box; overflow: hidden; -webkit-line-clamp: 2; -webkit-box-orient: vertical; font-size: 14px; line-height: 1.55; font-weight: 600; overflow-wrap: anywhere; }
.conversation-deleted { flex: none; color: var(--muted); font-size: 11px; }
.conversation-preview { display: -webkit-box; overflow: hidden; -webkit-line-clamp: 2; -webkit-box-orient: vertical; color: var(--muted); font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
.conversation-item-meta { display: flex; justify-content: space-between; gap: 8px; width: 100%; color: var(--muted); font-size: 11px; }
.conversation-item-meta > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conversation-item-meta time { flex: none; font-variant-numeric: tabular-nums; }
.conversation-pagination { display: flex; flex: none; justify-content: space-between; align-items: center; gap: 8px; padding: 6px 18px; border-top: 1px solid var(--line); }
.conversation-pagination > span { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.conversation-pagination button { font-size: 13px; }
.conversation-detail { display: flex; flex-direction: column; overflow: hidden; }
.conversation-back { display: none; }
.conversation-detail-heading { flex: none; padding: 20px 26px 14px; border-bottom: 1px solid var(--line); }
.conversation-detail-heading h2 { margin: 0; font: 600 22px/1.5 var(--serif); overflow-wrap: anywhere; }
.conversation-detail-heading p { margin: 6px 0 0; color: var(--muted); font-size: 12px; }
.conversation-identity { margin-top: 8px; color: var(--muted); font-size: 12px; }
.conversation-identity summary { display: list-item; width: fit-content; padding-block: 6px; cursor: pointer; }
.conversation-identity dl { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 6px 12px; margin: 8px 0 0; }
.conversation-identity dt { color: var(--muted); }
.conversation-identity dd { margin: 0; color: var(--ink); overflow-wrap: anywhere; }
.conversation-messages { flex: 1; min-height: 0; margin: 0; padding: 0 26px; overflow: auto; list-style: none; }
.conversation-message { padding: 22px 0; }
.conversation-messages li + li { border-top: 1px solid var(--line); }
.conversation-message > header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 10px; }
.conversation-message > header strong { color: var(--ink); font-size: 13px; font-weight: 600; }
.conversation-message.is-user > header strong { color: var(--clay); }
.conversation-message time { color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.conversation-message-content { color: var(--ink); font-size: 16px; line-height: 1.85; white-space: pre-wrap; overflow-wrap: anywhere; }
.conversation-metadata { margin-top: 12px; color: var(--muted); font-size: 12px; }
.conversation-metadata summary { width: fit-content; min-height: 32px; padding-block: 8px; cursor: pointer; }
.conversation-metadata pre { max-height: 280px; margin: 6px 0 0; padding: 12px; overflow: auto; border-radius: 4px; background: var(--paper); color: var(--ink); font-size: 12px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.conversation-feedback { margin: 0; padding: 24px 18px; color: var(--muted); font-size: 14px; line-height: 1.7; }
.conversation-feedback .admin-error { margin: 0 0 14px; }
.conversation-empty h3 { margin: 10px 0 6px; color: var(--ink); font-size: 16px; }
.conversation-empty p { margin: 0; }
.conversation-empty > .ui-icon { width: 24px; height: 24px; color: var(--clay); }
.conversation-detail-empty { display: flex; flex: 1; flex-direction: column; align-items: center; justify-content: center; gap: 10px; text-align: center; }
.conversation-detail-empty > .ui-icon { width: 30px; height: 30px; color: var(--clay); }
.conversation-detail-empty h2 { margin: 0; color: var(--ink); font: 600 22px/1.5 var(--serif); }
.conversation-detail-empty p { margin: 0; }
@media (max-width: 1100px) { .conversation-workspace { grid-template-columns: minmax(280px, 320px) minmax(0, 1fr); gap: 16px; } .conversation-detail-heading, .conversation-messages { padding-inline: 20px; } }
@media (max-width: 700px) {
  .conversation-workspace { display: block; min-height: 0; height: auto; }
  .conversation-directory { min-height: calc(100dvh - 170px); }
  .conversation-workspace.is-reading .conversation-directory { display: none; }
  .conversation-detail { display: none; min-height: calc(100dvh - 170px); }
  .conversation-workspace.is-reading .conversation-detail { display: flex; }
  .conversation-back { display: inline-flex; align-self: flex-start; gap: 6px; margin: 4px 16px 0; }
  .conversation-directory-heading { padding-top: 12px; }
  .conversation-search input, .conversation-filters select { min-height: 44px; }
  .conversation-filters { gap: 10px; }
  .conversation-filters button { min-height: 44px; }
  .conversation-list { flex: none; overflow: visible; }
  .conversation-list button { min-height: 112px; }
  .conversation-detail-heading { padding: 10px 18px 14px; }
  .conversation-detail-heading h2 { font-size: 20px; }
  .conversation-identity summary, .conversation-metadata summary { min-height: 44px; padding-block: 12px; }
  .conversation-messages { flex: none; padding-inline: 18px; overflow: visible; }
  .conversation-message { padding-block: 18px; }
  .conversation-message-pagination { margin-top: auto; }
}
</style>
