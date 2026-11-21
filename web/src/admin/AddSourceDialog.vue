<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import UiIcon from "../components/UiIcon.vue";
import {
  errorMessage,
  ingestDocument,
  ingestRecipe,
  ingestText,
  parseRecipeRecord,
  readDocument,
  updateDocument,
  uploadDocument,
} from "./api";
import type { DocumentContent, IngestionReceipt, SourceSummary } from "./contracts";

const props = defineProps<{
  open: boolean;
  kind: "document" | "recipe";
  source: Pick<SourceSummary, "source_id" | "version"> | null;
}>();
const emit = defineEmits<{ close: []; created: [receipt: IngestionReceipt] }>();

const dialog = ref<HTMLDialogElement | null>(null);
const mode = ref<"document" | "text" | "recipe">("document");
const file = ref<File | null>(null);
const fileTitle = ref("");
const textTitle = ref("");
const text = ref("");
const recipeName = ref("");
const recipeRecord = ref("");
const error = ref("");
const busy = ref<"load" | "upload" | "ingest" | null>(null);
const originalDocument = ref<DocumentContent | null>(null);
const isEditing = computed(() => props.source !== null);
const isSubmitting = computed(() => busy.value !== null);
const hasUnsavedChanges = computed(
  () => isEditing.value && originalDocument.value !== null && (
    textTitle.value !== originalDocument.value.title || text.value !== originalDocument.value.text
  ),
);
defineExpose({ isSubmitting, hasUnsavedChanges });
let contentController: AbortController | null = null;
let assetId: string | null = null;
let manualSourceId = `manual:${crypto.randomUUID()}`;
let returnFocus: HTMLElement | null = null;
let active = true;
let addDraft: {
  title: string;
  text: string;
  sourceId: string;
  mode: typeof mode.value;
} | null = null;

const submitLabel = computed(() => {
  if (busy.value === "load") return "正在读取原文…";
  if (busy.value === "upload") return "正在上传…";
  if (busy.value === "ingest") return "正在入库…";
  if (isEditing.value) return "保存并更新检索";
  return mode.value === "recipe"
    ? "添加菜谱记录"
    : mode.value === "text"
      ? "添加文本"
      : "添加文档";
});

watch(
  () => props.open,
  async (open) => {
    await nextTick();
    if (!active || !dialog.value) return;
    if (open && !dialog.value.open) {
      if (isEditing.value) {
        addDraft = {
          title: textTitle.value,
          text: text.value,
          sourceId: manualSourceId,
          mode: mode.value,
        };
        selectMode("text");
      } else if (props.kind === "recipe") selectMode("recipe");
      else if (mode.value === "recipe") selectMode("document");
      returnFocus =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      dialog.value.showModal();
      if (isEditing.value) void loadDocument();
    } else if (!open && dialog.value.open) {
      contentController?.abort();
      if (busy.value === "load") busy.value = null;
      dialog.value.close();
      if (addDraft !== null) {
        textTitle.value = addDraft.title;
        text.value = addDraft.text;
        manualSourceId = addDraft.sourceId;
        mode.value = addDraft.mode;
        addDraft = null;
      }
      returnFocus?.focus();
    }
  },
  { immediate: true, flush: "post" },
);

onBeforeUnmount(() => {
  active = false;
  contentController?.abort();
  dialog.value?.close();
});

function close(): void {
  if (busy.value === null || busy.value === "load") emit("close");
}

async function loadDocument(): Promise<void> {
  const source = props.source;
  if (source === null) return;
  contentController?.abort();
  const request = new AbortController();
  contentController = request;
  originalDocument.value = null;
  textTitle.value = "";
  text.value = "";
  busy.value = "load";
  error.value = "";
  try {
    const document = await readDocument(source, request.signal);
    if (!active || request.signal.aborted) return;
    originalDocument.value = document;
    textTitle.value = document.title;
    text.value = document.text;
  } catch (failure) {
    if (active && !request.signal.aborted) error.value = errorMessage(failure);
  } finally {
    if (active && !request.signal.aborted) busy.value = null;
  }
}

