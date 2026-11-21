<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { DomainDefinition, KnowledgeGraph } from "./contracts";
import { cardEntityDisplayLines, cardEntityDisplayName, entityDisplayLabel, graphTypeColor, layoutCardGraph, layoutGraph } from "./graph-layout";
import type { GraphNode, GraphSelection, GraphViewport } from "./graph-layout";

const props = defineProps<{
  id: string;
  graph: KnowledgeGraph;
  domain: DomainDefinition | null;
  selected: GraphSelection | null;
  kind?: "facts" | "schema";
  presentation?: "cards";
}>();
const emit = defineEmits<{ select: [selection: GraphSelection] }>();
const canvas = ref<HTMLElement | null>(null);
const viewport = ref<GraphViewport | null>(null);
const isCards = computed(() => props.presentation === "cards");
const layout = computed(() => isCards.value
  ? layoutCardGraph(props.graph, viewport.value ?? undefined)
  : layoutGraph(props.graph, viewport.value ?? undefined));
const displayNodes = computed(() => layout.value.nodes.map((node) => ({
  ...node,
  labelLines: node.group ? cardEntityDisplayLines(node.entity) : [cardEntityDisplayName(node.entity.name)],
  typeLines: nodeTypeLines(node.entity.type),
})));
const view = computed(() => isCards.value && viewport.value ? viewport.value : layout.value);
const fitScale = computed(() => Math.min(1, view.value.width / layout.value.width, view.value.height / layout.value.height));
const minimumZoom = computed(() => isCards.value ? Math.min(0.5, fitScale.value) : 0.5);
const zoom = ref(1);
const pan = ref({ x: 0, y: 0 });
const drag = ref<{ pointerId: number; x: number; y: number; panX: number; panY: number } | null>(null);
let observer: ResizeObserver | null = null;
const highlighted = computed(() => {
  const ids = new Set<string>();
  if (props.selected?.kind === "entity") ids.add(props.selected.id);
  for (const edge of layout.value.edges) {
    const relation = edge.relation;
    if ((props.selected?.kind === "relation" && relation.id === props.selected.id) ||
        (props.selected?.kind === "entity" && [relation.source_id, relation.target_id].includes(props.selected.id))) {
      ids.add(relation.source_id);
      ids.add(relation.target_id);
    }
  }
  return ids;
});

watch(() => [props.graph, viewport.value, props.presentation], resetView);
watch(() => props.selected, (selected) => {
  if (!isCards.value || !selected) return;
  if (selected.kind === "entity") {
    const node = layout.value.nodes.find((item) => item.entity.id === selected.id);
    if (node) revealNode(node);
  } else {
    const edge = layout.value.edges.find((item) => item.relation.id === selected.id);
    if (edge) revealPoint(edge.anchorX, edge.anchorY, 34, 80);
  }
});

onMounted(() => {
  const element = canvas.value;
  if (!element) return;
  measureViewport(element.getBoundingClientRect());
  observer = new ResizeObserver((entries) => {
    const entry = entries[0];
    if (entry) measureViewport(entry.contentRect);
  });
  observer.observe(element);
});
onBeforeUnmount(() => observer?.disconnect());

function measureViewport(size: { width: number; height: number }): void {
  const width = Math.round(size.width);
  const height = Math.round(size.height);
  if (width > 0 && height > 0 && (viewport.value?.width !== width || viewport.value?.height !== height))
    viewport.value = { width, height };
}

