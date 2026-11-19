<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import UiIcon from "../components/UiIcon.vue";
import {
  errorMessage,
  extractGraph,
  isCancelled,
  parseProperties,
  saveGraph,
  sourceFacts,
  validateGraph,
} from "./api";
import type {
  DomainDefinition,
  FactResult,
  GraphDraft,
  KnowledgeGraph,
  Properties,
  SourceSummary,
} from "./contracts";

const props = defineProps<{
  source: SourceSummary;
  domain: DomainDefinition | null;
}>();
const emit = defineEmits<{ saved: [] }>();

const facts = ref<FactResult | null>(null);
const factsLoading = ref(false);
const factsError = ref("");
const draft = ref<GraphDraft | null>(null);
const entityProperties = ref<Record<string, string>>({});
const relationProperties = ref<Record<string, string>>({});
const expandedItem = ref<string | null>(null);
const validationChecked = ref(false);
const busy = ref<"extract" | "validate" | "save" | null>(null);
const operationError = ref("");
const notice = ref("");
let factsController: AbortController | null = null;
let operationController: AbortController | null = null;

const domainMatches = computed(
  () =>
    props.domain !== null &&
    props.source.domain_id === props.domain.id &&
    props.source.ontology_version === props.domain.version,
);
const canEdit = computed(
  () =>
    props.source.kind === "document" &&
    props.source.status !== "withdrawn" &&
    domainMatches.value,
);
const canSave = computed(
  () =>
    canEdit.value &&
    validationChecked.value &&
    draft.value?.validation.valid === true &&
    !busy.value,
);
const hasUnsavedChanges = computed(
  () => draft.value !== null || busy.value !== null,
);
const visibleEntities = computed(
  () => facts.value?.entities.slice(0, 50) ?? [],
);
const visibleRelations = computed(
  () => facts.value?.relations.slice(0, 50) ?? [],
);
const factsTruncated = computed(
  () =>
    facts.value !== null &&
    (facts.value.truncated ||
      facts.value.entities.length > 50 ||
      facts.value.relations.length > 50),
);
const unavailableReason = computed(() => {
  if (props.source.kind !== "document")
    return "只有文档资料可以从原文抽取图谱。";
  if (props.source.status === "withdrawn")
    return "这份文档已撤回，已写入的图谱仍保留。";
  if (!props.domain) return "当前类型规则尚未加载，暂时无法抽取或保存。";
  if (!domainMatches.value)
    return "这份资料使用的本体版本与当前知识空间不同，无法在此抽取或保存。";
  return "";
});

const isWriting = computed(() => busy.value === "save");
defineExpose({ hasUnsavedChanges, isWriting, discardDraft });

onMounted(() => {
  void loadFacts();
});
onBeforeUnmount(() => {
  factsController?.abort();
  operationController?.abort();
});

async function loadFacts(): Promise<void> {
  factsController?.abort();
  const controller = new AbortController();
  factsController = controller;
  factsLoading.value = true;
  factsError.value = "";
  try {
    const result = await sourceFacts(props.source, controller.signal);
    if (!controller.signal.aborted) facts.value = result;
  } catch (reason) {
    if (!controller.signal.aborted && !isCancelled(reason))
      factsError.value = errorMessage(reason);
  } finally {
    if (!controller.signal.aborted) factsLoading.value = false;
  }
}

function setDraft(result: GraphDraft): void {
  draft.value = result;
  entityProperties.value = Object.fromEntries(
    result.graph.entities.map((entity) => [
      entity.id,
      JSON.stringify(entity.properties, null, 2),
    ]),
  );
  relationProperties.value = Object.fromEntries(
    result.graph.relations.map((relation) => [
      relation.id,
      JSON.stringify(relation.properties, null, 2),
    ]),
  );
}

function invalidateValidation(): void {
  if (!draft.value) return;
  validationChecked.value = false;
  draft.value.validation = { valid: false, errors: [] };
  operationError.value = "";
}

function parsePropertyInput(value: string, name: string): Properties {
  try {
    return parseProperties(value);
  } catch (reason) {
    throw new Error(`${name}的属性：${errorMessage(reason)}`);
  }
}

