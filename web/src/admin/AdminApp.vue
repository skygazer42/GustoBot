<template>
  <div class="admin-shell app-shell" :class="{ 'is-source-library': isCollection, 'is-recipe-workspace': view === 'recipes', 'is-ontology-workspace': view === 'ontology', 'is-question-workspace': view === 'test' }">
    <a class="skip-link" href="#admin-title">跳到管理内容</a>
    <aside class="admin-sidebar">
      <a class="admin-brand" href="/admin.html" aria-label="陶陶知识管理" @click="externalNavigation">
        <img class="brand-stamp" src="/taotao-mark.png" width="36" height="39" alt="" />
        <span><strong>陶陶</strong><small>知识管理</small></span>
      </a>
      <div class="admin-space">
        <span>{{ domain?.name ?? page?.domain.name ?? "知识空间" }}</span>
      </div>
      <nav aria-label="后台导航">
        <a
          v-for="item in navigation"
          :key="item.id"
          :href="`/admin.html?view=${item.id}`"
          :aria-current="view === item.id ? 'page' : undefined"
          :aria-label="item.label"
          @click="requestViewLink($event, item.id)"
          ><UiIcon :name="item.icon" /><span class="admin-nav-label">{{ item.label }}</span><span class="admin-nav-compact">{{ item.shortLabel }}</span></a
        >
      </nav>
      <div class="admin-sidebar-bottom">
        <a href="/" @click="externalNavigation"
          ><UiIcon name="back" /><span>回到餐桌手记</span></a
        >
      </div>
    </aside>

    <main class="admin-main">
      <header class="admin-topbar">
        <div>
          <h1 id="admin-title" tabindex="-1">{{ currentView.label }}</h1>
          <span v-if="!isCollection && view !== 'conversations'">{{
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
            v-if="view === 'recipes'"
            ref="recipePickerButton"
            class="admin-secondary recipe-picker-trigger"
            type="button"
            aria-label="选择菜谱"
            aria-haspopup="dialog"
            @click="openRecipePicker"
          >
            <UiIcon name="book" /><span>{{ selected?.title ?? '选择菜谱' }}</span><UiIcon name="down" />
          </button>
          <button
            v-if="loginConfigured"
            class="admin-text-button"
            type="button"
            :disabled="signingOut"
            @click="leaveDraft(() => emit('signOut'))"
          >
            {{ signingOut ? "正在退出…" : "退出登录" }}
          </button>
          <button
            v-if="view !== 'test' && view !== 'conversations'"
            class="admin-text-button admin-refresh-button"
            type="button"
            aria-label="刷新"
            title="刷新"
            :disabled="isCollection ? listBusy : domainBusy"
            @click="refresh"
          >
            <UiIcon name="refresh" /><span v-if="!isCollection">刷新</span>
          </button>
          <button
            v-if="isCollection"
            class="admin-primary"
            type="button"
            @click="openAdd"
          >
            <UiIcon name="new" />{{ isLibrary ? "添加文档" : "添加菜谱" }}
          </button>
        </div>
      </header>
      <div class="admin-content" :class="{ 'library-workspace': isLibrary, 'recipe-graph-workspace': view === 'recipes', 'ontology-workspace': view === 'ontology' }">
        <p v-if="actionError || sessionError" class="admin-error" role="alert">
          {{ actionError || sessionError }}
        </p>

        <nav v-if="view === 'ontology'" class="admin-ontology-tabs" aria-label="图谱视图">
          <button type="button" :aria-pressed="ontologyTab === 'graph'" @click="changeOntologyTab('graph')">知识图谱</button>
          <button type="button" :aria-pressed="ontologyTab === 'schema'" @click="changeOntologyTab('schema')">本体图谱</button>
          <button v-if="selected" class="admin-source-review-tab" type="button" :aria-pressed="ontologyTab === 'source'" @click="changeOntologyTab('source')">来源映射核对</button>
        </nav>
        <GraphExplorer
          v-if="view === 'ontology' && ontologyTab === 'graph' && (!domainError || domain)"
          ref="graphExplorer"
          :domain="domain"
          :source="graphSource"
          @all="graphSource = null"
          @sources="requestView('library')"
          @review="requestGraphReview"
        />
        <div v-if="view === 'ontology' && ontologyTab === 'graph' && domainError" class="admin-list-error">
          <p class="admin-error" role="alert">{{ domainError }}</p>
          <button class="admin-secondary" type="button" @click="loadDomain">重试本体读取</button>
        </div>

        <component
          :is="isLibrary ? 'section' : 'dialog'"
          v-if="isCollection"
          ref="sourceDirectory"
          class="admin-collection"
          :class="{ 'recipe-source-picker': view === 'recipes' }"
          :aria-label="isLibrary ? '文档目录' : '选择菜谱'"
        >
          <header v-if="view === 'recipes'" class="recipe-picker-heading">
            <div><h2>选择菜谱</h2><p v-if="page">共 {{ page.stats.total }} 份资料</p></div>
            <button class="admin-text-button" type="button" aria-label="关闭菜谱选择" @click="closeRecipePicker"><UiIcon name="close" /></button>
          </header>
          <div
            class="admin-source-box"
            :class="{ 'is-empty': page && !page.items.length && !listBusy && !listError }"
            :aria-busy="listBusy"
          >
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
              <ul class="admin-document-list" :aria-label="isLibrary ? '文档列表' : '做法列表'">
                <li v-for="source in page?.items ?? []" :key="sourceKey(source)" :class="{ 'admin-document-item': isLibrary }">
                  <button
                    class="admin-source-name admin-document-row"
                    type="button"
                    :aria-label="`核对资料：${source.title}`"
                    :aria-pressed="selected !== null && sourceKey(selected) === sourceKey(source)"
                    @click="requestSource(source)"
                  >
                    <span class="admin-file-icon"><UiIcon :name="source.kind === 'recipe' ? 'book' : 'file'" /></span>
                    <span class="admin-document-copy">
                      <strong :title="source.title">{{ source.title }}</strong>
                      <span class="admin-document-meta">
                        <span class="admin-badge" :class="sourceState(source)">{{ stateLabel(source.status) }}</span>
                        <span v-if="isLibrary" class="admin-document-chunks">{{ source.chunks ?? "—" }}<span v-if="source.chunks !== null"> 片</span></span>
                        <time :datetime="source.updated_at">{{ formatAdminDate(source.updated_at) }}</time>
                      </span>
                      <span v-if="!isLibrary && (source.entities !== null || source.relations !== null)" class="admin-document-meta">
                        <span v-if="source.entities !== null">{{ source.entities }} 个实体</span>
                        <span v-if="source.relations !== null">{{ source.relations }} 条关系</span>
                      </span>
                      <span v-if="!isLibrary" class="recipe-picker-version">版本 {{ source.version.slice(0, 8) }}</span>
                      <span v-if="source.latest_job?.status === 'failed'" class="admin-document-warning">
                        {{ source.status === "failed" ? source.latest_job.error : "最近一次任务失败" }}
                      </span>
                    </span>
                    <UiIcon name="chevron" class="admin-document-chevron" />
                  </button>
                  <button
                    v-if="isLibrary && source.kind === 'document'"
                    class="admin-text-button admin-delete-button admin-document-delete"
                    type="button"
                    :aria-label="`删除文档：${source.title}`"
                    :disabled="sourceBusy || ['pending', 'processing'].includes(source.status) || ['pending', 'processing'].includes(source.latest_job?.status ?? '')"
                    @click="requestDeletion(source)"
                  >删除</button>
                </li>
                <template v-if="!page && listBusy">
                  <li v-for="row in 3" :key="row" class="admin-document-skeleton" aria-hidden="true"><span></span></li>
                </template>
              </ul>
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
            <footer v-if="page && page.total > page.limit" class="admin-pagination" :aria-label="isLibrary ? '文档分页' : '菜谱分页'">
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
        </component>

        <section v-if="view === 'recipes'" class="recipe-main" aria-label="菜谱图谱工作区">
          <template v-if="selected">
            <div v-if="listError" class="recipe-catalog-error" role="alert"><span>{{ listError }}</span><button class="admin-text-button" type="button" @click="loadSources()">重试菜谱目录</button></div>
            <header class="recipe-source-heading">
              <div>
                <div class="recipe-source-title"><h2>{{ selected.title }}</h2><span class="admin-badge" :class="sourceState(selected)">{{ stateLabel(selected.status) }}</span></div>
                <p><time :datetime="selected.updated_at">{{ formatAdminDate(selected.updated_at) }} 更新</time><span>当前来源版本 {{ selected.version.slice(0, 8) }}</span></p>
              </div>
              <nav class="recipe-view-tabs" aria-label="菜谱资料视图">
                <button type="button" :aria-pressed="recipeTab === 'graph'" @click="recipeTab = 'graph'"><UiIcon name="graph" />图谱</button>
                <button type="button" :aria-pressed="recipeTab === 'facts'" @click="recipeTab = 'facts'"><UiIcon name="test" />事实</button>
                <button type="button" :aria-pressed="recipeTab === 'original'" @click="recipeTab = 'original'"><UiIcon name="file" />来源原文</button>
              </nav>
            </header>
            <div v-show="recipeTab === 'graph'" class="recipe-graph-panel">
              <div v-if="domainError" class="admin-list-error"><p class="admin-error" role="alert">{{ domainError }}</p><button class="admin-secondary" type="button" @click="loadDomain">重试本体读取</button></div>
              <GraphExplorer v-if="domain" ref="recipeGraph" variant="recipe" :domain="domain" :source="selected" @review="recipeTab = 'facts'" />
              <p v-else-if="!domainError" class="admin-helper" role="status">正在读取本体定义…</p>
            </div>
            <section v-if="recipeTab !== 'graph'" class="recipe-record-panel" :aria-label="recipeTab === 'facts' ? '菜谱事实核对' : '菜谱来源原文'">
              <p v-if="detailBusy" class="admin-helper" role="status">正在读取来源详情…</p>
              <div v-if="detailError"><p class="admin-error" role="alert">{{ detailError }}</p><button class="admin-secondary" type="button" @click="selectSource(selected, false)">重试资料详情</button></div>
              <template v-if="detail && !detailBusy && !detailError">
                <GraphReview v-if="recipeTab === 'facts' && domain" :key="sourceKey(detail.source)" :source="detail.source" :domain="domain" @browse="recipeTab = 'graph'" />
                <p v-else-if="recipeTab === 'facts'" class="admin-helper">{{ domainError || '正在读取本体定义…' }}</p>
                <template v-else>
                  <h3>来源原文</h3><pre class="admin-source-text" tabindex="0" aria-label="菜谱来源原文">{{ detail.text }}</pre>
                  <p v-if="detail.text_truncated" class="admin-helper">已显示原文的前 20,000 个字符。</p>
                  <details v-if="detail.jobs.length" class="admin-job-history"><summary>入库任务 · {{ detail.jobs.length }}</summary><ol><li v-for="job in detail.jobs" :key="job.id"><div><strong>{{ stateLabel(job.status) }}</strong><time :datetime="job.updated_at">{{ formatAdminDate(job.updated_at) }}</time></div><p v-if="job.error" class="admin-error">{{ job.error }}</p></li></ol></details>
                </template>
              </template>
            </section>
          </template>
          <div v-else class="recipe-workspace-empty">
            <p v-if="listBusy" role="status">正在读取菜谱目录…</p>
            <template v-else-if="listError"><p class="admin-error" role="alert">{{ listError }}</p><button type="button" class="admin-secondary" @click="loadSources()">重试菜谱目录</button></template>
            <template v-else><UiIcon name="book" /><h2>{{ page?.stats.total ? '选择一份菜谱' : '还没有菜谱' }}</h2><p>选择来源后，查看这份资料已入库的实体、关系与原文依据。</p><button class="admin-primary" type="button" @click="page?.stats.total ? openRecipePicker() : openAdd()">{{ page?.stats.total ? '选择菜谱' : '添加菜谱' }}</button></template>
          </div>
        </section>

        <section
          v-if="(isLibrary || (view === 'ontology' && ontologyTab === 'source')) && (selected || detailBusy || detailError)"
          class="admin-review"
          :class="{ 'library-review': isCollection }"
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
              @delete="requestDeletion"
              @edit="openEdit"
            >
              <template #actions>
                <button class="admin-text-button" type="button" :disabled="sourceBusy" @click="requestGraphReview">
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
                @browse="browseSourceGraph"
              />
              <p v-else class="admin-helper">{{ domainError || "正在读取本体定义…" }}</p>
            </div>
          </template>
        </section>

        <section v-else-if="isLibrary" class="admin-review library-review library-review-empty" aria-label="来源核对">
          <UiIcon :name="isLibrary ? 'file' : 'book'" />
          <h2>{{ page?.items.length ? (isLibrary ? "选择一份文档" : "选择一份菜谱") : (isLibrary ? "文档阅读区" : "菜谱详情区") }}</h2>
          <p v-if="page?.items.length">{{ isLibrary ? "在目录中选择文档，查看原文切片与入库记录。" : "在目录中选择菜谱，核对已入库的实体、关系与原文。" }}</p>
          <p v-else-if="isFiltered">调整目录筛选后，选择资料查看内容。</p>
          <p v-else>{{ isLibrary ? "完成文档入库后，这里会显示原文切片与入库记录。" : "添加菜谱后，这里会显示来源记录与图谱映射。" }}</p>
        </section>

        <section v-if="view === 'ontology' && ontologyTab === 'schema'" aria-label="本体图谱">
          <p v-if="domainBusy" role="status">正在读取本体定义…</p>
          <div v-if="domainError">
            <p class="admin-error" role="alert">{{ domainError }}</p>
            <button class="admin-secondary" type="button" @click="loadDomain">重试本体读取</button>
          </div>
          <OntologyGraph v-if="domain" :domain="domain" />
        </section>

        <section v-show="view === 'test'" class="admin-review is-test-view" aria-label="问答测试">
          <QuestionTester :source="selected" />
        </section>
        <ConversationHistory v-if="view === 'conversations'" />
      </div>
    </main>
    <AddSourceDialog
      ref="addDialog"
      :open="addOpen"
      :kind="view === 'recipes' ? 'recipe' : 'document'"
      :source="editingSource"
      @close="closeAdd"
      @created="sourceCreated"
    />
    <dialog
      ref="confirmation"
      class="admin-confirm"
      aria-labelledby="admin-confirm-title"
      aria-describedby="admin-confirm-description"
      @cancel.prevent="cancelConfirmation"
    >
      <h2 id="admin-confirm-title">{{ confirmationTitle }}</h2>
      <p id="admin-confirm-description">{{ confirmationText }}</p>
      <div>
        <button
          class="admin-secondary"
          type="button"
          @click="cancelConfirmation"
        >
          取消</button
        ><button class="admin-primary" :class="{ 'admin-danger': confirmationDanger }" type="button" @click="confirmAction">
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
import GraphExplorer from "./GraphExplorer.vue";
import OntologyGraph from "./OntologyGraph.vue";
import QuestionTester from "./QuestionTester.vue";
import ConversationHistory from "./ConversationHistory.vue";
import {
  deleteSource,
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

defineProps<{
  loginConfigured: boolean;
  signingOut: boolean;
  sessionError: string;
}>();
const emit = defineEmits<{ signOut: [] }>();

const navigation = [
  { id: "library", label: "向量知识库", shortLabel: "知识库", icon: "file" },
  { id: "recipes", label: "菜谱与做法", shortLabel: "菜谱", icon: "book" },
  { id: "ontology", label: "本体与图谱", shortLabel: "图谱", icon: "graph" },
  { id: "test", label: "问答测试", shortLabel: "问答", icon: "test" },
  { id: "conversations", label: "对话记录", shortLabel: "记录", icon: "clock" },
] as const;
type View = (typeof navigation)[number]["id"];
type SourceIdentity = Pick<SourceSummary, "source_id" | "version">;
const libraryStates = [
  { id: "all", label: "全部文档", stat: "total" },
  { id: "ready", label: "可检索", stat: "ready" },
  { id: "processing", label: "处理中", stat: "processing" },
  { id: "failed", label: "失败", stat: "failed" },
  { id: "withdrawn", label: stateLabel("withdrawn"), stat: "withdrawn" },
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
const editingSource = ref<SourceIdentity | null>(null);
const addDialog = ref<InstanceType<typeof AddSourceDialog> | null>(null);
const reviewHeading = ref<HTMLElement | null>(null);
const graphReview = ref<InstanceType<typeof GraphReview> | null>(null);
const graphExplorer = ref<InstanceType<typeof GraphExplorer> | null>(null);
const recipeGraph = ref<InstanceType<typeof GraphExplorer> | null>(null);
const recipeTab = ref<"graph" | "facts" | "original">("graph");
const sourceDirectory = ref<HTMLElement | null>(null);
const recipePickerButton = ref<HTMLButtonElement | null>(null);
const ontologyTab = ref<"graph" | "source" | "schema">("graph");
const graphSource = ref<SourceSummary | null>(null);
const confirmation = ref<HTMLDialogElement | null>(null);
const confirmationTitle = ref("");
const confirmationText = ref("");
const confirmationButton = ref("");
const confirmationDanger = ref(false);
let pendingAction: (() => void) | null = null;
let listController: AbortController | null = null;
let detailController: AbortController | null = null;
let domainController: AbortController | null = null;
let listEpoch = 0;
let detailEpoch = 0;
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let allowUnload = false;
const navigationBlockedMessage = "正在处理资料，请等待结果后再切换。";

function sourceKey(source: SourceIdentity): string {
  return JSON.stringify([source.source_id, source.version]);
}

async function loadSources(selectFirstSource = true): Promise<void> {
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
    if (!result.items.length && result.offset > 0) {
      filters.offset =
        result.total > 0 ? Math.floor((result.total - 1) / result.limit) * result.limit : 0;
      return;
    }
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
    } else if (selectFirstSource && !requestedSource.value) {
      const firstReady = result.items.find((item) => item.status === "ready");
      const firstSource = firstReady ?? result.items[0];
      if (firstSource) {
        selected.value = firstSource;
        void selectSource(firstSource, false);
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
  danger = false,
): Promise<void> {
  confirmationTitle.value = title;
  confirmationText.value = text;
  confirmationButton.value = button;
  confirmationDanger.value = danger;
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
  if (addDialog.value?.hasUnsavedChanges) {
    void askConfirmation(
      "放弃文档修改？",
      "尚未保存的正文与名称修改将丢失，原文和现有检索保持不变。",
      "放弃修改",
      () => {
        addOpen.value = false;
        editingSource.value = null;
        action();
      },
    );
  } else if (graphReview.value?.hasUnsavedChanges) {
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
    (sourceBusy.value || addDialog.value?.isSubmitting || addDialog.value?.hasUnsavedChanges || graphReview.value?.hasUnsavedChanges)
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
    closeRecipePicker();
    focusMobileReview();
    return;
  }
  leaveDraft(() => {
    selected.value = source;
    closeRecipePicker();
    void selectSource(source, true);
  });
}
function openRecipePicker(): void {
  leaveDraft(() => {
    if (sourceDirectory.value instanceof HTMLDialogElement) sourceDirectory.value.showModal();
  });
}
function closeRecipePicker(): void {
  if (sourceDirectory.value instanceof HTMLDialogElement && sourceDirectory.value.open) {
    sourceDirectory.value.close();
    recipePickerButton.value?.focus();
  }
}
function applyView(next: View, focusTitle = true): void {
  if (view.value === next) return;
  closeRecipePicker();
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
  if (next !== "conversations" && !domain.value && !domainBusy.value) void loadDomain();
  if (next === "recipes") recipeTab.value = "graph";
  const url = new URL(location.href);
  url.searchParams.set("view", next);
  history.replaceState(null, "", url);
  document.title = `陶陶 · ${currentView.value.label}`;
  if (next !== "test" && next !== "conversations" && selected.value && !detail.value) {
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
  if (next === view.value && next !== "ontology") return;
  leaveDraft(() => {
    if (next === "ontology") {
      ontologyTab.value = "graph";
      graphSource.value = null;
    }
    applyView(next);
  });
}
function changeOntologyTab(next: "graph" | "source" | "schema"): void {
  if (next !== ontologyTab.value) leaveDraft(() => { ontologyTab.value = next; });
}
function requestGraphReview(): void {
  leaveDraft(() => {
    ontologyTab.value = "source";
    applyView("ontology");
  });
}
function browseSourceGraph(): void {
  leaveDraft(() => {
    graphSource.value = selected.value;
    ontologyTab.value = "graph";
    applyView("ontology");
  });
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
    await graphExplorer.value?.reload();
    return;
  }
  const selectionEpoch = detailEpoch;
  await loadSources();
  if (detailEpoch === selectionEpoch && selected.value && !sourceBusy.value) {
    await selectSource(selected.value, false);
  }
  if (view.value === "recipes") await recipeGraph.value?.reload();
}
function openAdd(): void {
  leaveDraft(() => {
    editingSource.value = null;
    addOpen.value = true;
  });
}
function openEdit(): void {
  if (!detail.value || detail.value.source.kind !== "document") return;
  const source = detail.value.source;
  leaveDraft(() => {
    editingSource.value = { source_id: source.source_id, version: source.version };
    addOpen.value = true;
  });
}
function closeAdd(): void {
  if (editingSource.value !== null && addDialog.value?.hasUnsavedChanges) {
    void askConfirmation("放弃文档修改？", "尚未保存的正文与名称修改将丢失，原文和现有检索保持不变。", "放弃修改", () => {
      addOpen.value = false;
      editingSource.value = null;
    });
    return;
  }
  addOpen.value = false;
  editingSource.value = null;
}
async function sourceCreated(receipt: IngestionReceipt): Promise<void> {
  const edited = editingSource.value !== null;
  closeAdd();
  const targetView = receipt.kind === "recipe" ? "recipes" : "library";
  applyView(targetView, false);
  if (receipt.kind === "recipe") recipeTab.value = "graph";
  const selectionEpoch = detailEpoch;
  clearFilters();
  await nextTick();
  notice.value = edited ? "文档已更新并可检索，图谱事实与旧证据保留，请单独核对。" : receipt.kind === "recipe" ? "菜谱已写入图谱。" : "文档已入库，可检索。";
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
function requestDeletion(source: SourceSummary | null = detail.value?.source ?? null): void {
  if (source === null || source.kind !== "document") return;
  leaveDraft(() => void askConfirmation(
    "删除文档记录？",
    `“${source.title}”（${formatAdminDate(source.created_at)} 入库）在确认时已有的全部版本、入库任务和向量切片将被删除，文档记录无法恢复。已发布的图谱事实与证据、独立上传的文件会保留。`,
    "确认删除",
    () => void deleteSelected(source),
    true,
  ));
}
async function deleteSelected(source: SourceSummary): Promise<void> {
  if (sourceBusy.value) return;
  sourceBusy.value = true;
  actionError.value = "";
  notice.value = "";
  listController?.abort();
  listEpoch++;
  detailController?.abort();
  detailEpoch++;
  detailBusy.value = false;
  try {
    await deleteSource(source);
    selected.value = null;
    detail.value = null;
    requestedSource.value = null;
    detailError.value = "";
    notice.value = `${source.title} 的文档记录已删除，已发布图谱与独立上传文件保留。`;
    page.value = null;
    await loadSources();
  } catch (failure) {
    actionError.value = errorMessage(failure);
    await loadSources(false);
    const currentSource = page.value?.items.find((item) => item.source_id === source.source_id);
    selected.value = currentSource ?? null;
    detail.value = null;
    requestedSource.value = null;
    detailError.value = "";
    if (currentSource) await selectSource(currentSource, false);
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
  if (view.value !== "conversations") void loadDomain();
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
