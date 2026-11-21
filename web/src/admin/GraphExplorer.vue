<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import GraphCanvas from "./GraphCanvas.vue";
import UiIcon from "../components/UiIcon.vue";
import { errorMessage, isCancelled, queryGraph, sourceFacts } from "./api";
import type { DomainDefinition, FactResult, SourceSummary } from "./contracts";
import type { GraphSelection } from "./graph-layout";
import { entityDisplayLabel, graphTypeColor } from "./graph-layout";

const props = defineProps<{
  domain: DomainDefinition | null;
  source: SourceSummary | null;
  variant?: "recipe";
}>();
const emit = defineEmits<{ all: []; sources: []; review: [] }>();
const isRecipe = computed(() => props.variant === "recipe");
const facts = ref<FactResult | null>(null);
const busy = ref(false);
const error = ref("");
const entityType = ref("");
const anchorId = ref("");
const query = ref("");
const selection = ref<GraphSelection | null>(null);
let controller: AbortController | null = null;

const activeEntity = computed(() => selection.value?.kind === "entity"
  ? facts.value?.entities.find((entity) => entity.id === selection.value?.id) ?? null : null);
const activeRelation = computed(() => selection.value?.kind === "relation"
  ? facts.value?.relations.find((relation) => relation.id === selection.value?.id) ?? null : null);
const activeItem = computed(() => activeEntity.value ?? activeRelation.value);
const matchingEntities = computed(() => {
  const term = query.value.trim().toLocaleLowerCase();
  return term ? facts.value?.entities.filter((entity) =>
    [entity.name, ...entity.aliases, entityDisplayLabel(entity)].some((name) => name.toLocaleLowerCase().includes(term)),
  ) ?? [] : [];
});
const connections = computed(() => activeEntity.value ? facts.value?.relations.filter((relation) =>
  relation.source_id === activeEntity.value?.id || relation.target_id === activeEntity.value?.id,
) ?? [] : []);
const types = computed(() => Object.entries(props.domain?.classes ?? {}));
const typeSummary = computed(() => {
  const counts = new Map<string, number>();
  for (const entity of facts.value?.entities ?? []) counts.set(entity.type, (counts.get(entity.type) ?? 0) + 1);
  return [...counts].map(([type, count]) => ({ type, count, label: typeLabel(type), color: graphTypeColor(type, isRecipe.value ? "warm" : "default") }));
});