function editedGraph(): KnowledgeGraph {
  if (!draft.value) throw new Error("请先抽取候选。");
  return {
    ...draft.value.graph,
    entities: draft.value.graph.entities.map((entity) => ({
      ...entity,
      properties: parsePropertyInput(
        entityProperties.value[entity.id],
        `实体“${entity.name}”`,
      ),
    })),
    relations: draft.value.graph.relations.map((relation) => ({
      ...relation,
      properties: parsePropertyInput(
        relationProperties.value[relation.id],
        `关系“${relation.type}”`,
      ),
    })),
  };
}

function entityName(id: string, graph: KnowledgeGraph | null): string {
  return graph?.entities.find((entity) => entity.id === id)?.name ?? id;
}

function typeLabel(type: string): string {
  return props.domain?.classes[type]?.label || type;
}

function toggleItem(key: string): void {
  expandedItem.value = expandedItem.value === key ? null : key;
}

function discardDraft(): void {
  if (busy.value === "save") return;
  operationController?.abort();
  busy.value = null;
  draft.value = null;
  expandedItem.value = null;
  validationChecked.value = false;
  entityProperties.value = {};
  relationProperties.value = {};
  operationError.value = "";
}

async function extract(): Promise<void> {
  if (!canEdit.value || busy.value || draft.value) return;
  const controller = new AbortController();
  operationController = controller;
  busy.value = "extract";
  operationError.value = "";
  notice.value = "";
  try {
    const result = await extractGraph(props.source, controller.signal);
    if (controller.signal.aborted) return;
    setDraft(result);
    validationChecked.value = false;
  } catch (reason) {
    if (!controller.signal.aborted && !isCancelled(reason))
      operationError.value = errorMessage(reason);
  } finally {
    if (!controller.signal.aborted) busy.value = null;
  }
}

async function validate(): Promise<void> {
  if (!canEdit.value || !draft.value || busy.value) return;
  const controller = new AbortController();
  operationController = controller;
  busy.value = "validate";
  operationError.value = "";
  validationChecked.value = false;
  try {
    const result = await validateGraph(
      props.source,
      editedGraph(),
      controller.signal,
    );
    if (controller.signal.aborted) return;
    setDraft(result);
    validationChecked.value = true;
  } catch (reason) {
    if (!controller.signal.aborted && !isCancelled(reason))
      operationError.value = errorMessage(reason);
  } finally {
    if (!controller.signal.aborted) busy.value = null;
  }
}

async function save(): Promise<void> {
  if (!canSave.value || !draft.value) return;
  const controller = new AbortController();
  operationController = controller;
  busy.value = "save";
  operationError.value = "";
  try {
    const result = await saveGraph(
      props.source,
      draft.value.graph,
      controller.signal,
    );
    if (controller.signal.aborted) return;
    draft.value = null;
    expandedItem.value = null;
    entityProperties.value = {};
    relationProperties.value = {};
    validationChecked.value = false;
    notice.value = `图谱已写入：${result.entities} 个实体、${result.relations} 条关系。`;
    await loadFacts();
    if (!controller.signal.aborted) emit("saved");
  } catch (reason) {
    if (!controller.signal.aborted && !isCancelled(reason))
      operationError.value = errorMessage(reason);
  } finally {
    if (!controller.signal.aborted) busy.value = null;
  }
}
</script>