function resetView(): void {
  zoom.value = 1;
  const hub = isCards.value && view.value.width < 600 && layout.value.nodes.length > 3
    ? layout.value.nodes.find((node) => node.hub) : null;
  const relation = hub && props.selected?.kind === "relation"
    ? props.graph.relations.find((item) => item.id === props.selected?.id) : null;
  const source = relation ? layout.value.nodes.find((node) => node.entity.id === relation.source_id) : null;
  const target = relation ? layout.value.nodes.find((node) => node.entity.id === relation.target_id) : null;
  const focus = source && target &&
    Math.abs(source.x - target.x) + ((source.width ?? 160) + (target.width ?? 160)) / 2 <= view.value.width - 32 &&
    Math.abs(source.y - target.y) + ((source.height ?? 64) + (target.height ?? 64)) / 2 <= view.value.height - 64
    ? { x: (source.x + target.x) / 2, y: (source.y + target.y) / 2 } : hub;
  pan.value = isCards.value
    ? { x: focus ? view.value.width / 2 - focus.x : (view.value.width - layout.value.width) / 2, y: focus ? view.value.height / 2 - focus.y : (view.value.height - layout.value.height) / 2 }
    : { x: 0, y: 0 };
  if (hub && props.selected?.kind === "entity") {
    const node = layout.value.nodes.find((item) => item.entity.id === props.selected?.id);
    if (node?.group) revealNode(node);
  }
}

function fitCanvas(): void {
  if (!isCards.value) return resetView();
  zoom.value = fitScale.value;
  pan.value = {
    x: (view.value.width - layout.value.width * fitScale.value) / 2,
    y: (view.value.height - layout.value.height * fitScale.value) / 2,
  };
}

function revealPoint(x: number, y: number, horizontalPadding: number, verticalPadding: number): void {
  if (!isCards.value) return;
  const screenX = x * zoom.value + pan.value.x;
  const screenY = y * zoom.value + pan.value.y;
  const paddedX = Math.min(horizontalPadding, view.value.width / 3);
  const paddedY = Math.min(verticalPadding, view.value.height / 3);
  pan.value = {
    x: pan.value.x + Math.min(view.value.width - paddedX, Math.max(paddedX, screenX)) - screenX,
    y: pan.value.y + Math.min(view.value.height - paddedY, Math.max(paddedY, screenY)) - screenY,
  };
}

function revealNode(node: GraphNode): void {
  const group = node.group ? layout.value.groups?.find((item) => item.type === node.group) : null;
  if (group && view.value.width < 600 && group.width * zoom.value <= view.value.width - 100 && group.height * zoom.value <= view.value.height - 48) {
    pan.value = {
      x: (view.value.width - 88) / 2 - (group.x + group.width / 2) * zoom.value,
      y: view.value.height / 2 - (group.y + group.height / 2) * zoom.value,
    };
    return;
  }
  revealPoint(node.x, node.y, 100, 100);
}

function changeZoom(factor: number): void {
  const next = Math.min(4, Math.max(minimumZoom.value, zoom.value * factor));
  const ratio = next / zoom.value;
  pan.value = {
    x: view.value.width / 2 - (view.value.width / 2 - pan.value.x) * ratio,
    y: view.value.height / 2 - (view.value.height / 2 - pan.value.y) * ratio,
  };
  zoom.value = next;
}

function typeLabel(type: string): string {
  return props.domain?.classes[type]?.label || type;
}

function nodeTypeLines(type: string): string[] {
  const characters = [...typeLabel(type)];
  if (characters.length <= 2) return [characters.join("")];
  const middle = Math.ceil(characters.length / 2);
  return [shortened(characters.slice(0, middle).join(""), 3), shortened(characters.slice(middle).join(""), 3)];
}

function relationLabel(type: string): string {
  return props.domain?.allowed_edges[type]?.description.replace(/[。.]$/, "") || type;
}

function shortened(value: string, limit: number): string {
  const characters = [...value];
  return characters.length > limit ? `${characters.slice(0, limit).join("")}…` : value;
}

function edgeSelected(id: string, sourceId: string, targetId: string): boolean {
  return props.selected?.kind === "relation" ? props.selected.id === id :
    props.selected?.kind === "entity" && [sourceId, targetId].includes(props.selected.id);
}

function canvasPoint(event: PointerEvent, svg: SVGSVGElement): DOMPoint | null {
  const matrix = svg.getScreenCTM();
  return matrix ? new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse()) : null;
}

function startPan(event: PointerEvent): void {
  if (event.button !== 0 || !(event.currentTarget instanceof SVGSVGElement)) return;
  if (event.target instanceof Element && event.target.closest("[data-graph-item]")) return;
  const point = canvasPoint(event, event.currentTarget);
  if (!point) return;
  drag.value = { pointerId: event.pointerId, x: point.x, y: point.y, panX: pan.value.x, panY: pan.value.y };
  event.currentTarget.setPointerCapture(event.pointerId);
}

