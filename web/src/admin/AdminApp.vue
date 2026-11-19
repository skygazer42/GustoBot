<template>
  <div class="admin-shell app-shell" :class="{ 'is-vector-library': isLibrary }">
    <a class="skip-link" href="#admin-title">跳到管理内容</a>
    <aside class="admin-sidebar">
      <a class="admin-brand" href="/admin.html" @click="externalNavigation"
        ><span class="brand-stamp">陶</span
        ><span><strong>陶陶</strong><small>知识管理</small></span></a
      >
      <div class="admin-space">
        <span>{{ domain?.name ?? page?.domain.name ?? "知识空间" }}</span>
      </div>
      <nav aria-label="后台导航">
        <a
          v-for="item in navigation"
          :key="item.id"
          :href="`/admin.html?view=${item.id}`"
          :aria-current="view === item.id ? 'page' : undefined"
          @click="requestViewLink($event, item.id)"
          ><UiIcon :name="item.icon" /><span>{{ item.label }}</span></a
        >
      </nav>
      <div class="admin-sidebar-bottom">
        <a href="/" @click="externalNavigation"
          ><UiIcon name="back" /><span>回到餐桌手记</span></a
        >
      </div>
    </aside>

    <main class="admin-main">
      <header class="admin-topbar" :class="{ 'library-topbar': isLibrary }">
        <div>
          <h1 id="admin-title" tabindex="-1">{{ currentView.label }}</h1>
          <span v-if="!isLibrary">{{
            page?.domain.name ?? domain?.name ?? "正在读取知识空间"
          }}</span>
        </div>
        <p
          v-if="notice"
          class="admin-topbar-notice"
          role="status"
          :title="notice"
        >
          <span>{{ notice }}</span
          ><button type="button" aria-label="关闭操作提示" @click="notice = ''">
            <UiIcon name="close" />
          </button>
        </p>
        <div class="admin-topbar-actions">
          <button
            v-if="view !== 'test'"
            class="admin-text-button admin-refresh-button"
            type="button"
            aria-label="刷新"
            title="刷新"
            :disabled="isCollection ? listBusy : domainBusy"
            @click="refresh"
          >
            <UiIcon name="refresh" /><span v-if="!isLibrary">刷新</span>
          </button>
          <button
            v-if="isLibrary"
            class="admin-primary"
            type="button"
            @click="openAdd"
          >
            <UiIcon name="new" />添加文档
          </button>
        </div>
      </header>
      <div class="admin-content">
        <p v-if="actionError" class="admin-error" role="alert">
          {{ actionError }}
        </p>

        <section
          v-if="isCollection"
          class="admin-collection"
          :aria-label="isLibrary ? '文档目录' : '做法目录'"
        >
          <div v-if="view === 'recipes'" class="admin-page-heading">
            <h2>做法来源</h2>
            <button
              class="admin-primary"
              type="button"
              @click="openAdd"
            >
              <UiIcon name="new" />添加菜谱
            </button>
          </div>
          <div class="admin-source-box" :aria-busy="listBusy">
            <div class="admin-source-toolbar">
              <div class="admin-filter-tabs" aria-label="来源状态">
                <button
                  v-for="state in visibleStates"
                  :key="state.id"
                  type="button"
                  :aria-pressed="filters.state === state.id"
                  @click="changeState(state.id)"
                >
                  {{ state.label
                  }}<span v-if="page">{{ page.stats[state.stat] }}</span>
                </button>
              </div>
              <div class="admin-source-tools">
                <label class="admin-search"
                  ><UiIcon name="search" /><span class="sr-only"
                    >{{ isLibrary ? "搜索文档名称" : "搜索做法名称" }}</span
                  ><input
                    v-model="filters.q"
                    type="search"
                    maxlength="200"
                    :placeholder="isLibrary ? '搜索文档名称' : '搜索做法名称'" /></label
                >
              </div>
            </div>
            <p v-if="listBusy && page" class="admin-refreshing" role="status">
              正在更新清单…
            </p>
            <div v-if="listError" class="admin-list-error">
              <p class="admin-error" role="alert">{{ listError }}</p>
              <button
                class="admin-secondary"
                type="button"
                @click="loadSources()"
              >
                重试列表
              </button>
            </div>
            <div class="admin-table-wrap">
              <table class="admin-source-table">
                <thead>
                  <tr>
                    <th scope="col">{{ isLibrary ? "文档名称" : "做法名称" }}</th>
                    <th v-if="!isLibrary" scope="col">内容与入库</th>
                    <th scope="col">{{ isLibrary ? "处理状态" : "状态" }}</th>
                    <th v-if="isLibrary" scope="col" class="admin-chunk-count">切片数</th>
                    <th scope="col">最近更新</th>
                    <th scope="col"><span class="sr-only">核对资料</span></th>
                  </tr>
                </thead>
                <tbody v-if="!page && listBusy">
                  <tr
                    v-for="row in 3"
                    :key="row"
                    class="admin-skeleton-row"
                    aria-hidden="true"
                  >
                    <td colspan="5"><span></span></td>
                  </tr>
                </tbody>
                <tbody v-else-if="page">
                  <tr
                    v-for="source in page.items"
                    :key="sourceKey(source)"
                    :class="{
                      'is-selected':
                        selected && sourceKey(selected) === sourceKey(source),
                    }"
                    @click="requestSource(source)"
                  >
                    <td data-label="资料名称">
                      <button
                        class="admin-source-name"
                        type="button"
                        :aria-label="`核对资料：${source.title}`"
                        :aria-pressed="selected !== null && sourceKey(selected) === sourceKey(source)"
                        @click.stop="requestSource(source)"
                      >
                        <span class="admin-file-icon"
                          ><UiIcon
                            :name="
                              source.kind === 'recipe' ? 'book' : 'file'
                            " /></span
                        ><span
                          ><strong>{{ source.title }}</strong></span
                        >
                      </button>
                    </td>
                    <td v-if="!isLibrary" data-label="内容与入库">
                      <span>本体映射</span><small v-if="source.entities !== null"
                        >{{ source.entities }} 个实体 ·
                        <span v-if="source.relations !== null"
                          >{{ source.relations }} 条关系</span
                        ></small
                      >
                    </td>
                    <td class="admin-source-status" data-label="状态">
                      <span class="admin-badge" :class="sourceState(source)">{{
                        stateLabel(source.status)
                      }}</span
                      ><small v-if="source.latest_job?.status === 'failed'" class="admin-warning">{{
                        source.status === "failed" ? source.latest_job.error : "最近一次任务失败"
                      }}</small>
                    </td>
                    <td v-if="isLibrary" class="admin-chunk-count" data-label="切片数">
                      {{ source.chunks ?? "—" }}<span v-if="source.chunks !== null" class="admin-chunk-unit"> 片</span>
                    </td>
                    <td data-label="最近更新" class="admin-time">
                      <time :datetime="source.updated_at">{{ formatAdminDate(source.updated_at) }}</time>
                    </td>
                    <td class="admin-source-chevron">
                      <UiIcon :name="selected && sourceKey(selected) === sourceKey(source) ? 'down' : 'chevron'" />
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div
              v-if="page && !page.items.length && !listBusy && !listError"
              class="admin-empty"
            >
              <UiIcon name="file" />
              <h3>{{ isFiltered ? "没有符合条件的记录" : isLibrary ? "还没有文档" : "还没有菜谱" }}</h3>
              <button
                class="admin-secondary"
                type="button"
                @click="isFiltered ? clearFilters() : openAdd()"
              >
                {{ isFiltered ? "清除筛选" : isLibrary ? "添加文档" : "添加菜谱" }}
              </button>
            </div>
            <footer v-if="page && page.total > page.limit" class="admin-pagination" aria-label="文档分页">
              <span
                >共 {{ page.total }} 份{{ listBusy ? " · 更新中" : "" }}</span
              >
              <div>
                <button
                  class="admin-secondary"
                  type="button"
                  aria-label="上一页"
                  title="上一页"
                  :disabled="listBusy || page.offset === 0"
                  @click="changePage(-1)"
                >
                  <UiIcon name="chevron" class="admin-page-back" /></button
                ><span
                  >{{ Math.floor(page.offset / page.limit) + 1 }} /
                  {{ Math.max(1, Math.ceil(page.total / page.limit)) }}</span
                ><button
                  class="admin-secondary"
                  type="button"
                  aria-label="下一页"
                  title="下一页"
                  :disabled="listBusy || page.offset + page.limit >= page.total"
                  @click="changePage(1)"
                >
                  <UiIcon name="chevron" />
                </button>
              </div>
            </footer>
          </div>
        </section>

        <section
          v-if="view !== 'test' && (selected || detailBusy || detailError)"
          class="admin-review"
          :class="{ 'library-review': isLibrary }"
          aria-label="来源核对"
        >
          <header ref="reviewHeading" tabindex="-1" class="admin-review-heading">
            <span class="admin-file-icon">
              <UiIcon :name="selected?.kind === 'recipe' ? 'book' : 'file'" />
            </span>
            <h2>{{ selected?.title ?? "来源核对" }}</h2>
            <div v-if="selected" class="admin-review-meta">
              <time class="admin-time" :datetime="selected.updated_at">{{ formatAdminDate(selected.updated_at) }} 更新</time>
              <span class="admin-badge" :class="sourceState(selected)">{{ stateLabel(selected.status) }}</span>
            </div>
          </header>
          <div v-if="detailBusy && !detail" class="admin-evidence-pane" role="status">正在读取原文与入库任务…</div>
          <div v-if="detailError" class="admin-evidence-pane">
            <p class="admin-error" role="alert">{{ detailError }}</p>
            <button v-if="requestedSource" class="admin-secondary" type="button" @click="selectSource(requestedSource, false)">
              重试资料详情
            </button>
          </div>
          <template v-if="detail">
            <DocumentReview
              v-if="isLibrary"
              :key="sourceKey(detail.source)"
              :detail="detail"
              :busy="sourceBusy"
              @retry="retrySelected"
              @withdraw="requestWithdrawal"
            >
              <template #actions>
                <button class="admin-text-button" type="button" :disabled="sourceBusy" @click="requestView('ontology')">
                  <UiIcon name="graph" />图谱核对
                </button>
              </template>
            </DocumentReview>
            <div v-else class="admin-evidence-pane">
              <details class="admin-job-history">
                <summary>查看来源原文</summary>
                <pre class="admin-source-text" tabindex="0">{{ detail.text }}</pre>
                <p v-if="detail.text_truncated" class="admin-helper">已显示原文的前 20,000 个字符。</p>
              </details>
              <details v-if="detail.jobs.length" class="admin-job-history">
                <summary>入库任务 · {{ detail.jobs.length }}</summary>
                <ol>
                  <li v-for="job in detail.jobs" :key="job.id">
                    <div>
                      <strong>{{ stateLabel(job.status) }}</strong>
                      <time :datetime="job.updated_at">{{ formatAdminDate(job.updated_at) }}</time>
                    </div>
                    <p v-if="job.error" class="admin-error">{{ job.error }}</p>
                  </li>
                </ol>
              </details>
              <GraphReview
                v-if="domain"
                :key="sourceKey(detail.source)"
                ref="graphReview"
                :source="detail.source"
                :domain="domain"
                @saved="graphSaved"
              />
              <p v-else class="admin-helper">{{ domainError || "正在读取本体定义…" }}</p>
            </div>
          </template>
        </section>

        <section
          v-if="view === 'ontology'"
          class="admin-ontology"
          aria-labelledby="ontology-heading"
        >
          <header class="admin-page-heading">
            <div>
              <h2 id="ontology-heading">当前本体定义 · 只读</h2>
              <p class="admin-helper">
                这里展示当前本体编译出的业务类型和关系约束；完整 OWL / RDFS 与
                SHACL 由资源文件维护，来源映射单独管理。
              </p>
            </div>
          </header>
          <p v-if="domainBusy" role="status">正在读取本体定义…</p>
          <div v-if="domainError">
            <p class="admin-error" role="alert">{{ domainError }}</p>
            <button class="admin-secondary" type="button" @click="loadDomain">
              重试本体读取
            </button>
          </div>
          <template v-if="domain"
            ><div class="admin-ontology-summary">
              <span class="admin-tag">{{ domain.name }}</span
              ><span>版本 {{ domain.version }}</span
              ><span>{{ Object.keys(domain.classes).length }} 类实体</span
              ><span
                >{{ Object.keys(domain.allowed_edges).length }} 类关系</span
              >
            </div>
            <p class="admin-helper">{{ domain.description }}</p>
            <div class="admin-ontology-columns">
              <section>
                <h3>实体类型</h3>
                <details
                  v-for="(definition, symbol) in domain.classes"
                  :key="symbol"
                  class="admin-schema-item"
                >
                  <summary>
                    <strong>{{ definition.label || symbol }}</strong
                    ><span>{{ symbol }}</span>
                  </summary>
                  <p>{{ definition.description }}</p>
                  <p v-if="definition.grain" class="admin-helper">
                    粒度：{{ definition.grain }}
                  </p>
                  <dl>
                    <div
                      v-for="(property, name) in definition.properties"
                      :key="name"
                    >
                      <dt>
                        {{ name }}
                        <small>{{ property.required ? "必填" : "可选" }}</small>
                      </dt>
                      <dd>{{ property.type }} · {{ property.description }}</dd>
                    </div>
                  </dl>
                </details>
              </section>
              <section>
                <h3>允许的关系</h3>
                <article
                  v-for="(definition, symbol) in domain.allowed_edges"
                  :key="symbol"
                  class="admin-schema-item"
                >
                  <h4>{{ symbol }}</h4>
                  <p class="admin-edge-types">
                    {{ definition.domain.join(" / ") }} <UiIcon name="arrow" />
                    {{ definition.range.join(" / ") }}
                  </p>
                  <p>{{ definition.description }}</p>
                </article>
              </section>
            </div>
            <aside v-if="!selected" class="admin-ontology-notes">
              <h3>事实图谱按资料核对</h3>
              <p>
                在来源清单选中资料，可以查看该来源版本实际支持的实体、关系及引用证据。
              </p>
              <button
                class="admin-secondary"
                type="button"
                @click="requestView('library')"
              >
                查看向量知识库
              </button>
            </aside></template
          >
        </section>

        <section v-show="view === 'test'" class="admin-review is-test-view" aria-label="问答测试">
          <QuestionTester :source="selected" />
        </section>
      </div>
    </main>
    <AddSourceDialog
      ref="addDialog"
      :open="addOpen"
      :kind="view === 'recipes' ? 'recipe' : 'document'"
      @close="closeAdd"
      @created="sourceCreated"
    />
    <dialog
      ref="confirmation"
      class="admin-confirm"
      aria-labelledby="admin-confirm-title"
      @cancel.prevent="cancelConfirmation"
    >
      <h2 id="admin-confirm-title">{{ confirmationTitle }}</h2>
      <p>{{ confirmationText }}</p>
      <div>
        <button
          class="admin-secondary"
          type="button"
          @click="cancelConfirmation"
        >
          取消</button
        ><button class="admin-primary" type="button" @click="confirmAction">
          {{ confirmationButton }}
        </button>
      </div>
    </dialog>
  </div>