function selectMode(nextMode: "document" | "text" | "recipe"): void {
  mode.value = nextMode;
  error.value = "";
}

function selectFile(event: Event): void {
  const input = event.target as HTMLInputElement;
  file.value = null;
  assetId = null;
  error.value = "";
  const selected = input.files?.[0];
  if (!selected) return;
  if (!/\.(txt|md|markdown|csv|json|log|pdf|docx)$/i.test(selected.name)) {
    error.value = "请选择 TXT、Markdown、CSV、JSON、LOG、PDF 或 DOCX 文档。";
    input.value = "";
    return;
  }
  if (selected.size > 50 * 1024 * 1024) {
    error.value = "文件不能超过 50 MB。请拆分后再添加。";
    input.value = "";
    return;
  }
  file.value = selected;
  fileTitle.value = selected.name;
}

function resetDraft(): void {
  if (mode.value === "document") {
    file.value = null;
    fileTitle.value = "";
    assetId = null;
    const input = dialog.value?.querySelector<HTMLInputElement>('input[type="file"]');
    if (input) input.value = "";
  } else if (mode.value === "text") {
    textTitle.value = "";
    text.value = "";
    manualSourceId = `manual:${crypto.randomUUID()}`;
  } else {
    recipeName.value = "";
    recipeRecord.value = "";
  }
}

async function submit(): Promise<void> {
  if (busy.value) return;
  error.value = "";
  try {
    let receipt: IngestionReceipt;
    if (isEditing.value) {
      if (originalDocument.value === null) throw new Error("请先读取完整原文。");
      if (!textTitle.value.trim() || !text.value.trim())
        throw new Error("请填写资料名称和正文。");
      busy.value = "ingest";
      receipt = await updateDocument({
        ...originalDocument.value,
        title: textTitle.value.trim(),
        text: text.value,
      });
    } else if (mode.value === "document") {
      if (!file.value) throw new Error("请先选择文档。");
      if (!fileTitle.value.trim()) throw new Error("请填写资料名称。");
      busy.value = assetId ? "ingest" : "upload";
      if (!assetId) {
        assetId = await uploadDocument(file.value);
        if (!active) return;
      }
      busy.value = "ingest";
      receipt = await ingestDocument(assetId, fileTitle.value.trim());
    } else if (mode.value === "text") {
      if (!textTitle.value.trim() || !text.value.trim())
        throw new Error("请填写资料名称和正文。");
      busy.value = "ingest";
      receipt = await ingestText(
        textTitle.value.trim(),
        text.value,
        manualSourceId,
      );
    } else {
      if (!recipeName.value.trim()) throw new Error("请填写菜名。");
      const record = parseRecipeRecord(recipeRecord.value);
      busy.value = "ingest";
      receipt = await ingestRecipe(recipeName.value.trim(), record);
    }
    if (!active) return;
    if (receipt.status === "failed" || receipt.status === "cancelled") {
      throw new Error(receipt.error || "入库未完成，请核对输入后重试。");
    }
    resetDraft();
    originalDocument.value = null;
    emit("created", receipt);
  } catch (reason) {
    if (active) {
      const message = errorMessage(reason);
      error.value = message === "PDF has no extractable text; OCR is required before ingestion"
        ? "未提取到文字。请先对扫描件做 OCR，再上传含文本的 PDF。"
        : message;
    }
  } finally {
    if (active) busy.value = null;
  }
}
</script>