<template>
  <section class="graph-review" aria-labelledby="graph-review-title">
    <header class="graph-heading">
      <div>
        <h3 id="graph-review-title">图谱核对</h3>
        <p>
          {{
            source.kind === "recipe"
              ? "查看这份菜谱按字段映射写入的真实记录。"
              : "核对实体、关系与原文依据，再确认写入。"
          }}
        </p>
      </div>
      <button
        v-if="source.kind === 'document' && !draft"
        class="admin-secondary"
        type="button"
        :disabled="!canEdit || !!busy"
        :aria-busy="busy === 'extract'"
        @click="extract"
      >
        <UiIcon name="new" />{{
          busy === "extract" ? "正在抽取候选…" : "抽取图谱候选"
        }}
      </button>
    </header>
    <p v-if="unavailableReason" class="availability-note">
      {{ unavailableReason }}
    </p>
    <p v-if="operationError" class="admin-error" role="alert">
      {{ operationError }}
    </p>
    <p v-if="notice" class="admin-notice" role="status">{{ notice }}</p>

    <section
      v-if="draft"
      class="candidate-panel"
      aria-labelledby="candidate-title"
      :aria-busy="!!busy"
    >
      <header class="candidate-heading">
        <div>
          <h4 id="candidate-title">待核对候选 <span>尚未入库</span></h4>
          <p>
            {{ draft.graph.entities.length }} 个实体 ·
            {{ draft.graph.relations.length }} 条关系
          </p>
        </div>
        <button
          class="admin-text-button"
          type="button"
          :disabled="!!busy"
          @click="discardDraft"
        >
          放弃候选
        </button>
      </header>
      <p class="candidate-intro">
        展开一项核对类型和属性。校验与写入沿用这份候选，不会再次调用抽取模型。
      </p>
      <fieldset class="candidate-fields" :disabled="!!busy || !canEdit">
        <div class="candidate-scroll">
          <h5>实体</h5>
          <p v-if="!draft.graph.entities.length" class="small-empty">
            本次未抽取到实体。
          </p>
          <details
            v-for="entity in draft.graph.entities"
            :key="entity.id"
            class="candidate-item"
            :open="expandedItem === `entity:${entity.id}`"
          >
            <summary @click.prevent="toggleItem(`entity:${entity.id}`)">
              <span class="item-name">{{ entity.name || "未命名实体" }}</span
              ><span class="item-type">{{ typeLabel(entity.type) }}</span
              ><UiIcon name="down" />
            </summary>
            <div
              v-if="expandedItem === `entity:${entity.id}`"
              class="item-editor"
            >
              <p class="record-id">
                实体 ID <code>{{ entity.id }}</code>
              </p>
              <div class="editor-row">
                <label class="admin-field"
                  >名称<input
                    v-model="entity.name"
                    required
                    @input="invalidateValidation" /></label
                ><label class="admin-field"
                  >类型<select
                    v-model="entity.type"
                    @change="invalidateValidation"
                  >
                    <option
                      v-if="!domain?.classes[entity.type]"
                      :value="entity.type"
                    >
                      {{ entity.type }}（不在当前类型中）
                    </option>
                    <option
                      v-for="(definition, type) in domain?.classes"
                      :key="type"
                      :value="type"
                    >
                      {{ definition.label }} · {{ type }}
                    </option>
                  </select></label
                >
              </div>
              <label class="admin-field properties-field"
                >属性 JSON<textarea
                  v-model="entityProperties[entity.id]"
                  rows="4"
                  spellcheck="false"
                  @input="invalidateValidation"
                ></textarea>
              </label>
              <details class="evidence">
                <summary>
                  原文依据 · {{ entity.evidence.length }} 处（只读）
                </summary>
                <div
                  v-for="(evidence, index) in entity.evidence"
                  :key="index"
                  class="evidence-entry"
                >
                  <span>来源 {{ evidence.source_id }}</span>
                  <blockquote>{{ evidence.quote }}</blockquote>
                </div>
                <p v-if="!entity.evidence.length">
                  候选没有原文依据，需通过来源校验后才能写入。
                </p>
              </details>
            </div>
          </details>
          <h5>关系</h5>
          <p v-if="!draft.graph.relations.length" class="small-empty">
            本次未抽取到关系。
          </p>
          <details
            v-for="relation in draft.graph.relations"
            :key="relation.id"
            class="candidate-item"
            :open="expandedItem === `relation:${relation.id}`"
          >
            <summary @click.prevent="toggleItem(`relation:${relation.id}`)">
              <span class="item-name"
                >{{ entityName(relation.source_id, draft.graph) }} →
                {{ entityName(relation.target_id, draft.graph) }}</span
              ><span class="item-type">{{ relation.type }}</span
              ><UiIcon name="down" />
            </summary>
            <div
              v-if="expandedItem === `relation:${relation.id}`"
              class="item-editor"
            >
              <p class="record-id">
                关系 ID <code>{{ relation.id }}</code>
              </p>
              <label class="admin-field"
                >关系类型<select
                  v-model="relation.type"
                  @change="invalidateValidation"
                >
                  <option
                    v-if="!domain?.allowed_edges[relation.type]"
                    :value="relation.type"
                  >
                    {{ relation.type }}（不在当前关系中）
                  </option>
                  <option
                    v-for="(definition, type) in domain?.allowed_edges"
                    :key="type"
                    :value="type"
                  >
                    {{ type }} · {{ definition.description }}
                  </option>
                </select></label
              >
              <div class="editor-row endpoint-fields">
                <label class="admin-field"
                  >起点实体<select
                    v-model="relation.source_id"
                    @change="invalidateValidation"
                  >
                    <option
                      v-if="
                        !draft.graph.entities.some(
                          (entity) => entity.id === relation.source_id,
                        )
                      "
                      :value="relation.source_id"
                    >
                      {{ relation.source_id }}（未找到）
                    </option>
                    <option
                      v-for="entity in draft.graph.entities"
                      :key="entity.id"
                      :value="entity.id"
                    >
                      {{ entity.name }} · {{ typeLabel(entity.type) }}
                    </option>
                  </select></label
                ><label class="admin-field"
                  >终点实体<select
                    v-model="relation.target_id"
                    @change="invalidateValidation"
                  >
                    <option
                      v-if="
                        !draft.graph.entities.some(
                          (entity) => entity.id === relation.target_id,
                        )
                      "
                      :value="relation.target_id"
                    >
                      {{ relation.target_id }}（未找到）
                    </option>
                    <option
                      v-for="entity in draft.graph.entities"
                      :key="entity.id"
                      :value="entity.id"
                    >
                      {{ entity.name }} · {{ typeLabel(entity.type) }}
                    </option>
                  </select></label
                >
              </div>
              <label class="admin-field properties-field"
                >属性 JSON<textarea
                  v-model="relationProperties[relation.id]"
                  rows="4"
                  spellcheck="false"
                  @input="invalidateValidation"
                ></textarea>
              </label>
              <details class="evidence">
                <summary>
                  原文依据 · {{ relation.evidence.length }} 处（只读）
                </summary>
                <div
                  v-for="(evidence, index) in relation.evidence"
                  :key="index"
                  class="evidence-entry"
                >
                  <span>来源 {{ evidence.source_id }}</span>
                  <blockquote>{{ evidence.quote }}</blockquote>
                </div>
                <p v-if="!relation.evidence.length">
                  候选没有原文依据，需通过来源校验后才能写入。
                </p>
              </details>
            </div>
          </details>
          <details class="candidate-source">
            <summary>候选绑定的来源原文（只读）</summary>
            <div v-for="sourceText in draft.graph.sources" :key="sourceText.id">
              <p class="record-id">
                来源 <code>{{ sourceText.id }}</code>
              </p>
              <p v-if="sourceText.uri" class="source-uri">
                {{ sourceText.uri }}
              </p>
              <pre>{{ sourceText.text }}</pre>
            </div>
          </details>
        </div>
      </fieldset>
      <div class="candidate-validation" aria-live="polite">
        <p
          :class="{
            'validation-success': validationChecked && draft.validation.valid,
          }"
        >
          <UiIcon
            v-if="validationChecked && draft.validation.valid"
            name="check"
          />{{
            validationChecked
              ? draft.validation.valid
                ? "校验通过，可以确认写入"
                : "校验未通过，请修正后再校验"
              : "核对候选后，请先校验再确认写入"
          }}
        </p>
        <ul v-if="draft.validation.errors.length">
          <li v-for="(message, index) in draft.validation.errors" :key="index">
            {{ message }}
          </li>
        </ul>
      </div>
      <footer class="candidate-footer">
        <span>原文、证据和记录 ID 保持只读。</span>
        <div>
          <button
            class="admin-secondary"
            type="button"
            :disabled="!!busy || !canEdit"
            :aria-busy="busy === 'validate'"
            @click="validate"
          >
            {{ busy === "validate" ? "正在校验…" : "校验候选" }}</button
          ><button
            class="admin-primary"
            type="button"
            :disabled="!canSave"
            :aria-busy="busy === 'save'"
            @click="save"
          >
            {{ busy === "save" ? "正在写入…" : "确认写入图谱" }}
          </button>
        </div>
      </footer>
    </section>

    <details class="saved-facts" :open="!draft">
      <summary>
        <span>已入库图谱</span
        ><span v-if="facts" class="facts-count"
          >{{ facts.entities.length }} 个实体 ·
          {{ facts.relations.length }} 条关系</span
        >
      </summary>
      <div class="facts-body" :aria-busy="factsLoading">
        <div class="facts-toolbar">
          <span>当前资料版本的实际记录</span
          ><button
            class="admin-text-button"
            type="button"
            :disabled="factsLoading || !!busy"
            @click="loadFacts"
          >
            {{ factsLoading ? "正在读取…" : "刷新图谱" }}
          </button>
        </div>
        <div v-if="factsError" class="admin-error" role="alert">
          <p>{{ factsError }}</p>
          <button
            class="admin-secondary"
            type="button"
            :disabled="factsLoading"
            @click="loadFacts"
          >
            重新读取图谱
          </button>
          <p v-if="facts" class="retained-note">以下保留上次读取结果。</p>
        </div>
        <div v-if="factsLoading && !facts" class="facts-loading" role="status">
          <p>正在读取图谱记录…</p>
          <div aria-hidden="true"></div>
          <div aria-hidden="true"></div>
        </div>
        <template v-else-if="facts">
          <p v-if="factsTruncated" class="truncated-note">
            记录较多，当前结果已截断。实体与关系各最多显示 50 条。
          </p>
          <p
            v-if="!facts.entities.length && !facts.relations.length"
            class="facts-empty"
          >
            这份资料还没有已入库图谱。{{
              canEdit ? "可从原文抽取候选，核对后再写入。" : ""
            }}
          </p>
          <div v-else class="fact-columns">
            <section>
              <h5>
                实体 <span>{{ facts.entities.length }}</span>
              </h5>
              <p v-if="!visibleEntities.length" class="small-empty">
                没有实体记录。
              </p>
              <details
                v-for="entity in visibleEntities"
                :key="entity.id"
                class="fact-item"
              >
                <summary>
                  <span class="item-name">{{ entity.name }}</span
                  ><span class="item-type">{{ typeLabel(entity.type) }}</span>
                </summary>
                <div class="fact-detail">
                  <p class="record-id">
                    实体 ID <code>{{ entity.id }}</code>
                  </p>
                  <p v-if="entity.aliases.length" class="aliases">
                    别名：{{ entity.aliases.join("、") }}
                  </p>
                  <dl v-if="Object.keys(entity.properties).length">
                    <template
                      v-for="(value, key) in entity.properties"
                      :key="key"
                      ><dt>{{ key }}</dt>
                      <dd>{{ value }}</dd></template
                    >
                  </dl>
                  <p v-else class="small-empty">没有记录额外属性。</p>
                  <div
                    v-for="(evidence, index) in entity.evidence"
                    :key="index"
                    class="evidence-entry"
                  >
                    <span>原文依据 · {{ evidence.source_id }}</span>
                    <blockquote>{{ evidence.quote }}</blockquote>
                  </div>
                  <p v-if="!entity.evidence.length" class="small-empty">
                    未返回原文依据。
                  </p>
                </div>
              </details>
            </section>
            <section>
              <h5>
                关系 <span>{{ facts.relations.length }}</span>
              </h5>
              <p v-if="!visibleRelations.length" class="small-empty">
                没有关系记录。
              </p>
              <details
                v-for="relation in visibleRelations"
                :key="relation.id"
                class="fact-item"
              >
                <summary>
                  <span class="item-name"
                    >{{ entityName(relation.source_id, facts) }} →
                    {{ entityName(relation.target_id, facts) }}</span
                  ><span class="item-type">{{ relation.type }}</span>
                </summary>
                <div class="fact-detail">
                  <p class="record-id">
                    关系 ID <code>{{ relation.id }}</code>
                  </p>
                  <dl v-if="Object.keys(relation.properties).length">
                    <template
                      v-for="(value, key) in relation.properties"
                      :key="key"
                      ><dt>{{ key }}</dt>
                      <dd>{{ value }}</dd></template
                    >
                  </dl>
                  <p v-else class="small-empty">没有记录额外属性。</p>
                  <div
                    v-for="(evidence, index) in relation.evidence"
                    :key="index"
                    class="evidence-entry"
                  >
                    <span>原文依据 · {{ evidence.source_id }}</span>
                    <blockquote>{{ evidence.quote }}</blockquote>
                  </div>
                  <p v-if="!relation.evidence.length" class="small-empty">
                    未返回原文依据。
                  </p>
                </div>
              </details>
            </section>
          </div>
        </template>
      </div>
    </details>
  </section>