</template>

<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import UiIcon from "../components/UiIcon.vue";
import AddSourceDialog from "./AddSourceDialog.vue";
import DocumentReview from "./DocumentReview.vue";
import GraphReview from "./GraphReview.vue";
import QuestionTester from "./QuestionTester.vue";
import {
  errorMessage,
  formatAdminDate,
  getDomain,
  isCancelled,
  listSources,
  readSource,
  retrySource,
  sourceState,
  stateLabel,
  withdrawSource,
} from "./api";
import type {
  DomainDefinition,
  IngestionReceipt,
  SourceDetail,
  SourceFilters,
  SourcePage,
  SourceSummary,
} from "./contracts";

const navigation = [
  { id: "library", label: "向量知识库", icon: "file" },
  { id: "recipes", label: "菜谱与做法", icon: "book" },
  { id: "ontology", label: "本体与图谱", icon: "graph" },
  { id: "test", label: "问答测试", icon: "test" },
] as const;
type View = (typeof navigation)[number]["id"];
type SourceIdentity = Pick<SourceSummary, "source_id" | "version">;
const libraryStates = [
  { id: "all", label: "全部文档", stat: "total" },
  { id: "ready", label: "可检索", stat: "ready" },
  { id: "processing", label: "处理中", stat: "processing" },
  { id: "failed", label: "失败", stat: "failed" },
  { id: "withdrawn", label: "已撤回", stat: "withdrawn" },
] as const;
const recipeStates = [
  { id: "all", label: "全部资料", stat: "total" },
  { id: "pending", label: "待处理", stat: "pending" },
  { id: "ready", label: "已就绪", stat: "ready" },
] as const;
function readView(): View {
  return (
    navigation.find(
      (item) => item.id === new URLSearchParams(location.search).get("view"),
    )?.id ?? "library"
  );
}
const view = ref<View>(readView());
const currentView = computed(
  () => navigation.find((item) => item.id === view.value)!,
);
const isLibrary = computed(() => view.value === "library");
const isCollection = computed(() => isLibrary.value || view.value === "recipes");
const visibleStates = computed(() => isLibrary.value ? libraryStates : recipeStates);
const filters = reactive<Omit<SourceFilters, "kind">>({
  q: "",
  state: "all",
  offset: 0,
  limit: 6,
});
const isFiltered = computed(() => Boolean(filters.q.trim()) || filters.state !== "all");
const page = ref<SourcePage | null>(null);
const listBusy = ref(isCollection.value);
const listError = ref("");
const domain = ref<DomainDefinition | null>(null);
const domainBusy = ref(false);
const domainError = ref("");
const selected = ref<SourceSummary | null>(null);
const requestedSource = ref<SourceIdentity | null>(null);
const detail = ref<SourceDetail | null>(null);
const detailBusy = ref(false);
const detailError = ref("");
const sourceBusy = ref(false);
const actionError = ref("");
const notice = ref("");
const addOpen = ref(false);
const addDialog = ref<InstanceType<typeof AddSourceDialog> | null>(null);
const reviewHeading = ref<HTMLElement | null>(null);
const graphReview = ref<InstanceType<typeof GraphReview> | null>(null);
const confirmation = ref<HTMLDialogElement | null>(null);
const confirmationTitle = ref("");
const confirmationText = ref("");
const confirmationButton = ref("");
let pendingAction: (() => void) | null = null;
let listController: AbortController | null = null;
let detailController: AbortController | null = null;
let domainController: AbortController | null = null;
let listEpoch = 0;
let detailEpoch = 0;
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let allowUnload = false;
const navigationBlockedMessage = "正在提交入库操作，请等待结果后再切换资料。";

