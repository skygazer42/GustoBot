<template>
  <section id="chat-panel" class="chat-panel" :class="variant === 'widget' ? 'widget-panel' : 'workspace-panel'" aria-label="陶陶对话">
    <header v-if="variant === 'widget'" class="widget-header">
      <span class="bot-seal"><UiIcon name="bot" /></span>
      <div><h2 class="widget-name">陶陶</h2><p class="widget-subtitle">陪你把这一餐做好</p></div>
      <div class="widget-actions">
        <button type="button" class="minimize-button" aria-label="展开到完整工作台" title="展开到完整工作台" @click="emit('expand')"><UiIcon name="expand" />展开</button>
        <button type="button" class="minimize-button" aria-label="收起对话，保留草稿" title="收起对话 · Esc" @click="emit('close')"><UiIcon name="down" />收起</button>
      </div>
    </header>
    <div
      ref="history"
      class="conversation-history"
      :class="variant === 'widget' ? 'widget-history' : 'workspace-history'"
      :data-more="hasMore"
      tabindex="0"
      role="log"
      aria-label="对话消息"
      aria-live="polite"
      aria-relevant="additions"
      @scroll.passive="syncHistoryCue"
    >
      <div v-if="state.messages.length === 0" class="welcome-message">
        <p class="assistant-label"><UiIcon name="bot" />陶陶</p>
        <h2 class="welcome-title">今天这道菜，一起慢慢做。</h2>
        <p class="answer-copy">火候拿不准，食材想换一换，<br />都可以和我聊聊。</p>
      </div>
      <template v-for="message in state.messages" :key="message.id">
        <p v-if="message.role === 'user'" class="message-user"><span v-if="message.attachmentName" class="message-attachment"><UiIcon name="attachment" />{{ message.attachmentName }}</span>{{ message.content }}<span v-if="message.delivery === 'failed'" class="message-delivery">发送未成功</span></p>
        <article v-else class="assistant-message" :data-message-id="message.id">
          <p class="assistant-label"><UiIcon name="bot" />陶陶</p>
          <div class="answer-copy"><template v-for="(part, index) in linkify(message.content)" :key="index"><a v-if="part.href" :href="part.href" target="_blank" rel="noopener noreferrer">{{ part.text }}</a><template v-else>{{ part.text }}</template></template></div>
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
      <p v-if="state.isTyping" class="typing-status" role="status"><span class="spinner" aria-hidden="true"></span>陶陶正在想一想…</p>
      <div v-if="variant === 'widget'" class="active-recipe" role="group" :aria-label="`当前浏览中的食谱：${recipe.title}`">
        <img :src="recipe.photo" alt="" />
        <div><h3>{{ recipe.title }}</h3><span class="active-badge"><UiIcon name="check" />当前浏览中</span><p class="active-recipe-meta">{{ recipe.minutes }} 分钟 · {{ recipe.servings }} 人份</p></div>
      </div>
    </div>
    <ChatComposer
      ref="composer"
      :variant="variant"
      :draft="state.userInput"
      :busy="state.isTyping || state.isUploading"
      :file-name="state.attachedFileName"
      :upload-status="state.uploadStatus"
      :error="state.error"
      :has-conversation="state.messages.length > 0 || state.sessionId.length > 0"
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
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { recipe } from "../data/recipe";
import { formatSource, getSourceUrl, linkify } from "../lib/chat";
import type { ChatState } from "../lib/chat";
import ChatComposer from "./ChatComposer.vue";
import UiIcon from "./UiIcon.vue";

const props = defineProps<{ variant: "widget" | "workspace"; state: Readonly<ChatState> }>();
const emit = defineEmits<{
  (event: "close"): void;
  (event: "expand"): void;
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
watch(() => [props.state.error, props.state.uploadStatus, props.variant], () => nextTick(syncHistoryCue));
onMounted(() => {
  resizeObserver = new ResizeObserver(syncHistoryCue);
  if (history.value) {
    resizeObserver.observe(history.value);
  }
});
onBeforeUnmount(() => resizeObserver?.disconnect());
defineExpose({ focusInput });
</script>