<template>
  <dialog
    ref="dialog"
    class="add-source-dialog"
    aria-labelledby="add-source-title"
    @cancel.prevent="close"
    @close="props.open && emit('close')"
  >
    <form class="source-form" @submit.prevent="submit">
      <header class="dialog-heading">
        <div>
          <h2 id="add-source-title">{{ isEditing ? "编辑文档" : kind === "recipe" ? "添加菜谱" : "添加文档" }}</h2>
        </div>
        <button
          class="dialog-close admin-text-button"
          type="button"
          :disabled="busy === 'upload' || busy === 'ingest'"
          :aria-label="isEditing ? '关闭编辑文档' : kind === 'recipe' ? '关闭添加菜谱' : '关闭添加文档'"
          @click="close"
        >
          <UiIcon name="close" />
        </button>
      </header>
      <div class="dialog-body">
        <div v-if="kind === 'document' && !isEditing" class="input-modes" aria-label="添加方式">
          <button
            type="button"
            :aria-pressed="mode === 'document'"
            :disabled="!!busy"
            @click="selectMode('document')"
          >
            上传文档
          </button>
          <button
            type="button"
            :aria-pressed="mode === 'text'"
            :disabled="!!busy"
            @click="selectMode('text')"
          >
            粘贴文本
          </button>
        </div>
        <fieldset :disabled="!!busy">
          <template v-if="mode === 'document'">
            <label class="file-picker"
              ><UiIcon name="attachment" /><strong>{{
                file ? file.name : "选择一份文档"
              }}</strong
              ><span>TXT、Markdown、CSV、JSON、LOG、PDF、DOCX · 最大 50 MB</span
              ><input
                class="sr-only"
                type="file"
                accept=".txt,.md,.markdown,.csv,.json,.log,.pdf,.docx"
                aria-label="选择文档"
                @change="selectFile"
              />
              <span class="file-picker-action">{{ file ? "重新选择文件" : "选择文件" }}</span>
            </label>
            <label class="admin-field"
              >资料名称<input
                v-model="fileTitle"
                required
                maxlength="500"
                autocomplete="off"
                placeholder="便于在目录中找到这份资料"
            /></label>
            <p class="form-explanation">
              解析正文后切块、向量化，写入当前知识库。
            </p>
          </template>
          <template v-else-if="mode === 'text'">
            <label class="admin-field"
              >资料名称<input
                v-model="textTitle"
                required
                :disabled="busy !== null || (isEditing && !originalDocument)"
                maxlength="512"
                autocomplete="off"
                placeholder="为这段资料起个名字"
            /></label>
            <label class="admin-field"
              >原文<textarea
                v-model="text"
                required
                :disabled="busy !== null || (isEditing && !originalDocument)"
                :maxlength="isEditing ? 1000000 : undefined"
                rows="9"
                placeholder="粘贴需要长期检索的完整原文"
              ></textarea>
            </label>
            <p class="form-explanation">
              {{ isEditing ? "保存成功后，新正文将参与检索。图谱事实与旧证据保留，需单独核对。" : "粘贴的原文直接参与切块和向量入库。" }}
            </p>
          </template>
          <template v-else>
            <label class="admin-field"
              >菜名<input
                v-model="recipeName"
                required
                maxlength="500"
                autocomplete="off"
                placeholder="填写这份记录的菜名"
            /></label>
            <label class="admin-field"
              >原始菜谱 JSON<textarea
                v-model="recipeRecord"
                class="json-input"
                required
                rows="10"
                spellcheck="false"
                placeholder='{"主食材": [["番茄", "2个"]], "辅料": [["鸡蛋", "3个"]], "做法": "1:先炒鸡蛋。2:番茄出汁后合炒。"}'
              ></textarea>
            </label>
            <p class="form-explanation">
              提交一个 JSON
              对象，按当前菜谱字段映射写入图谱，不调用抽取模型。请保留原始字段与真实记录。
            </p>
          </template>
        </fieldset>
        <p v-if="busy === 'load'" class="admin-helper" role="status">正在读取完整原文…</p>
        <p v-if="error" class="admin-error" role="alert">{{ error }}</p>
        <button v-if="isEditing && !originalDocument && busy === null" class="admin-text-button" type="button" @click="loadDocument">重试读取原文</button>
      </div>
      <footer class="dialog-footer">
        <button
          class="admin-secondary"
          type="button"
          :disabled="busy === 'upload' || busy === 'ingest'"
          @click="close"
        >
          取消</button
        ><button
          class="admin-primary"
          type="submit"
          :disabled="!!busy || (isEditing && !originalDocument)"
          :aria-busy="!!busy"
        >
          {{ submitLabel }}
        </button>
      </footer>
    </form>
  </dialog>