function sourceKey(source: SourceIdentity): string {
  return JSON.stringify([source.source_id, source.version]);
}

async function loadSources(selectFirstDocument = true): Promise<void> {
  if (!isCollection.value) return;
  clearTimeout(searchTimer);
  listController?.abort();
  const request = new AbortController();
  listController = request;
  const epoch = ++listEpoch;
  listBusy.value = true;
  listError.value = "";
  try {
    const result = await listSources(
      { ...filters, q: filters.q.trim(), kind: isLibrary.value ? "document" : "recipe" },
      request.signal,
    );
    if (epoch !== listEpoch || request.signal.aborted) return;
    if (result.total > 0 && !result.items.length && result.offset > 0) {
      filters.offset =
        Math.floor((result.total - 1) / result.limit) * result.limit;
      return;
    }
    const firstPage = page.value === null;
    page.value = result;
    const current = selected.value;
    if (current) {
      const updated = result.items.find(
        (item) => sourceKey(item) === sourceKey(current),
      );
      if (updated) {
        selected.value = updated;
        if (detail.value) detail.value = { ...detail.value, source: updated };
      }
    } else if (selectFirstDocument && firstPage && isLibrary.value && !isFiltered.value && !requestedSource.value) {
      const firstReady = result.items.find((item) => item.status === "ready");
      const firstDocument = firstReady ?? result.items[0];
      if (firstDocument) {
        selected.value = firstDocument;
        void selectSource(firstDocument, false);
      }
    }
  } catch (failure) {
    if (epoch === listEpoch && !isCancelled(failure))
      listError.value = errorMessage(failure);
  } finally {
    if (epoch === listEpoch) listBusy.value = false;
  }
}