function movePan(event: PointerEvent): void {
  if (!drag.value || drag.value.pointerId !== event.pointerId || !(event.currentTarget instanceof SVGSVGElement)) return;
  const point = canvasPoint(event, event.currentTarget);
  if (point) pan.value = { x: drag.value.panX + point.x - drag.value.x, y: drag.value.panY + point.y - drag.value.y };
}

function endPan(event: PointerEvent): void {
  if (drag.value?.pointerId !== event.pointerId) return;
  drag.value = null;
  if (event.currentTarget instanceof SVGSVGElement && event.currentTarget.hasPointerCapture(event.pointerId))
    event.currentTarget.releasePointerCapture(event.pointerId);
}
</script>

<template>
  <div ref="canvas" class="graph-canvas" :class="{ 'is-card-graph': isCards }">
    <div class="graph-canvas-tools" role="group" aria-label="图谱画布操作">
      <button type="button" aria-label="缩小图谱" :disabled="zoom <= minimumZoom" @click="changeZoom(1 / 1.25)">−</button>
      <span aria-live="polite">{{ Math.round(zoom * 100) }}%</span>
      <button type="button" aria-label="放大图谱" :disabled="zoom >= 4" @click="changeZoom(1.25)">+</button>
      <button class="graph-fit" type="button" @click="fitCanvas">适应画布</button>
    </div>
    <svg
      class="graph-canvas-svg"
      :class="{ 'is-panning': drag !== null }"
      :viewBox="`0 0 ${view.width} ${view.height}`"
      role="group"
      :aria-label="kind === 'schema' ? '本体类型关系图' : '已入库实体关系图'"
      @pointerdown="startPan"
      @pointermove="movePan"
      @pointerup="endPan"
      @pointercancel="endPan"
      @lostpointercapture="endPan"
    >
      <defs>
        <marker :id="`${id}-arrow`" viewBox="0 0 10 10" :refX="isCards ? 9 : 8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 1 1 L 9 5 L 1 9 z" :fill="isCards ? 'var(--subtle)' : 'currentColor'" />
        </marker>
        <marker v-if="isCards" :id="`${id}-arrow-active`" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 1 1 L 9 5 L 1 9 z" fill="var(--clay)" />
        </marker>
        <pattern :id="`${id}-dots`" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="0.8" fill="var(--line)" /></pattern>
      </defs>
      <rect width="100%" height="100%" :fill="`url(#${id}-dots)`" />
      <g :transform="`translate(${pan.x} ${pan.y}) scale(${zoom})`">
        <g v-for="group in layout.groups" :key="group.type" class="graph-node-group" :data-entity-type="group.type" :transform="`translate(${group.x} ${group.y})`" aria-hidden="true">
          <rect class="graph-group-body" :width="group.width" :height="group.height" rx="8" />
          <circle cx="16" cy="19" r="3" :fill="graphTypeColor(group.type, 'warm')" />
          <text class="graph-group-title" x="26" y="23">{{ typeLabel(group.type) }}</text>
          <text class="graph-group-count" :x="group.width - 14" y="23" text-anchor="end">{{ group.entityIds.length }}</text>
        </g>
        <g
          v-for="edge in layout.edges"
          :key="edge.relation.id"
          class="graph-edge"
          :class="{ 'is-selected': edgeSelected(edge.relation.id, edge.relation.source_id, edge.relation.target_id), 'is-muted': selected && !edgeSelected(edge.relation.id, edge.relation.source_id, edge.relation.target_id), 'show-label': layout.edges.length <= 8 || (selected?.kind === 'relation' && selected.id === edge.relation.id) }"
          data-graph-item="relation"
          @click.stop="emit('select', { kind: 'relation', id: edge.relation.id })"
          @keydown.enter.prevent="emit('select', { kind: 'relation', id: edge.relation.id })"
          @keydown.space.prevent="emit('select', { kind: 'relation', id: edge.relation.id })"
        >
          <title>{{ relationLabel(edge.relation.type) }} · {{ edge.relation.type }}</title>
          <path class="graph-edge-hit" :d="edge.path" />
          <path class="graph-edge-line" :d="edge.path" :marker-end="`url(#${id}-arrow${isCards && edgeSelected(edge.relation.id, edge.relation.source_id, edge.relation.target_id) ? '-active' : ''})`" />
          <circle
            class="graph-edge-target"
            :cx="edge.anchorX"
            :cy="edge.anchorY"
            r="22"
            role="button"
            tabindex="0"
            :aria-label="`关系：${edge.relation.type}，${graph.entities.find(entity => entity.id === edge.relation.source_id)?.name ?? edge.relation.source_id} → ${graph.entities.find(entity => entity.id === edge.relation.target_id)?.name ?? edge.relation.target_id}`"
            :aria-pressed="selected?.kind === 'relation' && selected.id === edge.relation.id"
            @focus="revealPoint(edge.anchorX, edge.anchorY, 34, 80)"
          />
          <text class="graph-edge-label" :x="edge.labelX" :y="edge.labelY - 7" text-anchor="middle">{{ shortened(relationLabel(edge.relation.type), viewport && viewport.width < 500 ? 12 : 18) }}</text>
        </g>
        <g
          v-for="node in displayNodes"
          :key="node.entity.id"
          class="graph-node"
          :class="{ 'is-selected': selected?.kind === 'entity' && selected.id === node.entity.id, 'is-muted': selected && !highlighted.has(node.entity.id), 'is-highlighted': highlighted.has(node.entity.id), 'is-hub': node.hub, 'is-grouped': !!node.group }"
          :style="{ '--node-color': graphTypeColor(node.entity.type, isCards ? 'warm' : 'default') }"
          :transform="`translate(${node.x} ${node.y})`"
          data-graph-item="entity"
          role="button"
          tabindex="0"
          :aria-label="kind === 'schema' ? `类型：${node.entity.name}（${node.entity.type}）` : `实体：${entityDisplayLabel(node.entity)}（${typeLabel(node.entity.type)}）`"
          :aria-pressed="selected?.kind === 'entity' && selected.id === node.entity.id"
          @click.stop="emit('select', { kind: 'entity', id: node.entity.id })"
          @keydown.enter.prevent="emit('select', { kind: 'entity', id: node.entity.id })"
          @keydown.space.prevent="emit('select', { kind: 'entity', id: node.entity.id })"
          @focus="revealNode(node)"
        >
          <title>{{ entityDisplayLabel(node.entity) }} · {{ typeLabel(node.entity.type) }}</title>
          <template v-if="isCards">
            <rect class="graph-node-ring" :x="-(node.width ?? 160) / 2 - (node.group ? 0 : 4)" :y="-(node.height ?? 64) / 2 - (node.group ? 0 : 4)" :width="(node.width ?? 160) + (node.group ? 0 : 8)" :height="(node.height ?? 64) + (node.group ? 0 : 8)" rx="6" />
            <rect class="graph-node-body" :x="-(node.width ?? 160) / 2" :y="-(node.height ?? 64) / 2" :width="node.width ?? 160" :height="node.height ?? 64" :rx="node.hub ? 12 : 7" />
            <line v-if="node.group" class="graph-node-divider" :x1="-(node.width ?? 160) / 2" :x2="(node.width ?? 160) / 2" :y1="-(node.height ?? 44) / 2" :y2="-(node.height ?? 44) / 2" />
            <rect v-else class="graph-node-accent" :x="-(node.width ?? 160) / 2" y="-16" width="3" height="32" rx="1.5" />
            <text class="graph-node-name" :y="node.group ? node.labelLines.length > 1 ? -3 : 5 : -4" :text-anchor="node.group ? 'start' : 'middle'">
              <tspan v-for="(line, index) in node.labelLines" :key="index" :x="node.group ? -68 : 0" :dy="index === 0 ? 0 : 16">{{ line }}</tspan>
            </text>
            <text v-if="!node.group" class="graph-node-kind" y="19" text-anchor="middle">{{ shortened(typeLabel(node.entity.type), 8) }}</text>
          </template>
          <template v-else>
            <circle class="graph-node-ring" r="32" />
            <circle class="graph-node-body" r="26" />
            <text class="graph-node-kind" :y="node.typeLines.length > 1 ? -3 : 5" text-anchor="middle">
              <tspan v-for="(line, index) in node.typeLines" :key="index" x="0" :dy="index === 0 ? 0 : 15">{{ line }}</tspan>
            </text>
            <text class="graph-node-name" y="49" text-anchor="middle">{{ shortened(entityDisplayLabel(node.entity), 8) }}</text>
          </template>
        </g>
      </g>
    </svg>
    <p class="graph-canvas-hint">{{ isCards && (layout.width > view.width || layout.height > view.height) ? "拖动画布查看其余节点 · 点选连线查看关系" : "拖动画布 · 悬停或点选连线查看关系" }}</p>
  </div>
