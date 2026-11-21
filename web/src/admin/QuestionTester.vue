<template>
  <section class="question-tester" aria-label="问答测试工作区">
    <section class="question-setup" aria-label="测试设置">
      <header class="question-panel-heading">
        <h2 id="test-heading">测试设置</h2>
        <span>单次问答核对</span>
      </header>
      <form @submit.prevent="runQuestion">
        <div class="question-inputs">
          <p class="question-scope"><span>查询范围</span><strong>当前知识空间</strong></p>
          <label class="admin-field question-prompt">
            <span class="question-field-label"><span>测试问题</span><small aria-hidden="true">{{ question.length }} / 5000</small></span>
            <textarea v-model="question" rows="6" maxlength="5000" required placeholder="输入需要核对的问题，例如对象关系、筛选条件或原文记录。"></textarea>
          </label>
          <details class="expected-answer">
            <summary>添加预期回答，人工对照</summary>
            <label class="admin-field">预期回答<textarea v-model="expected" rows="4" placeholder="填写已经核对的预期内容"></textarea></label>
            <p>预期内容仅用于人工对照，不自动判定答案是否正确。</p>
          </details>
          <div v-if="source" class="question-context">
            <span>对照资料</span><strong>{{ source.title }}</strong>
            <p>核对引用是否包含这份资料，查询范围仍为整个知识空间。</p>
          </div>
        </div>
        <footer class="question-actions">
          <button class="admin-primary" type="submit" :disabled="busy || !question.trim()">
            <UiIcon name="test" />{{ busy ? "正在查询…" : "运行问答" }}
          </button>
        </footer>
      </form>
    </section>

    <section class="question-output" aria-labelledby="test-result-heading" :aria-busy="busy">
      <header class="question-panel-heading">
        <h2 id="test-result-heading">运行结果</h2>
        <span>{{ busy ? "查询中" : error ? "请求未完成" : answer ? "已收到返回" : "等待运行" }}</span>
      </header>
      <div class="question-output-body" role="region" aria-label="问答结果阅读区" tabindex="0">
        <div v-if="busy" class="test-running" role="status">
          <UiIcon name="clock" /><div><strong>正在检索并生成回答</strong>
            <p>{{ answer ? "下方保留上次返回的结果" : "完成后显示本次回答与引用来源。" }}</p>
          </div>
        </div>
        <div v-if="error" class="test-query-error" role="alert">
          <strong>请求未完成</strong><p>{{ error }}</p>
          <p>问题与预期内容已保留，可修改后重新运行。</p>
          <p v-if="answer">下方保留上次返回的结果</p>
        </div>
        <article v-if="answer" class="test-result" aria-label="实际问答结果">
          <header>
            <strong :class="'query-state-' + resultStatus.tone" role="status">{{ resultStatus.label }}</strong>
            <div class="test-response-metrics">
              <span>{{ elapsed.toFixed(2) }} 秒 · 请求耗时</span>
              <span v-if="typeof answer.metadata.model_calls === 'number'">大模型 {{ answer.metadata.model_calls }} 次</span>
            </div>
          </header>
          <div class="question-snapshot"><span>对应问题</span><p>{{ submittedQuestion }}</p></div>
          <div class="test-answer" :class="'query-message-' + resultStatus.tone">{{ answer.message }}</div>
          <div v-if="submittedExpected" class="expected-result">
            <span class="admin-muted">对应预期 · 人工核对</span><p>{{ submittedExpected }}</p>
          </div>
          <p v-if="submittedSource" class="citation-check">
            <UiIcon name="link" /><span>{{ citationLabel }}<br /><small>{{ submittedSource.title }}</small></span>
          </p>
          <details v-if="answer.sources.length" class="test-sources" open>
            <summary>返回来源 · {{ answer.sources.length }}</summary>
            <ul><li v-for="(citation, index) in answer.sources" :key="index">
              <a v-if="getSourceUrl(citation)" :href="getSourceUrl(citation) ?? undefined" target="_blank" rel="noopener noreferrer">{{ formatSource(citation) }}</a>
              <span v-else>{{ formatSource(citation) }}</span>
            </li></ul>
          </details>
          <p v-else class="admin-helper">本次没有返回可核对的来源。</p>
          <details class="test-trace">
            <summary>查看检索与执行明细</summary>
            <p v-if="answer.route_logic" class="test-route-logic">{{ answer.route_logic }}</p>
            <pre tabindex="0">{{ JSON.stringify({ route: answer.route, metadata: answer.metadata }, null, 2) }}</pre>
          </details>
        </article>
        <div v-else-if="!busy && !error" class="test-empty">
          <span class="test-empty-icon"><UiIcon name="ask" /></span>
          <h3>等待第一条问题</h3>
          <p>输入问题并运行问答，在这里核对实际回答、引用来源和执行记录。</p>
        </div>
      </div>
    </section>
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