async function loadDomain(): Promise<void> {
  domainController?.abort();
  const request = new AbortController();
  domainController = request;
  domainBusy.value = true;
  domainError.value = "";
  try {
    const result = await getDomain(request.signal);
    if (!request.signal.aborted) domain.value = result;
  } catch (failure) {
    if (!isCancelled(failure)) domainError.value = errorMessage(failure);
  } finally {
    if (!request.signal.aborted) domainBusy.value = false;
  }
}

async function selectSource(
  source: SourceIdentity,
  focusReview: boolean,
): Promise<void> {
  detailController?.abort();
  const request = new AbortController();
  detailController = request;
  const epoch = ++detailEpoch;
  requestedSource.value = source;
  if (detail.value && sourceKey(detail.value.source) !== sourceKey(source)) {
    detail.value = null;
  }
  detailError.value = "";
  detailBusy.value = true;
  try {
    const result = await readSource(source, request.signal);
    if (epoch !== detailEpoch || request.signal.aborted) return;
    selected.value = result.source;
    detail.value = result;
    await nextTick();
    if (focusReview && epoch === detailEpoch) focusMobileReview();
  } catch (failure) {
    if (epoch === detailEpoch && !isCancelled(failure))
      detailError.value = errorMessage(failure);
  } finally {
    if (epoch === detailEpoch) detailBusy.value = false;
  }
}