function typeLabel(type: string): string {
  return props.domain?.classes[type]?.label || type;
}
function entityName(id: string): string {
  const entity = facts.value?.entities.find((entity) => entity.id === id);
  if (!entity) return id;
  return entityDisplayLabel(entity);
}
function sourceName(id: string): string {
  if (props.source?.source_id === id) return props.source.title;
  return facts.value?.sources.find((source) => source.id === id)?.uri || id;
}
function exploreOutgoing(): void {
  if (!activeEntity.value || props.source || isRecipe.value) return;
  entityType.value = "";
  anchorId.value = activeEntity.value.id;
}
function resetScope(): void {
  entityType.value = "";
  anchorId.value = "";
}
async function reload(reset = false): Promise<void> {
  controller?.abort();
  busy.value = false;
  error.value = "";
  if (reset || (isRecipe.value && !props.source)) {
    facts.value = null;
    selection.value = null;
    query.value = "";
  }
  if (!props.domain || (isRecipe.value && !props.source)) return;
  const request = new AbortController();
  controller = request;
  busy.value = true;
  try {
    const result = props.source
      ? await sourceFacts(props.source, request.signal)
      : await queryGraph(props.domain, entityType.value, anchorId.value, request.signal);
    if (request.signal.aborted) return;
    if (result.ontology_version !== props.domain.version) {
      throw new Error("图谱与当前本体版本不一致，请刷新后重试。");
    }
    facts.value = result;
    if (selection.value && !(selection.value.kind === "entity" ? result.entities : result.relations)
      .some((item) => item.id === selection.value?.id)) selection.value = null;
    if (isRecipe.value && !selection.value) {
      const firstRelation = result.relations[0];
      const firstEntity = result.entities[0];
      if (firstRelation) selection.value = { kind: "relation", id: firstRelation.id };
      else if (firstEntity) selection.value = { kind: "entity", id: firstEntity.id };
    }
  } catch (reason) {
    if (!request.signal.aborted && !isCancelled(reason)) error.value = errorMessage(reason);
  } finally {
    if (!request.signal.aborted) busy.value = false;
  }
}
defineExpose({ reload });
watch(
  [() => props.domain?.id, () => props.domain?.version, () => props.source?.source_id,
    () => props.source?.version, () => props.variant, entityType, anchorId],
  () => void reload(true), { immediate: true },
);
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <section class="graph-workspace" :class="{ 'is-recipe-graph': isRecipe }" aria-labelledby="graph-workspace-title" :aria-busy="busy">
    <h2 v-if="isRecipe" id="graph-workspace-title" class="sr-only">{{ source ? `${source.title}的已入库图谱` : "菜谱图谱" }}</h2>
    <header v-else class="graph-workspace-heading">
      <div>
        <h2 id="graph-workspace-title">已入库知识图谱</h2>
        <p v-if="source">{{ source.title }} · 按来源版本核对</p>
        <p v-else-if="anchorId">以所选实体为起点，查看一跳出向关系</p>
        <p v-else class="graph-overview-hint">查看已映射的实体、关系与原文证据</p>
      </div>
      <div v-if="facts" class="graph-counts" aria-label="当前图谱数量">
        <span><strong>{{ facts.entities.length }}</strong> 个实体</span>
        <span><strong>{{ facts.relations.length }}</strong> 条关系</span>
      </div>
    </header>
    <div class="graph-workspace-toolbar">
      <label class="admin-search graph-entity-search">
        <UiIcon name="search" /><span class="sr-only">搜索当前图谱实体</span>
        <input v-model="query" type="search" placeholder="搜索当前图谱实体" maxlength="200" :disabled="!facts" />
      </label>
      <ul v-if="isRecipe && facts?.entities.length" class="graph-inline-legend" aria-label="图谱实体类型">
        <li v-for="item in typeSummary" :key="item.type">
          <span class="graph-type-swatch" :style="{ background: item.color }"></span>
          <span>{{ item.label }}</span><strong>{{ item.count }}</strong>
        </li>
      </ul>
      <div v-if="isRecipe && facts" class="graph-counts" aria-label="当前图谱数量">
        <span><strong>{{ facts.entities.length }}</strong> 个实体</span>
        <span><strong>{{ facts.relations.length }}</strong> 条关系</span>
      </div>
      <label v-if="!source && !isRecipe" class="graph-type-filter"><span class="graph-filter-label">起点类型</span>
        <select v-model="entityType" :disabled="!domain">
          <option value="">全部类型</option>
          <option v-for="[symbol, definition] in types" :key="symbol" :value="symbol">{{ definition.label || symbol }}</option>
        </select>
      </label>
      <button v-if="!isRecipe && (anchorId || entityType)" class="admin-text-button" type="button" @click="resetScope">返回空间概览</button>
      <template v-if="source && !isRecipe">
        <button class="admin-text-button" type="button" @click="emit('all')">查看全空间图谱</button>
        <button class="admin-secondary" type="button" @click="emit('review')">核对来源映射</button>
      </template>
    </div>
    <div v-if="query.trim()" class="graph-search-results" aria-label="实体搜索结果">
      <button v-for="entity in matchingEntities.slice(0, 8)" :key="entity.id" type="button" class="admin-secondary"
        @click="selection = { kind: 'entity', id: entity.id }">{{ entityDisplayLabel(entity) }} · {{ typeLabel(entity.type) }}</button>
      <p v-if="!matchingEntities.length">当前视图没有匹配实体。</p>
      <span v-else-if="matchingEntities.length > 8">共 {{ matchingEntities.length }} 项，继续输入以缩小范围。</span>
    </div>
    <div v-if="error" class="graph-query-error" role="alert">
      <p>{{ error }}</p><button class="admin-secondary" type="button" @click="reload()">重试图谱读取</button>
    </div>
    <p v-if="busy" class="graph-loading" role="status">正在读取已入库的图谱事实…</p>
    <p v-else-if="!domain" class="graph-loading">等待本体定义加载后读取图谱。</p>
    <p v-else-if="isRecipe && !source" class="graph-loading">选择一份菜谱后查看它的图谱与原文依据。</p>
    <div v-if="facts && !facts.entities.length && !busy" class="graph-workspace-empty">
      <UiIcon name="graph" />
      <h3>{{ source ? "这份资料尚无已入库图谱" : entityType || anchorId ? "当前范围没有图谱事实" : "还没有已入库的图谱事实" }}</h3>
      <p>文档向量入库与图谱写入分别进行；完成来源映射或抽取、校验并写入后，这里才会出现真实节点和关系。</p>
      <button v-if="source" type="button" class="admin-secondary" @click="emit('review')">核对来源映射</button>
      <button v-else-if="entityType || anchorId" type="button" class="admin-secondary" @click="resetScope">返回空间概览</button>
      <button v-else type="button" class="admin-secondary" @click="emit('sources')">查看资料来源</button>
    </div>
    <template v-else-if="facts && facts.entities.length">
      <div class="graph-exploration-body">
        <GraphCanvas id="stored-knowledge-graph" :graph="facts" :domain="domain" :selected="selection" :presentation="isRecipe ? 'cards' : undefined" @select="selection = $event" />
        <aside class="graph-inspector" aria-label="图谱详情">
          <template v-if="activeItem">
            <div class="graph-current-item">
              <span class="graph-inspector-kind">{{ activeEntity ? typeLabel(activeEntity.type) : isRecipe ? "当前关系" : "关系" }}</span>
              <h3>{{ activeEntity ? entityName(activeEntity.id) : isRecipe && activeRelation ? entityName(activeRelation.target_id) : activeRelation?.type }}</h3>
              <p v-if="activeRelation" class="graph-direction">{{ entityName(activeRelation.source_id) }} <UiIcon name="arrow" /> {{ entityName(activeRelation.target_id) }}</p>
              <p v-if="activeRelation && domain?.allowed_edges[activeRelation.type]?.description" class="admin-helper">{{ domain.allowed_edges[activeRelation.type].description }}</p>
              <p v-if="isRecipe && activeRelation" class="graph-relation-type">{{ activeRelation.type }}</p>
            </div>
            <button v-if="activeEntity && !source && !isRecipe" type="button" class="admin-secondary" :disabled="busy" @click="exploreOutgoing">查看出向关系</button>
            <section class="graph-inspector-section">
              <h4 v-if="!isRecipe || Object.keys(activeItem.properties).length">属性</h4>
              <dl v-if="Object.keys(activeItem.properties).length" class="graph-properties">
                <div v-for="(value, name) in activeItem.properties" :key="name"><dt>{{ name }}</dt><dd>{{ value }}</dd></div>
              </dl>
              <p v-else-if="!isRecipe" class="admin-helper">未记录额外属性。</p>
              <details class="graph-identity"><summary>标识{{ activeEntity?.aliases.length ? "与别名" : "" }}</summary>
                <code>{{ activeItem.id }}</code><p v-if="activeEntity?.aliases.length">{{ activeEntity.aliases.join("、") }}</p>
                <p v-if="isRecipe && activeEntity && entityDisplayLabel(activeEntity) !== activeEntity.name">{{ activeEntity.name }}</p>
              </details>
            </section>
            <section v-if="activeEntity && connections.length" class="graph-inspector-section">
              <h4>关联关系 <span>{{ connections.length }}</span></h4>
              <button v-for="relation in connections.slice(0, 20)" :key="relation.id" class="graph-connection" type="button"
                @click="selection = { kind: 'relation', id: relation.id }">
                <span>{{ entityName(relation.source_id) }} → {{ entityName(relation.target_id) }}</span><small>{{ relation.type }}</small>
              </button>
              <p v-if="connections.length > 20" class="admin-helper">当前列出前 20 条，可在画布上继续选择关系。</p>
            </section>
            <section class="graph-inspector-section">
              <h4>来源证据 <span>{{ activeItem.evidence.length }}</span></h4>
              <div v-for="(evidence, index) in activeItem.evidence" :key="`${evidence.source_id}:${index}`" class="graph-evidence">
                <p>{{ sourceName(evidence.source_id) }}</p><blockquote>{{ evidence.quote }}</blockquote>
              </div>
              <p v-if="!activeItem.evidence.length" class="admin-helper">当前记录未返回原文证据。</p>
            </section>
          </template>
          <div v-else class="graph-overview">
            <span class="graph-inspector-kind">当前视图</span>
            <h3>实体分布</h3>
            <p class="admin-helper">选择节点或连线，查看属性与来源证据。</p>
            <ul class="graph-type-legend" aria-label="当前实体类型分布">
              <li v-for="item in typeSummary" :key="item.type"><span class="graph-type-swatch" :style="{ background: item.color }"></span><span>{{ item.label }}</span><strong>{{ item.count }}</strong></li>
            </ul>
            <p class="admin-helper">数量仅统计当前加载的图谱。</p>
          </div>
        </aside>
      </div>
      <footer class="graph-workspace-footer">
        <span>本体版本 {{ facts.ontology_version }}</span>
        <span v-if="isRecipe">按当前来源版本核对</span>
        <span v-else-if="source">撤回文档检索会保留已写入的图谱事实。</span>
        <span v-else-if="!anchorId && !entityType">空间共 {{ facts.total }} 个实体</span>
        <p v-if="facts.truncated" role="status">{{ isRecipe ? "当前为部分事实视图，节点、关系或证据已达到读取上限。" : "当前为部分事实视图，节点、关系或证据已达到读取上限。可选择实体查看出向关系，或按起点类型缩小范围。" }}</p>
      </footer>
    </template>
  </section>
</template>