const props = defineProps<{ source: SourceSummary | null }>();
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
    ? "返回来源包含对应资料的标识，请核对版本和原文。"
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
    if (!request.signal.aborted && !isCancelled(failure)) error.value = errorMessage(failure);
  } finally {
    if (!request.signal.aborted) busy.value = false;
  }
}

onBeforeUnmount(() => controller?.abort());
</script>

<style scoped lang="scss">
.question-tester {
  display: grid;
  grid-template-columns: clamp(320px, 25vw, 390px) minmax(0, 1fr);
  gap: 18px;
  height: calc(100dvh - 112px);
  min-height: 540px;
  min-width: 0;
}
.question-setup,
.question-output {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface);
}
.question-panel-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
  min-height: 56px;
  padding: 13px 20px;
  border-bottom: 1px solid var(--line);
}
.question-panel-heading h2 { margin: 0; font: 600 18px/1.4 var(--serif); }
.question-panel-heading > span { color: var(--subtle); font-size: 13px; }
.question-setup form { display: flex; flex: 1; flex-direction: column; min-height: 0; margin: 0; }
.question-inputs { flex: 1; min-height: 0; overflow: auto; padding: 20px; }
.question-scope { display: flex; flex-wrap: wrap; gap: 8px 12px; margin: 0 0 20px; padding-bottom: 14px; border-bottom: 1px solid var(--line); font-size: 13px; }
.question-scope > span { color: var(--subtle); }
.question-scope strong { color: var(--muted); font-weight: 500; }
.question-field-label { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.question-field-label small { color: var(--subtle); font-size: 13px; font-variant-numeric: tabular-nums; }
.question-tester textarea { width: 100%; line-height: 1.7; resize: vertical; }
.question-prompt textarea { min-height: 144px; }
.question-actions { margin-top: auto; padding: 16px 20px; border-top: 1px solid var(--line); }
.question-actions .admin-primary { width: 100%; min-height: 44px; }
.expected-answer { margin-top: 18px; color: var(--muted); font-size: 13px; }
.expected-answer summary { min-height: 44px; padding-block: 10px; cursor: pointer; }
.expected-answer .admin-field { margin-top: 10px; }
.expected-answer > p { margin: 10px 0 0; color: var(--subtle); line-height: 1.7; }
.question-context { display: grid; gap: 8px; margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--line); font-size: 13px; }
.question-context > span { color: var(--subtle); }
.question-context strong { overflow-wrap: anywhere; font-size: 14px; font-weight: 600; }
.question-context p { margin: 0; color: var(--subtle); line-height: 1.7; }
.question-output-body { flex: 1; min-height: 0; overflow: auto; padding: 22px; }
.question-output-body:focus-visible { outline: 2px solid var(--clay); outline-offset: -3px; }
.test-empty { display: grid; justify-items: center; align-content: center; gap: 12px; height: 100%; min-height: 260px; padding: 24px; text-align: center; }
.test-empty-icon { display: grid; place-items: center; width: 40px; height: 40px; border: 1px solid var(--line); border-radius: 7px; color: var(--clay); background: var(--paper); }
.test-empty-icon .ui-icon { width: 20px; height: 20px; }
.test-empty h3 { margin: 0; font: 600 22px/1.4 var(--serif); }
.test-empty > p { max-width: 340px; margin: 0; color: var(--subtle); font-size: 14px; line-height: 1.8; }
.test-running { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 20px; padding: 16px; border: 1px solid var(--line); border-radius: 7px; background: var(--paper); font-size: 14px; }
.test-running > .ui-icon { flex: none; margin-top: 2px; color: var(--clay); }
.test-running p { margin: 6px 0 0; color: var(--subtle); font-size: 13px; line-height: 1.7; }
.test-query-error { margin-bottom: 20px; padding: 16px; border-left: 3px solid var(--clay); background: #f7e9df; color: #82381e; font-size: 14px; }
.test-query-error p { margin: 8px 0 0; line-height: 1.7; overflow-wrap: anywhere; }
.test-result { margin: 0; }
.test-result > header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px 16px; padding-bottom: 12px; border-bottom: 1px solid var(--line); font-size: 14px; }
.test-response-metrics { display: flex; flex-wrap: wrap; gap: 6px 16px; color: var(--subtle); font-size: 13px; font-variant-numeric: tabular-nums; }
.question-snapshot { margin: 18px 0; padding: 2px 0 2px 12px; border-left: 2px solid var(--control-line); color: var(--muted); font-size: 14px; line-height: 1.7; overflow-wrap: anywhere; }
.question-snapshot > span { color: var(--subtle); font-size: 13px; }
.question-snapshot > p { margin: 6px 0 0; white-space: pre-wrap; }
.test-answer { max-width: 70ch; font-size: 16px; line-height: 1.85; white-space: pre-wrap; overflow-wrap: anywhere; }
.query-state-ready { color: #50624c; }
.query-state-pending { color: #87601e; }
.query-state-error { color: #82381e; }
.query-message-pending { padding: 14px; border-left: 3px solid #a5792a; background: #f5ecd9; }
.query-message-error { padding: 14px; border-left: 3px solid var(--clay); background: #f7e9df; }
.expected-result { margin-top: 20px; padding: 14px; border-left: 2px solid var(--control-line); background: var(--paper); font-size: 14px; }
.expected-result > p { margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
.citation-check { display: flex; align-items: flex-start; gap: 8px; margin-top: 20px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.citation-check > .ui-icon { flex: none; margin-top: 2px; }
.citation-check small { color: var(--subtle); font-size: 13px; overflow-wrap: anywhere; }
.test-sources,
.test-trace { margin-top: 22px; padding-top: 16px; border-top: 1px solid var(--line); font-size: 13px; }
.test-sources summary,
.test-trace summary { min-height: 36px; padding-block: 8px; cursor: pointer; color: var(--muted); }
.test-sources ul { padding-left: 18px; line-height: 1.8; overflow-wrap: anywhere; }
.test-sources li + li { margin-top: 10px; }
.test-sources a { color: var(--clay); text-decoration: underline; }
.test-route-logic { color: var(--subtle); line-height: 1.8; overflow-wrap: anywhere; }
.test-trace pre { max-height: 280px; padding: 14px; overflow: auto; border-radius: 5px; background: var(--paper); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; }
@media (max-width: 1100px) {
  .question-tester { grid-template-columns: minmax(0, 1fr); height: auto; min-height: 0; }
  .question-inputs { overflow: visible; }
  .question-output-body { min-height: 360px; max-height: none; overflow: visible; }
  .question-prompt textarea { min-height: 120px; }
  .test-empty { min-height: 260px; }
}
@media (max-width: 700px) {
  .question-tester { gap: 16px; }
  .question-panel-heading { padding: 16px; }
  .question-inputs, .question-output-body { padding: 18px 16px; }
  .question-scope { margin-bottom: 20px; }
  .question-actions { padding: 14px 16px; }
  .expected-answer summary { min-height: 44px; }
  .test-sources summary, .test-trace summary { min-height: 44px; padding-block: 12px; }
  .test-empty { padding: 16px; }
  .test-empty h3 { font-size: 22px; }
  .test-answer { font-size: 16px; }
}
</style>
