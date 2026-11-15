<template>
  <form class="composer" :class="variant === 'widget' ? 'widget-form' : 'workspace-form'" @submit.prevent="emit('submit')">
    <div class="followups" aria-label="接着问问">
      <button v-for="question in followups" :key="question" type="button" @click="emit('ask', question)">{{ question }}</button>
    </div>
    <div v-if="fileName" class="attachment-chip">
      <UiIcon name="attachment" /><span>{{ fileName }}</span>
      <button type="button" aria-label="移除已上传的附件" :disabled="busy" @click="emit('remove-attachment')"><UiIcon name="close" /></button>
    </div>
    <div class="input-shell">
      <label for="chat-draft" class="sr-only">想问的问题</label>
      <textarea
        id="chat-draft"
        ref="input"
        class="draft-input"
        :value="draft"
        :placeholder="fileName ? '想了解这份文件的什么？' : variant === 'widget' ? '还有哪里拿不准？' : '说说哪一步拿不准，陶陶陪你想想。'"
        :aria-describedby="error ? 'chat-error' : undefined"
        rows="2"
        maxlength="4000"
        @input="updateDraft"
        @keydown="handleKeydown"
      />
      <button class="send-button" type="submit" :disabled="busy || !draft.trim()" :aria-label="busy ? '正在处理，请稍候' : '发送问题'" title="发送问题">
        <span v-if="busy" class="spinner" aria-hidden="true"></span><UiIcon v-else name="up" />
      </button>
    </div>
    <div class="composer-tools">
      <label class="upload-button" :class="{ 'is-disabled': busy }">
        <input class="file-input" type="file" aria-label="上传文件" :disabled="busy" @change="emit('upload', $event)" />
        <UiIcon name="attachment" /><span>上传文件</span>
      </label>
      <button v-if="hasConversation" class="new-session" type="button" @click="emit('reset')"><UiIcon name="new" />新对话</button>
    </div>
    <p v-if="uploadStatus" class="upload-feedback" role="status">{{ uploadStatus }}</p>
    <p class="input-guide">Enter 发送 · Shift + Enter 换行</p>
    <p v-if="error" id="chat-error" class="message-status" role="status" aria-live="polite">{{ error }}</p>
  </form>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import UiIcon from "./UiIcon.vue";

const props = defineProps<{
  variant: "widget" | "workspace";
  draft: string;
  busy: boolean;
  fileName: string;
  uploadStatus: string;
  error: string;
  hasConversation: boolean;
}>();
const emit = defineEmits<{
  (event: "update-draft", value: string): void;
  (event: "submit"): void;
  (event: "ask", question: string): void;
  (event: "upload", eventObject: Event): void;
  (event: "remove-attachment"): void;
  (event: "reset"): void;
  (event: "resize"): void;
}>();
const input = ref<HTMLTextAreaElement | null>(null);
const followups = ["少油一点怎么做？", "只有一个鸡蛋呢？"];
let resizeObserver: ResizeObserver | undefined;

function resizeInput(): void {
  const element = input.value;
  if (!element || element.clientWidth === 0) {
    return;
  }
  element.style.height = "auto";
  const style = getComputedStyle(element);
  element.style.height = `${Math.min(Math.max(element.scrollHeight, parseFloat(style.minHeight)), parseFloat(style.maxHeight))}px`;
  emit("resize");
}

async function focusInput(): Promise<void> {
  await nextTick();
  resizeInput();
  input.value?.focus({ preventScroll: true });
}

function updateDraft(event: Event): void {
  if (event.target instanceof HTMLTextAreaElement) {
    emit("update-draft", event.target.value);
  }
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey && !event.ctrlKey && !event.altKey && !event.metaKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    if (!props.busy && props.draft.trim()) {
      emit("submit");
    }
  }
}

watch(() => [props.draft, props.variant], () => nextTick(resizeInput));
onMounted(() => {
  resizeObserver = new ResizeObserver(resizeInput);
  if (input.value) {
    resizeObserver.observe(input.value);
  }
  void document.fonts.ready.then(resizeInput);
});
onBeforeUnmount(() => resizeObserver?.disconnect());
defineExpose({ focusInput, resizeInput });
</script>