</template>

<style scoped>
.add-source-dialog {
  width: min(650px, calc(100vw - 32px));
  max-height: calc(100dvh - 40px);
  margin: auto;
  padding: 0;
  border: 1px solid var(--control-line);
  border-radius: 12px;
  background: var(--surface);
  color: var(--ink);
  box-shadow: 0 24px 80px #2c221e30;
}
.add-source-dialog::backdrop {
  background: #2c221e61;
}
.source-form {
  display: flex;
  flex-direction: column;
  max-height: calc(100dvh - 42px);
}
.dialog-heading {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
  padding: 22px 24px 18px;
  border-bottom: 1px solid var(--line);
}
.dialog-heading h2 {
  margin: 0;
  font: 600 25px/1.4 var(--serif);
}
.dialog-heading p {
  margin: 6px 0 0;
  color: var(--subtle);
  font-size: 14px;
  line-height: 1.6;
}
.dialog-close {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  min-width: 44px;
  min-height: 44px;
}
.dialog-close .ui-icon,
.file-picker .ui-icon {
  width: 22px;
  height: 22px;
}
.dialog-body {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 20px 24px;
}
.input-modes {
  display: flex;
  gap: 4px;
  margin-bottom: 22px;
  padding: 4px;
  border-radius: 7px;
  background: var(--panel);
}
.input-modes button {
  flex: 1;
  min-height: 42px;
  padding: 8px 6px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 14px;
  cursor: pointer;
}
.input-modes button[aria-pressed="true"] {
  background: var(--surface);
  color: var(--clay);
  font-weight: 700;
  box-shadow: 0 1px 3px #2c221e12;
}
.input-modes button:focus-visible,
.file-picker:focus-within {
  outline: 2px solid var(--clay);
  outline-offset: 3px;
}
fieldset {
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}
.file-picker {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 9px;
  margin-bottom: 20px;
  padding: 22px 16px 16px;
  border: 1px dashed var(--control-line);
  border-radius: 7px;
  background: var(--paper);
  text-align: center;
  cursor: pointer;
}
.file-picker strong {
  max-width: 100%;
  font-size: 15px;
  overflow-wrap: anywhere;
}
.file-picker span {
  color: var(--subtle);
  font-size: 13px;
  line-height: 1.6;
}
.file-picker .file-picker-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 44px;
  margin-top: 3px;
  padding: 8px 16px;
  border: 1px solid var(--control-line);
  border-radius: 7px;
  background: var(--surface);
  color: var(--clay);
  font-size: 14px;
}
.admin-field + .admin-field {
  margin-top: 18px;
}
.admin-field input,
.admin-field textarea {
  font-size: 16px;
}
.admin-field textarea {
  min-width: 0;
  width: 100%;
  resize: vertical;
  line-height: 1.7;
}
.json-input {
  font-family: var(--sans);
}
.form-explanation {
  margin: 16px 0 0;
  color: var(--subtle);
  font-size: 13px;
  line-height: 1.8;
}
.dialog-footer {
  display: flex;
  flex-shrink: 0;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px;
  border-top: 1px solid var(--line);
  background: var(--paper);
}
.dialog-footer button {
  min-width: 112px;
}
@media (max-width: 600px) {
  .add-source-dialog {
    width: calc(100vw - 20px);
    max-height: calc(100dvh - 24px);
  }
  .source-form {
    max-height: calc(100dvh - 26px);
  }
  .dialog-heading {
    padding: 18px 18px 14px;
  }
  .dialog-body {
    padding: 18px;
  }
  .dialog-footer {
    padding: 14px 18px max(14px, env(safe-area-inset-bottom));
  }
  .dialog-footer .admin-primary {
    flex: 1;
  }
  .input-modes button {
    font-size: 13px;
  }
}
</style>
