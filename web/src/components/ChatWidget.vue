<template>
  <section id="chat-panel" class="chat-panel widget-panel" aria-label="陶陶对话">
    <header class="widget-header">
      <img class="bot-seal" src="/taotao-mark.png" width="34" height="34" alt="" />
      <div><h2 class="widget-name">陶陶</h2><p class="widget-subtitle">{{ recipe ? '陪你把这一餐做好' : '菜谱助手' }}</p></div>
      <div class="widget-actions">
        <button type="button" class="minimize-button" aria-label="收起对话，保留草稿" title="收起对话 · Esc" @click="emit('close')"><UiIcon name="down" />收起</button>
      </div>
    </header>
    <div v-if="recipe" class="recipe-context-bar" role="group" aria-label="当前食谱">
      <img v-if="recipe.cover_image" :src="recipe.cover_image.url" alt="" /><strong>{{ recipe.name }}</strong><span>{{ servings !== null ? `${servings} 人份` : '按原文做法' }}</span>
    </div>
    <div
      ref="history"
      class="conversation-history widget-history"
      :data-more="hasMore"
      tabindex="0"
      role="log"
      aria-label="对话消息"
      aria-live="polite"
      aria-relevant="additions"
      @scroll.passive="syncHistoryCue"
    >
      <div v-if="state.messages.length === 0" class="welcome-message">
        <p class="assistant-label"><img src="/taotao-mark.png" width="16" height="16" alt="" />陶陶</p>
        <h2 class="welcome-title">{{ recipe ? '这份做法，一起慢慢看。' : '今天想聊点什么？' }}</h2>
        <p class="answer-copy">{{ recipe ? '可以问当前做法，也可以了解相关背景。回答会结合已关联的图谱和文章，并区分不同来源。' : '可以直接提问，也可以选一道菜，结合具体做法、图谱和相关文章一起聊。' }}</p>
      </div>
      <template v-for="message in state.messages" :key="message.id">
        <p v-if="message.role === 'user'" class="message-user"><span v-if="message.attachmentName" class="message-attachment"><UiIcon name="attachment" />{{ message.attachmentName }}</span>{{ message.content }}<span v-if="message.delivery === 'failed'" class="message-delivery">发送未成功</span></p>
        <article v-else class="assistant-message" :data-message-id="message.id">
          <p class="assistant-label"><img src="/taotao-mark.png" width="16" height="16" alt="" />陶陶</p>
          <div class="answer-copy"><template v-for="(part, index) in linkify(message.content)" :key="index"><a v-if="part.href" :href="part.href" target="_blank" rel="noopener noreferrer">{{ part.text }}</a><template v-else>{{ part.text }}</template></template></div>
          <div v-if="message.clarificationOptions?.length" class="clarification-options" aria-label="选择具体做法">
            <button v-for="option in message.clarificationOptions" :key="option.question" type="button" :disabled="state.isTyping || state.isUploading || message.id !== state.messages[state.messages.length - 1]?.id" @click="emit('ask', option.question)">{{ option.label }}</button>
          </div>
          <details v-if="message.sources?.length" class="message-sources" @toggle="syncHistoryCue">
            <summary>参考来源 · {{ message.sources.length }}</summary>
            <ul>
              <li v-for="(source, index) in message.sources" :key="index">
                <a v-if="getSourceUrl(source)" :href="getSourceUrl(source) ?? undefined" target="_blank" rel="noopener noreferrer">{{ formatSource(source) }}</a>
                <span v-else>{{ formatSource(source) }}</span>
              </li>
            </ul>
          </details>
        </article>
      </template>
      <article v-if="state.replyDraft" class="assistant-message" aria-live="off">
        <p class="assistant-label"><img src="/taotao-mark.png" width="16" height="16" alt="" />陶陶</p>
        <div class="answer-copy">{{ state.replyDraft }}</div>
      </article>
      <p v-if="state.replyProgress" class="typing-status" role="status"><span class="spinner" aria-hidden="true"></span>{{ state.replyProgress }}</p>
    </div>
    <ChatComposer
      ref="composer"
      :draft="state.userInput"
      :busy="state.isTyping || state.isUploading"
      :file-name="state.attachedFileName"
      :upload-status="state.uploadStatus"
      :error="state.error"
      :has-conversation="state.messages.length > 0 || state.sessionId.length > 0"
      :followups="followups"
      :allow-upload="recipe === null"
      @update-draft="emit('update-draft', $event)"
      @submit="emit('submit')"
      @ask="emit('ask', $event)"
      @upload="emit('upload', $event)"
      @remove-attachment="emit('remove-attachment')"
      @reset="emit('reset')"
      @resize="syncHistoryCue"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { RecipeDetail } from "../data/recipe";
import { availablePrompts, formatSource, getSourceUrl, linkify, type ChatState } from "../lib/chat";
import ChatComposer from "./ChatComposer.vue";
import UiIcon from "./UiIcon.vue";

const props = defineProps<{ state: Readonly<ChatState>; recipe: RecipeDetail | null; servings: number | null }>();
const followups = computed(() => availablePrompts(props.recipe ? ["这道菜有哪些食材？", "这份做法有哪些关键步骤？"] : [], props.state.messages));
const emit = defineEmits<{
  (event: "close"): void;
  (event: "update-draft", value: string): void;
  (event: "submit"): void;
  (event: "ask", question: string): void;
  (event: "upload", eventObject: Event): void;
  (event: "remove-attachment"): void;
  (event: "reset"): void;
}>();
const history = ref<HTMLElement | null>(null);
const composer = ref<InstanceType<typeof ChatComposer> | null>(null);
const hasMore = ref(false);
let resizeObserver: ResizeObserver | undefined;

function syncHistoryCue(): void {
  const element = history.value;
  hasMore.value = Boolean(element && element.clientHeight > 0 && element.scrollHeight - element.clientHeight - element.scrollTop > 2);
}

async function focusInput(): Promise<void> {
  await composer.value?.focusInput();
  syncHistoryCue();
}

watch(() => [props.state.messages.length, props.state.isTyping], async () => {
  await nextTick();
  const element = history.value;
  if (element) {
    const latestMessage = props.state.messages[props.state.messages.length - 1];
    const reply = latestMessage?.role === "assistant" && !props.state.isTyping
      ? element.querySelector<HTMLElement>(`[data-message-id="${latestMessage.id}"]`)
      : null;
    element.scrollTop = reply
      ? element.scrollTop + reply.getBoundingClientRect().top - element.getBoundingClientRect().top - 14
      : element.scrollHeight;
  }
  syncHistoryCue();
});
watch(() => [props.state.error, props.state.uploadStatus], () => nextTick(syncHistoryCue));
watch(() => [props.state.replyDraft, props.state.replyProgress], async () => {
  const element = history.value;
  if (!element || !props.state.isTyping) return;
  const atBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 32;
  await nextTick();
  if (atBottom) element.scrollTop = element.scrollHeight;
  syncHistoryCue();
});
onMounted(() => {
  resizeObserver = new ResizeObserver(syncHistoryCue);
  if (history.value) {
    resizeObserver.observe(history.value);
  }
});
onBeforeUnmount(() => resizeObserver?.disconnect());
defineExpose({ focusInput });
</script>
