<template>
  <div class="document-review-grid">
    <section class="review-slices" aria-labelledby="document-slices-heading">
      <header class="review-heading">
        <h3 id="document-slices-heading">原文切片</h3>
        <div v-if="chunk" class="slice-navigation">
          <span class="slice-position" aria-live="polite">
            第 <strong>{{ String(chunk.number).padStart(2, "0") }}</strong>
            片 / 共 {{ chunk.total }} 片
          </span>
          <button
            class="admin-secondary slice-arrow"
            type="button"
            aria-label="上一片"
            title="上一片"
            :disabled="chunkBusy || chunk.number <= 1"
            @click="loadChunk(chunk.number - 1)"
          >
            <UiIcon class="previous-arrow" name="chevron" />
          </button>
          <button
            class="admin-secondary slice-arrow"
            type="button"
            aria-label="下一片"
            title="下一片"
            :disabled="chunkBusy || chunk.number >= chunk.total"
            @click="loadChunk(chunk.number + 1)"
          >
            <UiIcon name="chevron" />
          </button>
        </div>
      </header>
      <pre
        v-if="chunk"
        :key="chunk.number"
        class="admin-chunk-text"
        aria-label="切片正文"
        tabindex="0"
      >{{ chunk.content }}</pre>
      <p v-if="chunkBusy" class="admin-helper" role="status">正在读取切片…</p>
      <template v-else-if="chunkError">
        <p class="admin-error" role="alert">
          第 {{ requestedNumber }} 片读取失败。{{ chunkError }}
        </p>
        <button
          class="admin-text-button"
          type="button"
          @click="loadChunk(requestedNumber)"
        >
          重试读取切片
        </button>
      </template>
      <p v-else-if="!canReadChunks" class="admin-helper">暂无已入库的原文切片。</p>
    </section>

    <section class="ingestion-record" aria-labelledby="document-record-heading">
      <h3 id="document-record-heading">入库记录</h3>
      <ol class="ingestion-stages">
        <li v-for="stage in stages" :key="stage.name" class="ingestion-stage">
          <span
            class="stage-icon"
            :class="{ complete: stage.complete }"
            aria-hidden="true"
          >
            <UiIcon v-if="stage.complete" name="check" />
            <span v-else>·</span>
          </span>
          <div>
            <div class="stage-heading">
              <strong>{{ stage.name }}</strong>
              <span :class="{ complete: stage.complete }">{{ stage.status }}</span>
            </div>
            <p v-if="stage.detail" class="stage-detail">{{ stage.detail }}</p>
          </div>
        </li>
      </ol>
      <p
        v-if="latestJob"
        class="last-job"
        :class="{ 'last-job-failed': latestJob.status === 'failed' }"
      >
        最近任务 · {{ jobLabel(latestJob.status) }}
        <time :datetime="latestJob.updated_at">
          {{ formatAdminDate(latestJob.updated_at) }}
        </time>
      </p>
      <p v-if="latestJob?.error && latestJob.status !== 'cancelled'" class="admin-error">
        {{ latestJob.error }}
      </p>
    </section>
  </div>

  <footer class="review-tools">
    <details class="review-disclosure">
      <summary>查看来源原文</summary>
      <pre
        v-if="detail.text"
        class="admin-source-text"
        aria-label="来源原文"
        tabindex="0"
      >{{ detail.text }}</pre>
      <p v-else class="admin-helper">暂无来源原文。</p>
      <p v-if="detail.text_truncated" class="admin-helper">已显示原文的前 20,000 个字符。</p>
    </details>
    <details v-if="earlierJobs.length" class="review-disclosure admin-job-history">
      <summary>历史入库任务 · {{ earlierJobs.length }}</summary>
      <ol>
        <li v-for="job in earlierJobs" :key="job.id">
          <div>
            <strong>{{ jobLabel(job.status) }}</strong>
            <time :datetime="job.updated_at">{{ formatAdminDate(job.updated_at) }}</time>
          </div>
          <p v-if="job.error && job.status !== 'cancelled'" class="admin-error">
            {{ job.error }}
          </p>
          <details>
            <summary>任务明细</summary>
            <pre>{{ JSON.stringify(job.details, null, 2) }}</pre>
          </details>
        </li>
      </ol>
    </details>
    <div class="review-actions" role="group" aria-label="文档操作">
      <div v-if="$slots.actions" class="review-action-group review-action-group--review" role="group" aria-label="核对资料">
        <slot name="actions" />
      </div>
      <div class="review-action-group review-action-group--processing" role="group" aria-label="入库与检索">
        <button class="admin-text-button" type="button" :disabled="busy || hasActiveIngestion" @click="emit('edit')">编辑原文</button>
        <button
          class="admin-text-button"
          type="button"
          :disabled="busy"
          @click="emit('retry')"
        >
          {{ busy ? "处理中…" : source.status === "withdrawn" ? "恢复文档入库" : "重新入库" }}
        </button>
        <button
          v-if="source.status !== 'withdrawn'"
          class="admin-text-button"
          type="button"
          :disabled="busy"
          @click="emit('withdraw')"
        >
          撤回文档检索
        </button>
      </div>
      <div class="review-action-group review-action-group--danger" role="group" aria-label="删除记录">
        <button
          class="admin-text-button admin-delete-button"
          type="button"
          :disabled="busy || hasActiveIngestion"
          :aria-describedby="hasActiveIngestion ? 'document-delete-unavailable' : undefined"
          @click="emit('delete')"
        >
          删除文档记录
        </button>
      </div>
    </div>
    <p v-if="hasActiveIngestion" id="document-delete-unavailable" class="admin-helper delete-unavailable">
      入库任务尚未完成，结束后可删除文档记录。
    </p>
  </footer>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import UiIcon from "../components/UiIcon.vue";
