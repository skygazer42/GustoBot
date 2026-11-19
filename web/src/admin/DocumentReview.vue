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
    <div class="review-actions">
      <slot name="actions" />
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
const emit = defineEmits<{ retry: []; withdraw: [] }>();

const source = computed(() => props.detail.source);
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
  if (source.value.status === "withdrawn") indexStatus = "已撤回";
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
  display: grid;
  grid-template-columns: minmax(0, 1.32fr) minmax(0, 1fr);
}
.review-slices,
.ingestion-record {
  min-width: 0;
  padding: 16px 18px 18px;
}
.ingestion-record {
  border-left: 1px solid var(--line);
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
  width: 32px;
  min-height: 32px;
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
  max-height: 168px;
  margin: 9px 0 0;
  padding: 13px 16px 15px;
  overflow: auto;
  border-left: 2px solid var(--clay);
  background: var(--paper);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: 16px/1.75 var(--sans);
}
.ingestion-stages {
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}
.ingestion-stage {
  position: relative;
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  align-items: start;
  gap: 9px;
  min-height: 35px;
  padding: 2px 0;
}
.ingestion-stage:not(:last-child)::after {
  position: absolute;
  top: 27px;
  bottom: 0;
  left: 11px;
  border-left: 1px solid var(--line);
  content: "";
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
  font-size: 14px;
}
.stage-heading span {
  color: var(--muted);
  font-size: 13px;
}
.stage-icon.complete,
.stage-heading span.complete {
  color: #42533e;
}
.stage-detail {
  margin: 0;
}
.last-job {
  margin: 7px 0 0;
}
.last-job-failed {
  color: var(--clay);
}
.review-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 0 18px;
  padding: 2px 18px;
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
  padding-block: 10px;
  cursor: pointer;
}
.review-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0 14px;
  margin-left: auto;
}
@media (max-width: 700px) {
  .document-review-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .ingestion-record {
    border-top: 1px solid var(--line);
    border-left: 0;
  }
  .slice-arrow {
    width: 44px;
    min-height: 44px;
  }
}
</style>
