<template>
  <section
    class="question-tester"
    :class="{ 'is-compact': compact }"
    aria-labelledby="test-heading"
  >
    <header class="admin-panel-heading">
      <h2 id="test-heading">问答测试</h2>
      <span class="admin-muted">当前知识空间</span>
    </header>
    <p v-if="!compact" class="admin-helper">
      用实际问题核对回答、来源和用量记录。
    </p>
    <form @submit.prevent="runQuestion">
      <label class="admin-field"
        >测试问题<textarea
          v-model="question"
          rows="2"
          maxlength="5000"
          required
          placeholder="例如：佛跳墙的冰糖用量有记录吗？"
        ></textarea>
      </label>
      <div class="question-actions">
        <button
          class="admin-primary"
          type="submit"
          :disabled="busy || !question.trim()"
        >
          <UiIcon name="test" />{{ busy ? "正在查询…" : "运行问答" }}
        </button>
      </div>
      <details class="expected-answer">
        <summary>添加预期回答，人工对照</summary>
        <label class="admin-field"
          >预期回答<textarea
            v-model="expected"
            rows="2"
            placeholder="只填写经过核对的预期内容"
          ></textarea>
        </label>
      </details>
    </form>
    <p v-if="error" class="admin-error" role="alert">{{ error }}</p>
    <article v-if="answer" class="test-result" aria-label="实际问答结果">
      <header>
        <strong :class="`query-state-${resultStatus.tone}`" role="status">{{
          resultStatus.label
        }}</strong
        ><span>{{ elapsed.toFixed(2) }} 秒 · 请求耗时</span>
        <span v-if="typeof answer.metadata.model_calls === 'number'"
          >大模型 {{ answer.metadata.model_calls }} 次</span
        >
      </header>
      <p class="question-snapshot">{{ submittedQuestion }}</p>
      <div class="test-answer" :class="`query-message-${resultStatus.tone}`">
        {{ answer.message }}
      </div>
      <div v-if="submittedExpected" class="expected-result">
        <span class="admin-muted">本次预期 · 人工核对</span>
        <p>{{ submittedExpected }}</p>
      </div>
      <p v-if="submittedSource" class="citation-check">
        <UiIcon name="link" /><span
          >{{ citationLabel }}<br /><small>{{
            submittedSource.title
          }}</small></span
        >
      </p>
      <details v-if="answer.sources.length" class="test-sources" open>
        <summary>返回来源 · {{ answer.sources.length }}</summary>
        <ul>
          <li v-for="(source, index) in answer.sources" :key="index">
            <a
              v-if="getSourceUrl(source)"
              :href="getSourceUrl(source) ?? undefined"
              target="_blank"
              rel="noopener noreferrer"
              >{{ formatSource(source) }}</a
            ><span v-else>{{ formatSource(source) }}</span>
          </li>
        </ul>
      </details>
      <p v-else class="admin-helper">本次没有返回可核对的来源。</p>
      <details class="test-trace">
        <summary>查看检索与执行明细</summary>
        <pre>{{
          JSON.stringify(
            { route: answer.route, metadata: answer.metadata },
            null,
            2,
          )
        }}</pre>
      </details>
    </article>
    <p v-else-if="!busy" class="test-empty">
      <UiIcon name="ask" />尚未运行问题，回答与来源将在这里显示。
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import UiIcon from "../components/UiIcon.vue";
import { formatSource, getSourceUrl } from "../lib/chat";
import {
  classifyAnswerStatus,
  errorMessage,
  isCancelled,
  queryKnowledge,
} from "./api";
import type { KnowledgeAnswer, SourceSummary } from "./contracts";

const props = withDefaults(
  defineProps<{ source: SourceSummary | null; compact?: boolean }>(),
  { compact: false },
);
const question = ref("");
const expected = ref("");
const busy = ref(false);
const error = ref("");
const answer = ref<KnowledgeAnswer | null>(null);
const elapsed = ref(0);
const submittedQuestion = ref("");
const submittedExpected = ref("");
const submittedSource = ref<SourceSummary | null>(null);
let controller: AbortController | null = null;
const resultStatus = computed(() =>
  classifyAnswerStatus(answer.value?.metadata.status),
);