import {
  errorMessage,
  formatAdminDate,
  isRecord,
  readSourceChunk,
  stateLabel,
} from "./api";
import type { SourceChunk, SourceDetail } from "./contracts";

const props = defineProps<{ detail: SourceDetail; busy: boolean }>();
const emit = defineEmits<{ retry: []; withdraw: []; delete: []; edit: [] }>();

const source = computed(() => props.detail.source);
const hasActiveIngestion = computed(
  () => ["pending", "processing"].includes(source.value.status) ||
    ["pending", "processing"].includes(source.value.latest_job?.status ?? "") ||
    props.detail.jobs.some((job) => ["pending", "processing"].includes(job.status)),
);
const latestJob = computed(() => source.value.latest_job ?? props.detail.jobs[0]);
const earlierJobs = computed(() =>
  props.detail.jobs.filter((job) => job.id !== latestJob.value?.id),
);
const successfulJob = computed(() =>
  props.detail.jobs.find(
    (job) =>
      job.status === "ready" &&
      job.source_version === source.value.version &&
      job.details.ontology_version === source.value.ontology_version,
  ),
);
const canReadChunks = computed(
  () =>
    source.value.kind === "document" &&
    (source.value.status === "ready" ||
      source.value.status === "withdrawn" ||
      Boolean(successfulJob.value)),
);

const chunk = ref<SourceChunk | null>(null);
const chunkBusy = ref(false);
const chunkError = ref("");
let requestedNumber = 1;
let controller: AbortController | undefined;

const stages = computed(() => {
  const hasText = props.detail.text.trim().length > 0;
  const receipt = successfulJob.value?.details.document;
  const recordedCount =
    isRecord(receipt) && typeof receipt.chunks === "number" ? receipt.chunks : 0;
  const count = chunk.value?.total ?? (recordedCount || source.value.chunks || 0);
  const indexed = Boolean(successfulJob.value || chunk.value);
  let indexStatus = "暂无入库记录";
  if (source.value.status === "withdrawn") indexStatus = stateLabel("withdrawn");
  else if (source.value.status === "ready") indexStatus = "可检索";
  else if (indexed) indexStatus = "曾完成入库";

  return [
    { name: "解析", status: hasText ? "已取得正文" : "暂无正文", complete: hasText, detail: "" },
    {
      name: "切块",
      status: count > 0 ? "已生成切片" : "暂无切片记录",
      complete: count > 0,
      detail: count > 0 ? `${count} 个切片` : "",
    },
    {
      name: "向量入库",
      status: indexStatus,
      complete: indexed && source.value.status !== "withdrawn",
      detail: indexed ? "Milvus" : "",
    },
  ];
});

function jobLabel(status: string): string {
  return status === "ready" ? "已完成入库" : stateLabel(status);
}

async function loadChunk(number: number): Promise<void> {
  controller?.abort();
  const request = new AbortController();
  controller = request;
  requestedNumber = number;
  chunkBusy.value = true;
  chunkError.value = "";
  try {
    const result = await readSourceChunk(source.value, number, request.signal);
    if (!request.signal.aborted) chunk.value = result;
  } catch (error) {
    if (!request.signal.aborted) chunkError.value = errorMessage(error);
  } finally {
    if (!request.signal.aborted) chunkBusy.value = false;
  }
}

