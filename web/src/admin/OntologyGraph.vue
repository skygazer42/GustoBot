<script setup lang="ts">
import { computed, ref, watch } from "vue";
import GraphCanvas from "./GraphCanvas.vue";
import UiIcon from "../components/UiIcon.vue";
import type { DomainDefinition } from "./contracts";
import { graphTypeColor } from "./graph-layout";
import type { GraphSelection } from "./graph-layout";
import { buildOntologyGraph, missingOntologyConstraints } from "./ontology-graph";

const props = defineProps<{ domain: DomainDefinition }>();
const selection = ref<GraphSelection | null>(null);
const query = ref("");
const graph = computed(() => buildOntologyGraph(props.domain));
const missing = computed(() => missingOntologyConstraints(props.domain));
const types = computed(() => Object.entries(props.domain.classes));
const relations = computed(() => Object.entries(props.domain.allowed_edges));
const matchingTypes = computed(() => {
  const term = query.value.trim().toLocaleLowerCase();
  return types.value.filter(([symbol, definition]) =>
    !term || [symbol, definition.label].some((name) => name.toLocaleLowerCase().includes(term)),
  );
});
const activeType = computed(() => selection.value?.kind === "entity"
  ? props.domain.classes[selection.value.id] ?? null : null);
const activeRelation = computed(() => selection.value?.kind === "relation"
  ? graph.value.relations.find((relation) => relation.id === selection.value?.id) ?? null : null);
const activeRule = computed(() => activeRelation.value
  ? props.domain.allowed_edges[activeRelation.value.type] ?? null : null);
const properties = computed(() => activeType.value?.properties ?? activeRule.value?.properties ?? {});

function typeLabel(symbol: string): string {
  return props.domain.classes[symbol]?.label || symbol;
}
function selectType(symbol: string): void {
  if (!types.value.some(([type]) => type === symbol)) return;
  selection.value = { kind: "entity", id: symbol };
}
watch(() => [props.domain.id, props.domain.version], () => {
  selection.value = null;
  query.value = "";
});
</script>