</template>

<style scoped>
.graph-review {
  min-width: 0;
}
.graph-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}
.graph-heading h3 {
  margin: 0;
  font: 600 21px/1.4 var(--serif);
}
.graph-heading p {
  margin: 7px 0 0;
  color: var(--subtle);
  font-size: 13px;
  line-height: 1.7;
}
.graph-heading > button {
  flex-shrink: 0;
}
.graph-heading .ui-icon {
  width: 17px;
  height: 17px;
}
.availability-note {
  margin: 14px 0 0;
  color: var(--subtle);
  font-size: 13px;
  line-height: 1.7;
}
.candidate-panel {
  min-width: 0;
  margin-top: 20px;
  border: 1px solid var(--control-line);
  border-radius: 8px;
  overflow: hidden;
}
.candidate-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 15px 18px 0;
}
.candidate-heading h4 {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin: 0;
  font-size: 16px;
}
.candidate-heading h4 span {
  font: 400 13px/1.5 var(--sans);
  color: var(--clay);
}
.candidate-heading p {
  margin: 6px 0 0;
  color: var(--subtle);
  font-size: 13px;
}
.candidate-heading > button {
  flex-shrink: 0;
}
.candidate-intro {
  margin: 12px 18px 16px;
  color: var(--subtle);
  font-size: 13px;
  line-height: 1.7;
}
.candidate-fields {
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}
.candidate-scroll {
  max-height: 540px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0 18px 18px;
}
h5 {
  margin: 18px 0 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--muted);
}
.candidate-scroll > h5:first-child {
  margin-top: 0;
}
.candidate-item,
.fact-item {
  border-top: 1px solid var(--line);
}
.candidate-item:last-of-type,
.fact-item:last-child {
  border-bottom: 1px solid var(--line);
}
summary {
  cursor: pointer;
}
.candidate-item > summary {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 48px;
  padding: 10px 2px;
  list-style: none;
}
.candidate-item > summary::-webkit-details-marker {
  display: none;
}
.candidate-item > summary:focus-visible,
.fact-item > summary:focus-visible,
.saved-facts > summary:focus-visible,
.evidence > summary:focus-visible {
  outline: 2px solid var(--clay);
  outline-offset: 2px;
}
.item-name {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 14px;
}
.item-type {
  margin-left: auto;
  color: var(--subtle);
  font-size: 13px;
  overflow-wrap: anywhere;
}
.candidate-item > summary .ui-icon {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  color: var(--subtle);
}
.candidate-item[open] > summary .ui-icon {
  transform: rotate(180deg);
}
.item-editor {
  padding: 5px 0 18px;
}
.record-id {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 14px;
  color: var(--subtle);
  font-size: 13px;
  line-height: 1.7;
}
code {
  color: var(--muted);
  font-family: var(--sans);
  overflow-wrap: anywhere;
}
.editor-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}
.admin-field {
  min-width: 0;
}
.admin-field input,
.admin-field select,
.admin-field textarea {
  width: 100%;
  min-width: 0;
  font-size: 16px;
}
.admin-field textarea {
  resize: vertical;
  line-height: 1.7;
}
.properties-field,
.endpoint-fields {
  margin-top: 14px;
}
.evidence {
  margin-top: 14px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--muted);
}
.evidence > summary {
  padding: 5px 0;
}
.evidence-entry {
  margin-top: 12px;
  font-size: 13px;
  color: var(--subtle);
  overflow-wrap: anywhere;
}
.evidence-entry > span {
  display: block;
  line-height: 1.7;
}
blockquote {
  margin: 6px 0 0;
  padding: 0 0 0 12px;
  border-left: 2px solid var(--control-line);
  color: var(--ink);
  white-space: pre-wrap;
  font: 400 16px/1.8 var(--serif);
}
.candidate-source {
  margin-top: 18px;
  color: var(--muted);
  font-size: 13px;
}
.candidate-source > summary {
  padding: 8px 0;
}
.candidate-source .record-id {
  margin-top: 12px;
  margin-bottom: 0;
}
.source-uri {
  overflow-wrap: anywhere;
  color: var(--subtle);
}
pre {
  margin: 8px 0 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: 400 14px/1.8 var(--sans);
}
.candidate-validation {
  padding: 12px 18px;
  border-top: 1px solid var(--line);
  background: var(--paper);
  font-size: 13px;
  line-height: 1.8;
}
.candidate-validation p {
  display: flex;
  gap: 6px;
  align-items: center;
  margin: 0;
  color: var(--muted);
}
.candidate-validation .ui-icon {
  width: 17px;
  height: 17px;
  flex-shrink: 0;
}
.candidate-validation .validation-success {
  color: var(--clay);
  font-weight: 700;
}
.candidate-validation ul {
  margin: 10px 0 0;
  padding-left: 20px;
  color: var(--clay);
  overflow-wrap: anywhere;
}
.candidate-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  border-top: 1px solid var(--line);
  background: var(--paper);
}
.candidate-footer > span {
  color: var(--subtle);
  font-size: 13px;
  line-height: 1.7;
}
.candidate-footer > div {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}
.saved-facts {
  margin-top: 20px;
  border-top: 1px solid var(--line);
}
.saved-facts > summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 14px 0;
  color: var(--muted);
  font-size: 14px;
  font-weight: 700;
}
.saved-facts > summary::before {
  content: "+";
  color: var(--subtle);
  font-weight: 400;
}
.saved-facts[open] > summary::before {
  content: "−";
}
.facts-count {
  margin-left: auto;
  color: var(--subtle);
  font-size: 13px;
  font-weight: 400;
}
.facts-body {
  min-width: 0;
}
.facts-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  color: var(--subtle);
  font-size: 13px;
}
.facts-toolbar > button {
  flex-shrink: 0;
}
.facts-empty {
  padding: 18px 0;
  color: var(--subtle);
  font-size: 14px;
  line-height: 1.8;
}
.fact-columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 24px;
  max-height: 540px;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.fact-columns > section {
  min-width: 0;
}
.fact-columns h5 span {
  margin-left: 6px;
  font-weight: 400;
  color: var(--subtle);
}
.fact-item > summary {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-height: 44px;
  padding: 10px 0;
}
.fact-item > summary::before {
  content: "+";
  flex-shrink: 0;
  color: var(--subtle);
}
.fact-item[open] > summary::before {
  content: "−";
}
.fact-item .item-type {
  max-width: 48%;
  text-align: right;
}
.fact-detail {
  padding: 4px 0 16px 18px;
}
.fact-detail .record-id {
  margin-bottom: 8px;
}
dl {
  display: grid;
  grid-template-columns: minmax(70px, 0.8fr) minmax(0, 1.2fr);
  gap: 7px 12px;
  margin: 12px 0;
  font-size: 13px;
  line-height: 1.7;
}
dt {
  color: var(--subtle);
  overflow-wrap: anywhere;
}
dd {
  margin: 0;
  color: var(--ink);
  overflow-wrap: anywhere;
}
.aliases,
.small-empty {
  color: var(--subtle);
  font-size: 13px;
  line-height: 1.7;
}
.truncated-note {
  margin: 14px 0 0;
  padding: 10px 12px;
  border-left: 2px solid var(--clay);
  background: var(--paper);
  color: var(--muted);
  font-size: 13px;
  line-height: 1.7;
}
.retained-note {
  font-size: 13px;
}
.facts-loading {
  padding: 12px 0 6px;
  color: var(--subtle);
  font-size: 13px;
}
.facts-loading > div {
  height: 34px;
  margin: 10px 0;
  border-radius: 4px;
  background: var(--panel);
}
.facts-loading > div:last-child {
  width: 75%;
}
@media (max-width: 760px) {
  .graph-heading {
    flex-direction: column;
    gap: 12px;
  }
  .fact-columns,
  .editor-row {
    grid-template-columns: minmax(0, 1fr);
  }
  .fact-columns {
    gap: 6px;
  }
  .candidate-heading {
    align-items: flex-start;
    padding: 14px 14px 0;
  }
  .candidate-intro {
    margin: 12px 14px 14px;
  }
  .candidate-scroll {
    padding: 0 14px 14px;
    max-height: 60dvh;
  }
  .candidate-item > summary {
    gap: 8px;
  }
  .candidate-item .item-type {
    max-width: 45%;
    text-align: right;
  }
  .candidate-validation {
    padding: 12px 14px;
  }
  .candidate-footer {
    align-items: stretch;
    flex-direction: column;
    padding: 14px;
    gap: 12px;
  }
  .candidate-footer > div {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
    gap: 8px;
  }
  .candidate-footer button {
    width: 100%;
  }
}
</style>