watch(
  [
    () => source.value.source_id,
    () => source.value.version,
    () => source.value.ontology_version,
    () => successfulJob.value?.id,
    canReadChunks,
  ],
  () => {
    chunk.value = null;
    chunkError.value = "";
    if (canReadChunks.value) {
      void loadChunk(1);
    } else {
      controller?.abort();
      chunkBusy.value = false;
    }
  },
  { immediate: true },
);
onUnmounted(() => controller?.abort());
</script>

<style scoped>
.document-review-grid {
  display: flex;
  flex: 0 1 auto;
  flex-direction: column;
  min-height: 0;
  overflow: auto;
}
.review-slices,
.ingestion-record {
  min-width: 0;
  padding: 22px 24px;
}
.review-slices {
  display: flex;
  flex: none;
  flex-direction: column;
  min-height: 0;
}
.ingestion-record {
  flex: none;
  border-top: 1px solid var(--line);
}
.document-review-grid h3 {
  margin: 0;
  font: 600 18px/1.4 var(--serif);
}
.review-heading,
.slice-navigation,
.stage-heading,
.last-job {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 8px;
}
.review-heading {
  justify-content: space-between;
  min-height: 32px;
}
.slice-position,
.stage-detail,
.last-job {
  color: var(--muted);
  font-size: 13px;
}
.slice-position strong {
  color: var(--clay);
  font-size: 17px;
  font-variant-numeric: tabular-nums;
}
.slice-arrow {
  width: 44px;
  min-height: 44px;
  padding: 0;
}
.slice-arrow .ui-icon {
  width: 16px;
  height: 16px;
}
.previous-arrow {
  transform: rotate(180deg);
}
.admin-chunk-text {
  flex: none;
  min-height: 0;
  max-height: min(42dvh, max(160px, calc(100dvh - 520px)), 420px);
  margin: 12px 0 0;
  padding: 20px 22px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--paper);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: 16px/1.9 var(--sans);
}
.ingestion-stages {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
}
.ingestion-stage {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  align-items: start;
  gap: 9px;
  min-width: 0;
  padding: 0;
}
.stage-icon {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: var(--paper);
  color: var(--subtle);
}
.stage-icon.complete {
  border-color: #cbd5c3;
  background: #edf2e9;
}
.stage-icon .ui-icon {
  width: 14px;
  height: 14px;
}
.stage-heading strong {
  display: block;
  font-size: 14px;
}
.stage-heading {
  display: block;
}
.stage-heading span {
  display: block;
  color: var(--muted);
  font-size: 13px;
}
.stage-icon.complete,
.stage-heading span.complete {
  color: #42533e;
}
.stage-detail {
  margin: 4px 0 0;
}
.last-job {
  margin: 14px 0 0;
}
.last-job-failed {
  color: var(--clay);
}
.review-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 18px;
  padding: 10px 24px;
  flex: none;
  max-height: min(50vh, 380px);
  overflow: auto;
  border-top: 1px solid var(--line);
}
.review-disclosure {
  margin: 0;
  min-width: 0;
  color: var(--muted);
  font-size: 13px;
}
.review-disclosure[open] {
  flex-basis: 100%;
}
.review-disclosure summary {
  min-height: 44px;
  padding-block: 12px;
  box-sizing: border-box;
  cursor: pointer;
}
.review-actions,
.review-action-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 12px;
}
.review-actions {
  margin-left: auto;
}
.review-actions .admin-text-button,
.review-action-group--review :slotted(.admin-text-button) {
  min-height: 44px;
  padding-inline: 6px;
}
.review-action-group--review :slotted(.admin-text-button) {
  padding-inline: 10px;
  border: 1px solid var(--control-line);
  border-radius: 6px;
  color: var(--muted);
}
.review-action-group--processing .admin-text-button {
  color: var(--muted);
}
.review-action-group--danger {
  padding-left: 12px;
  border-left: 1px solid var(--line);
}
.delete-unavailable {
  flex-basis: 100%;
  margin: 0;
  text-align: right;
}
@media (max-width: 1100px) {
  .document-review-grid { overflow: visible; }
  .admin-chunk-text { max-height: 420px; }
}
@media (max-width: 700px) {
  .review-slices,
  .ingestion-record {
    padding: 18px 16px;
  }
  .review-slices { min-height: 0; }
  .admin-chunk-text { max-height: 320px; padding: 16px; }
  .ingestion-stages { grid-template-columns: minmax(0, 1fr); gap: 14px; }
  .stage-heading { display: flex; }
  .review-tools {
    padding: 10px 16px;
  }
  .review-actions {
    justify-content: flex-start;
    width: 100%;
    margin-left: 0;
  }
  .review-action-group--danger {
    flex-basis: 100%;
    padding: 4px 0 0;
    border-top: 1px solid var(--line);
    border-left: 0;
  }
  .delete-unavailable { text-align: left; }
}
</style>