</template>

<style scoped lang="scss">
.graph-canvas {
  position: relative;
  min-width: 0;
  min-height: 360px;
  height: 100%;
  overflow: hidden;
  border-radius: 8px;
  background: var(--paper);
}
.graph-canvas-svg {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 360px;
  cursor: grab;
  touch-action: none;
  user-select: none;
}
.graph-canvas-svg.is-panning { cursor: grabbing; }
.graph-canvas-tools {
  position: absolute;
  z-index: 1;
  top: 14px;
  right: 14px;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface);
  color: var(--muted);
  font-size: 13px;
}
.graph-canvas-tools button {
  min-width: 32px;
  min-height: 32px;
  padding: 3px 7px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--muted);
  font: inherit;
  cursor: pointer;
}
.graph-canvas-tools button:hover:not(:disabled) { background: var(--wash); }
.graph-canvas-tools button:disabled { opacity: 0.4; cursor: default; }
.graph-canvas-tools .graph-fit { margin-left: 4px; border-left: 1px solid var(--line); border-radius: 0; }
.graph-canvas-tools > span { min-width: 37px; text-align: center; font-variant-numeric: tabular-nums; }
.graph-node, .graph-edge { cursor: pointer; outline: none; }
.graph-node.is-muted, .graph-edge.is-muted { opacity: 0.28; }
.graph-node-body { fill: color-mix(in srgb, var(--node-color) 12%, var(--surface)); stroke: var(--node-color); stroke-width: 1.6; }
.graph-node-ring { fill: none; stroke: transparent; stroke-width: 2; }
.graph-node-kind { fill: var(--node-color); font-family: inherit; font-size: 12px; font-weight: 600; pointer-events: none; }
.graph-node-name { fill: var(--ink); font-size: 14px; font-weight: 600; stroke: var(--paper); stroke-width: 4px; paint-order: stroke; }
.graph-node:hover .graph-node-body, .graph-node.is-selected .graph-node-body { stroke-width: 3; }
.graph-node.is-selected .graph-node-ring, .graph-node:focus-visible .graph-node-ring { stroke: var(--clay); }
.graph-edge { color: var(--subtle); }
.graph-edge-line { fill: none; stroke: currentColor; stroke-width: 1.4; }
.graph-edge-hit { fill: none; stroke: transparent; stroke-width: 20; }
.graph-edge-target { fill: transparent; stroke: transparent; outline: none; }
.graph-edge-target:focus-visible { stroke: var(--clay); stroke-width: 1.5; }
.graph-edge-label { fill: var(--muted); font-size: 13px; stroke: var(--paper); stroke-width: 5px; paint-order: stroke; opacity: 0; pointer-events: none; }
.graph-edge.show-label .graph-edge-label, .graph-edge:hover .graph-edge-label, .graph-edge:focus-within .graph-edge-label { opacity: 1; pointer-events: auto; }
.graph-edge:hover, .graph-edge.is-selected, .graph-edge:focus-within { color: var(--clay); opacity: 1; }
.graph-edge.is-selected .graph-edge-line, .graph-edge:focus-within .graph-edge-line { stroke-width: 2.8; }
.graph-edge:focus-within .graph-edge-label { fill: var(--clay); text-decoration: underline; }
.graph-canvas-tools button:focus-visible { outline: 2px solid var(--clay); outline-offset: 1px; }
.graph-canvas-hint {
  position: absolute;
  bottom: 12px;
  left: 16px;
  margin: 0;
  color: var(--subtle);
  font-size: 13px;
  pointer-events: none;
}
.is-card-graph {
  border-radius: 0;

  .graph-node-group { pointer-events: none; }
  .graph-group-body { fill: var(--surface); stroke: var(--line); stroke-width: 1; }
  .graph-group-title { fill: var(--muted); font-size: 13px; font-weight: 600; }
  .graph-group-count { fill: var(--subtle); font-size: 12px; font-variant-numeric: tabular-nums; }
  .graph-node-divider { stroke: var(--line); stroke-width: 1; pointer-events: none; }
  .graph-node.is-muted { opacity: 1; }
  .graph-edge { color: var(--subtle); }
  .graph-edge.is-muted { opacity: 0.8; }
  .graph-edge-line { stroke-width: 1.2; }
  .graph-edge:hover, .graph-edge.is-selected, .graph-edge:focus-within { color: var(--clay); opacity: 1; }
  .graph-edge.is-selected .graph-edge-line, .graph-edge:focus-within .graph-edge-line { stroke-width: 2.2; }
  .graph-edge.is-selected .graph-edge-label { fill: var(--clay); }
  .graph-node-body { fill: var(--surface); stroke: var(--line); stroke-width: 1; }
  .graph-node-accent { fill: var(--node-color); pointer-events: none; }
  .graph-node-name { fill: var(--ink); stroke: none; font-size: 14px; }
  .graph-node-kind { fill: var(--subtle); font-size: 13px; font-weight: 400; }
  .graph-node.is-hub .graph-node-body { fill: color-mix(in srgb, var(--clay) 8%, var(--surface)); stroke: color-mix(in srgb, var(--clay) 55%, var(--line)); }
  .graph-node.is-hub .graph-node-ring { stroke: color-mix(in srgb, var(--clay) 18%, var(--paper)); stroke-width: 1; }
  .graph-node.is-hub .graph-node-name { font: 600 19px var(--serif); }
  .graph-node.is-highlighted .graph-node-body { stroke: var(--clay); stroke-width: 1.5; }
  .graph-node.is-highlighted:not(.is-hub) .graph-node-body,
  .graph-node.is-selected .graph-node-body { fill: color-mix(in srgb, var(--clay) 7%, var(--surface)); stroke: var(--clay); }
  .graph-node.is-highlighted:not(.is-hub) .graph-node-name,
  .graph-node.is-selected .graph-node-name { fill: var(--clay); }
  .graph-node.is-selected .graph-node-ring, .graph-node:focus-visible .graph-node-ring { stroke: var(--clay); stroke-width: 2; }
  .graph-node.is-grouped .graph-node-body { fill: transparent; stroke: transparent; }
  .graph-node.is-grouped .graph-node-name { font-size: 13px; font-weight: 400; }
  .graph-node.is-grouped:hover .graph-node-body { fill: var(--panel); }
  .graph-node.is-grouped.is-highlighted .graph-node-body,
  .graph-node.is-grouped.is-selected .graph-node-body { fill: color-mix(in srgb, var(--clay) 8%, var(--surface)); stroke: var(--clay); stroke-width: 1; }
  .graph-node.is-grouped.is-selected .graph-node-ring { stroke: transparent; }
  .graph-node.is-grouped:focus-visible .graph-node-ring { stroke: var(--clay); }
}
@media (max-width: 700px) {
  .graph-canvas { height: 420px; }
  .graph-canvas, .graph-canvas-svg { min-height: 420px; }
  .graph-canvas-tools { top: 10px; right: 10px; }
  .graph-canvas-tools button { min-width: 44px; min-height: 44px; }
  .is-card-graph .graph-canvas-tools { top: auto; bottom: 36px; flex-direction: column; gap: 0; }
  .is-card-graph .graph-canvas-tools .graph-fit { margin-left: 0; border-left: 0; border-top: 1px solid var(--line); }
  .graph-canvas-hint { bottom: 8px; left: 10px; font-size: 13px; }
}
</style>