const citationLabel = computed(() => {
  const source = submittedSource.value;
  if (!source || !answer.value) return "";
  const matched = answer.value.sources.some(
    (item) =>
      item.source_id === source.source_id ||
      item.id === source.source_id ||
      item.document_id === source.source_id ||
      item.source === source.uri ||
      (Array.isArray(item.source_ids) &&
        item.source_ids.includes(source.source_id)),
  );
  return matched
    ? "返回来源包含本次核对资料，版本见明细。"
    : "返回来源中未找到本次核对资料；本次查询面向整个知识空间。";
});

async function runQuestion(): Promise<void> {
  if (busy.value || !question.value.trim()) return;
  controller?.abort();
  const request = new AbortController();
  controller = request;
  busy.value = true;
  error.value = "";
  const currentQuestion = question.value.trim();
  const currentExpected = expected.value.trim();
  const currentSource = props.source;
  const start = performance.now();
  try {
    const result = await queryKnowledge(currentQuestion, request.signal);
    if (request.signal.aborted) return;
    answer.value = result;
    elapsed.value = (performance.now() - start) / 1000;
    submittedQuestion.value = currentQuestion;
    submittedExpected.value = currentExpected;
    submittedSource.value = currentSource;
  } catch (failure) {
    if (!isCancelled(failure)) error.value = errorMessage(failure);
  } finally {
    if (!request.signal.aborted) busy.value = false;
  }
}

onBeforeUnmount(() => controller?.abort());
</script>

<style scoped lang="scss">
.question-tester {
  min-width: 0;
  padding: 22px;
  background: var(--surface);
}
.question-tester form {
  margin-top: 16px;
}
.question-tester.is-compact form {
  margin-top: 8px;
}
.question-tester textarea {
  width: 100%;
}
.expected-answer {
  margin: 0 0 16px;
  color: var(--subtle);
  font-size: 13px;
}
.question-actions {
  margin-bottom: 12px;
}
.expected-answer .admin-field {
  margin-top: 12px;
}
.test-empty {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-top: 28px;
  padding-top: 20px;
  border-top: 1px solid var(--line);
  font-size: 13px;
  color: var(--subtle);
}
.test-result {
  margin-top: 22px;
  padding-top: 20px;
  border-top: 1px solid var(--line);
}
.test-result > header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 14px;
}
.test-result > header span {
  font-size: 13px;
  color: var(--subtle);
}
.question-snapshot {
  margin: 12px 0 16px;
  padding: 10px 12px;
  background: var(--paper);
  font-size: 13px;
  color: var(--muted);
}
.test-answer {
  font-size: 16px;
  line-height: 1.85;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.query-state-ready {
  color: #50624c;
}
.query-state-pending {
  color: #87601e;
}
.query-state-error {
  color: #82381e;
}
.query-message-pending {
  padding: 12px;
  border-left: 3px solid #a5792a;
  background: #f5ecd9;
}
.query-message-error {
  padding: 12px;
  border-left: 3px solid var(--clay);
  background: #f7e9df;
}
.expected-result {
  margin-top: 16px;
  padding: 12px;
  border-left: 2px solid var(--control-line);
  font-size: 14px;
}
.expected-result > p {
  margin-top: 6px;
}
.citation-check {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 16px;
  color: var(--muted);
  font-size: 13px;
}
.citation-check small {
  font-size: 13px;
  color: var(--subtle);
}
.test-sources,
.test-trace {
  margin-top: 18px;
  font-size: 13px;
}
.test-sources ul {
  padding-left: 18px;
  overflow-wrap: anywhere;
}
.test-sources li + li {
  margin-top: 8px;
}
.test-sources a {
  color: var(--clay);
  text-decoration: underline;
}
.test-trace pre {
  max-height: 260px;
  padding: 12px;
  overflow: auto;
  background: var(--paper);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 13px;
}
</style>