async function askConfirmation(
  title: string,
  text: string,
  button: string,
  action: () => void,
): Promise<void> {
  confirmationTitle.value = title;
  confirmationText.value = text;
  confirmationButton.value = button;
  pendingAction = action;
  await nextTick();
  confirmation.value?.showModal();
}
function cancelConfirmation(): void {
  pendingAction = null;
  confirmation.value?.close();
}
function confirmAction(): void {
  const action = pendingAction;
  cancelConfirmation();
  action?.();
}
function leaveDraft(action: () => void): void {
  if (sourceBusy.value || addDialog.value?.isSubmitting || graphReview.value?.isWriting) {
    actionError.value = navigationBlockedMessage;
    return;
  }
  if (graphReview.value?.hasUnsavedChanges) {
    void askConfirmation(
      "放弃当前未入库的候选？",
      "切换后会丢弃当前图谱候选。已入库资料和事实会保留。",
      "放弃并继续",
      () => {
        graphReview.value?.discardDraft();
        action();
      },
    );
  } else action();
}
function externalNavigation(event: MouseEvent): void {
  if (
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  )
    return;
  const link = event.currentTarget;
  if (!(link instanceof HTMLAnchorElement)) return;
  const href = link.href;
  event.preventDefault();
  leaveDraft(() => {
    allowUnload = true;
    location.assign(href);
  });
}
function beforeUnload(event: BeforeUnloadEvent): void {
  if (
    !allowUnload &&
    (sourceBusy.value || addDialog.value?.isSubmitting || graphReview.value?.hasUnsavedChanges)
  ) {
    event.preventDefault();
    event.returnValue = "";
  }
}
function focusMobileReview(): void {
  if (window.innerWidth <= 700) {
    reviewHeading.value?.scrollIntoView({ block: "start" });
    reviewHeading.value?.focus({ preventScroll: true });
  }
}
function requestSource(source: SourceSummary): void {
  if (
    selected.value &&
    sourceKey(source) === sourceKey(selected.value) &&
    detail.value
  ) {
    focusMobileReview();
    return;
  }
  leaveDraft(() => {
    selected.value = source;
    void selectSource(source, true);
  });
}
function applyView(next: View, focusTitle = true): void {
  if (view.value === next) return;
  listController?.abort();
  listEpoch++;
  listError.value = "";
  detailController?.abort();
  detailEpoch++;
  detailError.value = "";
  detailBusy.value = false;
  const kind = next === "recipes" ? "recipe" : next === "library" ? "document" : null;
  if (kind) {
    page.value = null;
    listBusy.value = true;
    clearFilters();
    if (selected.value?.kind !== kind) {
      selected.value = null;
      detail.value = null;
      requestedSource.value = null;
    }
  } else {
    listBusy.value = false;
  }
  view.value = next;
  const url = new URL(location.href);
  url.searchParams.set("view", next);
  history.replaceState(null, "", url);
  document.title = `陶陶 · ${currentView.value.label}`;
  if (next !== "test" && selected.value && !detail.value) {
    void selectSource(selected.value, false);
  }
  if (focusTitle) {
    void nextTick(() => {
      window.scrollTo(0, 0);
      document.getElementById("admin-title")?.focus({ preventScroll: true });
    });
  }
}
function requestView(next: View): void {
  if (next !== view.value) leaveDraft(() => applyView(next));
}
function requestViewLink(event: MouseEvent, next: View): void {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  requestView(next);
}
function popState(): void {
  leaveDraft(() => applyView(readView()));
}
function changeState(state: SourceFilters["state"]): void {
  if (filters.state !== state) {
    filters.state = state;
    filters.offset = 0;
  }
}
function changePage(direction: number): void {
  filters.offset = Math.max(0, filters.offset + direction * filters.limit);
}
function clearFilters(): void {
  filters.q = "";
  filters.state = "all";
  filters.offset = 0;
}
async function refresh(): Promise<void> {
  if (view.value === "ontology") {
    await loadDomain();
    return;
  }
  const selectionEpoch = detailEpoch;
  await loadSources();
  if (detailEpoch === selectionEpoch && selected.value && !sourceBusy.value) {
    await selectSource(selected.value, false);
  }
}
function openAdd(): void {
  leaveDraft(() => (addOpen.value = true));
}
function closeAdd(): void {
  addOpen.value = false;
}
async function sourceCreated(receipt: IngestionReceipt): Promise<void> {
  closeAdd();
  const targetView = receipt.kind === "recipe" ? "recipes" : "library";
  applyView(targetView, false);
  const selectionEpoch = detailEpoch;
  clearFilters();
  await nextTick();
  notice.value = receipt.kind === "recipe" ? "菜谱已写入图谱。" : "文档已入库，可检索。";
  await loadSources(false);
  if (
    detailEpoch !== selectionEpoch ||
    view.value !== targetView ||
    sourceBusy.value ||
    graphReview.value?.hasUnsavedChanges
  )
    return;
  const source = { source_id: receipt.source_id, version: receipt.version };
  selected.value = page.value?.items.find((item) => sourceKey(item) === sourceKey(source)) ?? null;
  await selectSource(source, true);
}
async function retrySelected(): Promise<void> {
  if (!detail.value || sourceBusy.value) return;
  const source = detail.value.source;
  const originView = view.value;
  sourceBusy.value = true;
  actionError.value = "";
  try {
    const receipt = await retrySource(source);
    notice.value = `${source.title} 重新入库完成：${stateLabel(receipt.status)}。`;
    await loadSources();
    if (
      view.value === originView &&
      selected.value &&
      sourceKey(selected.value) === sourceKey(source)
    )
      await selectSource(source, false);
  } catch (failure) {
    actionError.value = errorMessage(failure);
    await loadSources();
    if (view.value === originView) await selectSource(source, false);
  } finally {
    sourceBusy.value = false;
  }
}
function requestWithdrawal(): void {
  if (!detail.value || detail.value.source.kind !== "document") return;
  const source = detail.value.source;
  leaveDraft(
    () =>
      void askConfirmation(
        "撤回这份资料的文档检索？",
        "原文和任务历史会保留，后续文档检索不再使用它。已经写入的图谱事实会保留。",
        "撤回文档检索",
        () => void withdrawSelected(source),
      ),
  );
}
async function withdrawSelected(source: SourceSummary): Promise<void> {
  const originView = view.value;
  sourceBusy.value = true;
  actionError.value = "";
  try {
    await withdrawSource(source);
    notice.value = `${source.title} 已撤回文档检索，原文与图谱事实保留。`;
    await loadSources();
    if (
      view.value === originView &&
      selected.value &&
      sourceKey(selected.value) === sourceKey(source)
    )
      await selectSource(source, false);
  } catch (failure) {
    actionError.value = errorMessage(failure);
  } finally {
    sourceBusy.value = false;
  }
}
function graphSaved(): void {
  notice.value = "图谱事实已通过校验并写入。";
  if (isCollection.value) void loadSources();
}

watch(
  () => sourceBusy.value || addDialog.value?.isSubmitting === true || graphReview.value?.isWriting === true,
  (processing) => {
    if (!processing && actionError.value === navigationBlockedMessage)
      actionError.value = "";
  },
);
watch(
  () => [filters.q, filters.state, filters.offset, view.value],
  (current, previous) => {
    clearTimeout(searchTimer);
    if (!isCollection.value) return;
    listController?.abort();
    listEpoch++;
    listBusy.value = true;
    listError.value = "";
    if (current[0] !== previous?.[0]) filters.offset = 0;
    searchTimer = setTimeout(
      () => void loadSources(),
      current[0] !== previous?.[0] ? 250 : 0,
    );
  },
  { immediate: true },
);
onMounted(() => {
  document.title = `陶陶 · ${currentView.value.label}`;
  void loadDomain();
  window.addEventListener("popstate", popState);
  window.addEventListener("beforeunload", beforeUnload);
});
onBeforeUnmount(() => {
  clearTimeout(searchTimer);
  listController?.abort();
  detailController?.abort();
  domainController?.abort();
  listEpoch++;
  detailEpoch++;
  window.removeEventListener("popstate", popState);
  window.removeEventListener("beforeunload", beforeUnload);
});
</script>