<template>
  <div class="ontology-view">
    <section class="graph-workspace ontology-workspace" aria-labelledby="ontology-graph-title">
      <header class="graph-workspace-heading">
        <div><h2 id="ontology-graph-title">本体结构图</h2><p>类型与允许关系 · 只读约束</p></div>
        <div class="graph-counts" aria-label="本体定义数量">
          <span><strong>{{ types.length }}</strong> 类实体</span>
          <span><strong>{{ relations.length }}</strong> 类关系</span>
        </div>
      </header>
      <div class="graph-workspace-toolbar">
        <label class="admin-search ontology-search"><UiIcon name="search" /><span class="sr-only">搜索本体类型</span>
          <input v-model="query" type="search" maxlength="200" placeholder="搜索类型名称或标识" />
        </label>
        <span class="ontology-domain-name">{{ domain.name }}</span>
      </div>
      <div v-if="query.trim()" class="ontology-search-results" aria-label="本体类型搜索结果">
        <button v-for="[symbol, definition] in matchingTypes.slice(0, 8)" :key="symbol" type="button" class="admin-secondary"
          @click="selectType(symbol)">{{ definition.label || symbol }} · {{ symbol }}</button>
        <p v-if="!matchingTypes.length">没有匹配的本体类型。</p>
        <span v-else-if="matchingTypes.length > 8">共 {{ matchingTypes.length }} 项，继续输入可缩小范围。</span>
      </div>
      <p v-if="missing.length" class="ontology-missing" role="status">
        {{ missing.length }} 条类型约束引用了未定义的端点，未绘入结构图；可在定义清单中核对。
      </p>
      <div v-if="!types.length" class="graph-workspace-empty"><UiIcon name="graph" /><h3>尚未定义实体类型</h3><p>当前知识空间没有可绘制的本体类型。</p></div>
      <div v-else class="graph-exploration-body">
        <GraphCanvas id="ontology-type-graph" kind="schema" :graph="graph" :domain="domain" :selected="selection" @select="selection = $event" />
        <aside class="graph-inspector ontology-inspector" aria-label="本体定义详情">
          <template v-if="activeType || activeRule">
            <button class="admin-text-button ontology-return" type="button" @click="selection = null">返回类型目录</button>
            <span class="graph-inspector-kind">{{ activeType ? "实体类型" : "关系约束" }}</span>
            <h3>{{ activeType?.label || (activeType ? selection?.id : activeRelation?.type) }}</h3>
            <code v-if="activeType" class="ontology-symbol">{{ selection?.id }}</code>
            <p class="ontology-description">{{ activeType?.description ?? activeRule?.description }}</p>
            <p v-if="activeType?.grain" class="ontology-grain"><span>建模粒度</span>{{ activeType.grain }}</p>
            <section v-if="activeRule" class="graph-inspector-section">
              <h4>允许的起点类型</h4>
              <div class="ontology-type-links"><button v-for="symbol in activeRule.domain" :key="symbol" type="button" class="admin-secondary" :disabled="!graph.entities.some((entity) => entity.id === symbol)" @click="selectType(symbol)">{{ typeLabel(symbol) }}{{ graph.entities.some((entity) => entity.id === symbol) ? "" : "（未定义）" }}</button></div>
              <h4 class="ontology-range-heading">允许的终点类型</h4>
              <div class="ontology-type-links"><button v-for="symbol in activeRule.range" :key="symbol" type="button" class="admin-secondary" :disabled="!graph.entities.some((entity) => entity.id === symbol)" @click="selectType(symbol)">{{ typeLabel(symbol) }}{{ graph.entities.some((entity) => entity.id === symbol) ? "" : "（未定义）" }}</button></div>
              <p v-if="activeRelation" class="ontology-current-pair">当前连线：{{ typeLabel(activeRelation.source_id) }} → {{ typeLabel(activeRelation.target_id) }}</p>
            </section>
            <section class="graph-inspector-section">
              <h4>属性约束 <span>{{ Object.keys(properties).length }}</span></h4>
              <article v-for="(property, name) in properties" :key="name" class="ontology-property">
                <header><strong>{{ name }}</strong><span>{{ property.required ? "必填" : "可选" }}</span></header>
                <p class="ontology-property-type">{{ property.type }}</p>
                <p>{{ property.description }}</p>
                <p v-if="property.minimum != null || property.maximum != null" class="ontology-property-bounds">
                  <span v-if="property.minimum != null">最小值 {{ property.minimum }}</span><span v-if="property.maximum != null">最大值 {{ property.maximum }}</span>
                </p>
              </article>
              <p v-if="!Object.keys(properties).length" class="admin-helper">未定义额外属性约束。</p>
            </section>
          </template>
          <template v-else>
            <span class="graph-inspector-kind">类型目录</span><h3>类型之间如何关联</h3>
            <p class="ontology-description">选择类型或连线，查看建模含义、允许方向和属性约束。</p>
            <div class="ontology-type-directory">
              <button v-for="[symbol, definition] in types" :key="symbol" type="button" :aria-label="`查看类型：${definition.label || symbol}`" @click="selectType(symbol)">
                <span class="ontology-type-swatch" :style="{ backgroundColor: graphTypeColor(symbol) }"></span>
                <span><strong>{{ definition.label || symbol }}</strong><small>{{ symbol }}</small></span>
                <UiIcon name="chevron" />
              </button>
            </div>
          </template>
        </aside>
      </div>
      <footer class="graph-workspace-footer"><span>本体版本 {{ domain.version }}</span><span>描述允许的类型结构，不表示已写入的实例事实。</span></footer>
    </section>
    <details class="ontology-definition-list">
      <summary>定义清单 <span>{{ types.length }} 类实体 · {{ relations.length }} 类关系</span></summary>
      <p v-if="domain.description" class="ontology-description">{{ domain.description }}</p>
      <ul v-if="domain.interpretation_notes.length" class="ontology-interpretation"><li v-for="note in domain.interpretation_notes" :key="note">{{ note }}</li></ul>
      <div class="ontology-definition-columns">
        <section aria-label="实体类型定义"><h3>实体类型</h3>
          <details v-for="[symbol, definition] in types" :key="symbol" class="ontology-definition-item">
            <summary>{{ definition.label || symbol }} <code>{{ symbol }}</code></summary>
            <p>{{ definition.description }}</p><p v-if="definition.grain">建模粒度：{{ definition.grain }}</p>
            <dl><div v-for="(property, name) in definition.properties" :key="name"><dt>{{ name }} · {{ property.required ? "必填" : "可选" }}</dt><dd>{{ property.type }} · {{ property.description }}<span v-if="property.minimum != null"> · 最小值 {{ property.minimum }}</span><span v-if="property.maximum != null"> · 最大值 {{ property.maximum }}</span></dd></div></dl>
          </details>
        </section>
        <section aria-label="关系约束定义"><h3>允许的关系</h3>
          <details v-for="[symbol, definition] in relations" :key="symbol" class="ontology-definition-item">
            <summary>{{ symbol }}</summary><p>{{ definition.description }}</p>
            <p>{{ definition.domain.map(typeLabel).join(" / ") }} → {{ definition.range.map(typeLabel).join(" / ") }}</p>
            <dl><div v-for="(property, name) in definition.properties" :key="name"><dt>{{ name }} · {{ property.required ? "必填" : "可选" }}</dt><dd>{{ property.type }} · {{ property.description }}<span v-if="property.minimum != null"> · 最小值 {{ property.minimum }}</span><span v-if="property.maximum != null"> · 最大值 {{ property.maximum }}</span></dd></div></dl>
          </details>
        </section>
      </div>
    </details>
  </div>
</template>

<style scoped lang="scss">
.ontology-search { flex: 1; max-width: 340px; min-width: 200px; }
.ontology-search input { width: 100%; }
.ontology-domain-name { color: var(--subtle); font-size: 13px; }
.ontology-search-results { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 20px; border-bottom: 1px solid var(--line); }
.ontology-search-results p, .ontology-search-results > span { margin: 0; color: var(--subtle); font-size: 13px; }
.ontology-missing { margin: 0; padding: 10px 20px; color: var(--clay); background: var(--paper); font-size: 13px; }
.ontology-return { display: block; margin: -6px 0 15px; }
.ontology-symbol { display: block; margin-top: -8px; color: var(--subtle); font-size: 13px; overflow-wrap: anywhere; }
.ontology-description { margin: 12px 0; line-height: 1.8; color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }
.ontology-grain { display: grid; gap: 5px; margin-top: 20px; color: var(--muted); font-size: 13px; }
.ontology-grain span { color: var(--subtle); }
.ontology-type-directory { margin-top: 24px; }
.ontology-type-directory > button { display: grid; grid-template-columns: 10px minmax(0, 1fr) 14px; align-items: center; gap: 10px; width: 100%; min-height: 60px; padding: 11px 0; border: 0; border-bottom: 1px solid var(--line); color: var(--ink); background: transparent; text-align: left; }
.ontology-type-directory > button:hover { color: var(--clay); }
.ontology-type-directory strong { display: block; font-size: 14px; font-weight: 600; }
.ontology-type-directory small { display: block; margin-top: 3px; color: var(--subtle); font-size: 13px; overflow-wrap: anywhere; }
.ontology-type-swatch { width: 8px; height: 8px; border-radius: 50%; }
.ontology-type-links { display: flex; flex-wrap: wrap; gap: 8px; }
.ontology-inspector .ontology-range-heading { margin-top: 20px; }
.ontology-current-pair { margin-top: 16px; color: var(--subtle); font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.ontology-property { padding: 14px 0; border-bottom: 1px solid var(--line); font-size: 13px; }
.ontology-property header { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; }
.ontology-property header strong { overflow-wrap: anywhere; }
.ontology-property header span { color: var(--subtle); }
.ontology-property p { margin: 6px 0 0; color: var(--muted); line-height: 1.7; overflow-wrap: anywhere; }
.ontology-property .ontology-property-type { color: var(--clay); }
.ontology-property-bounds { display: flex; flex-wrap: wrap; gap: 12px; }
.ontology-definition-list { margin-top: 16px; padding: 16px 20px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
.ontology-definition-list > summary { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px; color: var(--muted); cursor: pointer; }
.ontology-definition-list > summary span { color: var(--subtle); font-size: 13px; }
.ontology-definition-list > summary::before { content: "+"; margin-right: 2px; color: var(--clay); }
.ontology-definition-list[open] > summary::before { content: "−"; }
.ontology-definition-list > summary span { margin-left: auto; }
.ontology-definition-columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 24px; }
.ontology-definition-columns h3 { font: 600 21px/1.5 var(--serif); }
.ontology-definition-item { padding: 14px 0; border-bottom: 1px solid var(--line); font-size: 13px; overflow-wrap: anywhere; }
.ontology-definition-item > summary { cursor: pointer; color: var(--ink); }
.ontology-definition-item code { margin-left: 10px; color: var(--subtle); font-size: 13px; }
.ontology-definition-item p { color: var(--muted); line-height: 1.8; }
.ontology-definition-item dl { color: var(--muted); }
.ontology-definition-item dl > div { margin-top: 12px; }
.ontology-definition-item dt { font-weight: 600; }
.ontology-definition-item dd { margin: 5px 0 0; line-height: 1.7; }
.ontology-interpretation { padding-left: 20px; color: var(--muted); font-size: 13px; line-height: 1.8; }
@media (max-width: 700px) {
  .ontology-search { max-width: none; }
  .ontology-search input { font-size: 16px; }
  .ontology-domain-name { width: 100%; }
  .ontology-search-results, .ontology-missing { padding-inline: 16px; }
  .ontology-type-links .admin-secondary { min-height: 44px; }
  .ontology-definition-list { padding: 16px; }
  .ontology-definition-columns { grid-template-columns: minmax(0, 1fr); gap: 12px; }
}
</style>
