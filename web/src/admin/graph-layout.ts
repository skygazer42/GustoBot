import type { Entity, KnowledgeGraph, Relation } from "./contracts";

export type GraphSelection = { kind: "entity" | "relation"; id: string };

export interface GraphNode {
  entity: Entity;
  x: number;
  y: number;
  width?: number;
  height?: number;
  hub?: boolean;
  group?: string;
}

export interface GraphGroup {
  type: string;
  x: number;
  y: number;
  width: number;
  height: number;
  entityIds: string[];
}

export interface GraphEdge {
  relation: Relation;
  path: string;
  labelX: number;
  labelY: number;
  anchorX: number;
  anchorY: number;
}

interface RoutedEdge extends GraphEdge {
  bounds: { minX: number; maxX: number; minY: number; maxY: number };
}

export interface GraphLayout {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width: number;
  height: number;
  groups?: GraphGroup[];
}

export interface GraphViewport {
  width: number;
  height: number;
}

const nodeRadius = 26;

const typePalette = ["#9c4628", "#516b58", "#5b6f83", "#866a40", "#806379", "#587d7a"];
const warmTypePalette = ["#9c4628", "#866a40", "#806456", "#a67761", "#65554b", "#ad8150"];

export function graphTypeColor(type: string, palette: "default" | "warm" = "default"): string {
  let hash = 0;
  for (const character of type) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  const colors = palette === "warm" ? warmTypePalette : typePalette;
  return colors[hash % colors.length];
}

export function entityDisplayName(name: string, limit = 12): string {
  const characters = [...name];
  const leading = Math.floor((limit - 1) / 2);
  return characters.length > limit
    ? `${characters.slice(0, leading).join("")}…${characters.slice(-(limit - leading - 1)).join("")}`
    : name;
}

export function cardEntityDisplayName(name: string): string {
  const separator = name.lastIndexOf(" - ");
  if (separator < 1) return entityDisplayName(name, 10);
  const prefix = name.slice(0, separator).trim();
  const suffix = name.slice(separator + 3).trim();
  if (!suffix) return entityDisplayName(name, 10);
  const units = (value: string): number => [...value].reduce((total, character) => total + (character.charCodeAt(0) > 255 ? 2 : 1), 0);
  const complete = `${prefix} · ${suffix}`;
  if (units(complete) <= 20) return complete;
  let ending = suffix;
  if (units(ending) > 18) {
    ending = "";
    for (const word of suffix.split(/\s+/).reverse()) {
      const candidate = ending ? `${word} ${ending}` : word;
      if (units(candidate) > 18) break;
      ending = candidate;
    }
    if (!ending) return entityDisplayName(suffix, 10);
  }
  let beginning = "";
  for (const character of prefix) {
    if (units(beginning + character) > 18 - units(ending)) break;
    beginning += character;
  }
  return `${beginning.trimEnd()}…${ending}`;
}

export function entityDisplayLabel(entity: Entity): string {
  const order = entity.properties.order;
  const instruction = entity.properties.instruction;
  if (typeof order !== "number" || !Number.isInteger(order) || order < 1 || typeof instruction !== "string") return entity.name;
  const content = instruction.trim().replace(new RegExp(`^${order}\\s*[.．、:：)）]\\s*`, "u"), "");
  return content ? `${order}. ${content}` : entity.name;
}

export function cardEntityDisplayLines(entity: Entity): string[] {
  const label = entityDisplayLabel(entity);
  if (label === entity.name) return [cardEntityDisplayName(entity.name)];
  const lines = [""];
  let units = 0;
  for (const character of label) {
    const size = character.charCodeAt(0) > 255 ? 2 : 1;
    if (units + size > 21) {
      if (lines.length === 2) {
        lines[1] = `${[...lines[1]].slice(0, -2).join("").trimEnd()}…`;
        break;
      }
      const boundary = Math.max(...["，", "；", ",", ";"].map((separator) => lines[0].lastIndexOf(separator)));
      const remainder = boundary >= Math.floor(lines[0].length / 2) ? lines[0].slice(boundary + 1) : "";
      if (remainder) lines[0] = lines[0].slice(0, boundary + 1);
      lines.push(remainder);
      units = [...remainder].reduce((total, item) => total + (item.charCodeAt(0) > 255 ? 2 : 1), 0);
    }
    lines[lines.length - 1] += character;
    units += size;
  }
  return lines;
}

function compareCardEntities(left: Entity, right: Entity): number {
  const leftOrder = left.properties.order;
  const rightOrder = right.properties.order;
  return typeof leftOrder === "number" && typeof rightOrder === "number" && leftOrder !== rightOrder
    ? leftOrder - rightOrder : compareIds(left, right);
}

function rectangleBoundary(node: GraphNode, x: number, y: number): { x: number; y: number } {
  const dx = x - node.x;
  const dy = y - node.y;
  const scale = Math.min((node.width ?? 160) / 2 / Math.max(Math.abs(dx), 0.0001), (node.height ?? 64) / 2 / Math.max(Math.abs(dy), 0.0001));
  return { x: node.x + dx * scale, y: node.y + dy * scale };
}

function cardEdgeGeometry(relation: Relation, source: GraphNode, target: GraphNode, lane: number): RoutedEdge {
  let start: { x: number; y: number };
  let end: { x: number; y: number };
  let firstControl: { x: number; y: number };
  let secondControl: { x: number; y: number };
  if (source === target) {
    const lift = 100 + lane * 28;
    const halfWidth = (source.width ?? 160) / 2;
    const top = source.y - (source.height ?? 64) / 2;
    start = { x: source.x + halfWidth / 2, y: top };
    end = { x: source.x - halfWidth / 2, y: top };
    firstControl = { x: source.x + halfWidth * 1.7, y: top - lift };
    secondControl = { x: source.x - halfWidth * 1.7, y: top - lift };
  } else {
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const direction = relation.source_id < relation.target_id ? 1 : -1;
    if (Math.abs(dy) > Math.abs(dx) * 0.6) {
      firstControl = { x: source.x + dx * 0.35 + lane * direction, y: (source.y + target.y) / 2 };
      secondControl = { x: target.x - dx * 0.15 + lane * direction, y: (source.y + target.y) / 2 };
    } else {
      firstControl = { x: (source.x + target.x) / 2, y: source.y + dy * 0.35 + lane * direction };
      secondControl = { x: (source.x + target.x) / 2, y: target.y - dy * 0.15 + lane * direction };
    }
    start = rectangleBoundary(source, firstControl.x, firstControl.y);
    end = rectangleBoundary(target, secondControl.x, secondControl.y);
  }
  const anchorX = (start.x + 3 * firstControl.x + 3 * secondControl.x + end.x) / 8;
  const anchorY = (start.y + 3 * firstControl.y + 3 * secondControl.y + end.y) / 8;
  return {
    relation,
    path: `M ${start.x} ${start.y} C ${firstControl.x} ${firstControl.y} ${secondControl.x} ${secondControl.y} ${end.x} ${end.y}`,
    labelX: anchorX,
    labelY: anchorY,
    anchorX,
    anchorY,
    bounds: {
      minX: Math.min(start.x, firstControl.x, secondControl.x, end.x),
      maxX: Math.max(start.x, firstControl.x, secondControl.x, end.x),
      minY: Math.min(start.y, firstControl.y, secondControl.y, end.y),
      maxY: Math.max(start.y, firstControl.y, secondControl.y, end.y),
    },
  };
}

function placeCardEdgeLabel(edge: RoutedEdge, nodes: GraphNode[]): RoutedEdge {
  for (const offset of [0, -28, 28, -56, 56, -84, 84]) {
    const labelY = edge.labelY + offset;
    if (nodes.every((node) => edge.labelX + 110 < node.x - (node.width ?? 160) / 2 || edge.labelX - 110 > node.x + (node.width ?? 160) / 2 || labelY - 3 < node.y - (node.height ?? 64) / 2 || labelY - 22 > node.y + (node.height ?? 64) / 2)) {
      return { ...edge, labelY };
    }
  }
  return edge;
}

/** Retain readable card sizes; larger graphs use a pannable canvas instead of compressed labels. */
export function layoutCardGraph(graph: KnowledgeGraph, viewport?: GraphViewport): GraphLayout {
  const entities = [...new Map(graph.entities.map((entity) => [entity.id, entity])).values()].sort(compareIds);
  const byEntityId = new Map(entities.map((entity) => [entity.id, entity]));
  const relations = [...new Map(graph.relations.map((relation) => [relation.id, relation])).values()]
    .filter((relation) => byEntityId.has(relation.source_id) && byEntityId.has(relation.target_id)).sort(compareIds);
  const viewportWidth = Math.max(320, viewport && Number.isFinite(viewport.width) ? viewport.width : 1080);
  const viewportHeight = Math.max(420, viewport && Number.isFinite(viewport.height) ? viewport.height : 620);
  const neighbors = new Map(entities.map((entity) => [entity.id, new Set<string>()]));
  const outgoing = new Map(entities.map((entity) => [entity.id, new Set<string>()]));
  for (const relation of relations) {
    if (relation.source_id === relation.target_id) continue;
    neighbors.get(relation.source_id)!.add(relation.target_id);
    neighbors.get(relation.target_id)!.add(relation.source_id);
    outgoing.get(relation.source_id)!.add(relation.target_id);
  }
  const ordered = [...entities].sort((left, right) => neighbors.get(right.id)!.size - neighbors.get(left.id)!.size || outgoing.get(right.id)!.size - outgoing.get(left.id)!.size || compareIds(left, right));
  const hub = ordered[0];
  const nodes: GraphNode[] = [];
  const nodeGroups: GraphGroup[] = [];
  let width = viewportWidth;
  let height = viewportHeight;
  function place(entity: Entity, x: number, y: number, group?: string): void {
    const isHub = ordered.length > 3 && entity.id === hub?.id;
    nodes.push({ entity, x, y, width: isHub ? 184 : 160, height: group !== undefined ? 44 : isHub ? 80 : 64, hub: entity.id === hub?.id, ...(group !== undefined ? { group } : {}) });
  }
  if (ordered.length <= 3) {
    ordered.forEach((entity, index) => {
      if (viewportWidth < 600) place(entity, width / 2, 110 + index * (ordered.length === 2 ? 170 : 115));
      else place(entity, width / 2 + (ordered.length === 1 ? 0 : index === 0 ? -170 : 170), height / 2 + (ordered.length === 3 && index > 0 ? (index === 1 ? -90 : 90) : 0));
    });
  } else if (hub && neighbors.get(hub.id)!.size === entities.length - 1) {
    const byType = new Map<string, Entity[]>();
    for (const entity of entities) {
      if (entity === hub) continue;
      const group = byType.get(entity.type) ?? [];
      group.push(entity);
      byType.set(entity.type, group);
    }
    const groups = [...byType.entries()].sort((left, right) => right[1].length - left[1].length || compareIds({ id: left[0] }, { id: right[0] }));
    const right = groups[0]?.[1].sort(compareCardEntities) ?? [];
    const left = groups[1]?.[1].sort(compareCardEntities) ?? [];
    const bands: [Entity[], Entity[]] = [[], []];
    for (const [, group] of groups.slice(2)) {
      bands[bands[0].length <= bands[1].length ? 0 : 1].push(...group.sort(compareCardEntities));
    }
    width = Math.max(viewportWidth, 1080, Math.max(bands[0].length, bands[1].length) * 180 + 480);
    height = Math.max(viewportHeight, 604, Math.max(left.length, right.length) * 44 + 180);
    const centerY = height / 2 + 8;
    place(hub, width / 2, centerY);
    for (const [side, items] of [[-1, left], [1, right]] as const) {
      const x = side < 0 ? 140 : width - 140;
      if (items.length > 1) {
        const group: GraphGroup = { type: items[0].type, x: x - 92, y: centerY - (60 + items.length * 44) / 2, width: 184, height: 60 + items.length * 44, entityIds: items.map((entity) => entity.id) };
        nodeGroups.push(group);
        items.forEach((entity, index) => place(entity, x, group.y + 70 + index * 44, group.type));
      } else if (items[0]) place(items[0], x, centerY);
    }
    bands.forEach((items, band) => items.forEach((entity, index) =>
      place(entity, width / 2 + (index - (items.length - 1) / 2) * 180, band === 0 ? 90 : height - 74),
    ));
  } else {
    const columns = Math.max(1, Math.min(5, Math.floor((Math.max(viewportWidth, 720) - 80) / 220)));
    width = Math.max(viewportWidth, columns * 220 + 80);
    height = Math.max(viewportHeight, Math.ceil(ordered.length / columns) * 120 + 100);
    ordered.forEach((entity, index) => place(entity, 120 + index % columns * 220, 110 + Math.floor(index / columns) * 120));
  }
  const byId = new Map(nodes.map((node) => [node.entity.id, node]));
  const groups = new Map<string, Relation[]>();
  for (const relation of relations) {
    const key = pairKey(relation);
    const group = groups.get(key) ?? [];
    group.push(relation);
    groups.set(key, group);
  }
  function routeEdges(): RoutedEdge[] {
    return [...groups.values()].flatMap((group) => group.map((relation, index) => {
      const source = byId.get(relation.source_id)!;
      const target = byId.get(relation.target_id)!;
      const lane = source === target ? index : (index - (group.length - 1) / 2) * 54;
      return placeCardEdgeLabel(cardEdgeGeometry(relation, source, target, lane), nodes);
    }));
  }
  const edges = routeEdges();
  const left = Math.min(0, ...edges.map((edge) => edge.bounds.minX - 30));
  const top = Math.min(0, ...edges.map((edge) => Math.min(edge.bounds.minY, edge.labelY - 28) - 30));
  for (const node of nodes) {
    node.x -= left;
    node.y -= top;
  }
  for (const group of nodeGroups) {
    group.x -= left;
    group.y -= top;
  }
  return {
    nodes,
    edges: routeEdges().map(({ bounds: _bounds, ...edge }) => edge),
    width: Math.max(width - left, ...nodes.map((node) => node.x + 110), ...edges.map((edge) => edge.bounds.maxX - left + 30), ...nodeGroups.map((group) => group.x + group.width)),
    height: Math.max(height - top, ...nodes.map((node) => node.y + 64), ...edges.map((edge) => edge.bounds.maxY - top + 30), ...nodeGroups.map((group) => group.y + group.height)),
    ...(nodeGroups.length ? { groups: nodeGroups } : {}),
  };
}

function placeEdgeLabel(edge: RoutedEdge, nodes: GraphNode[], labelHalfWidth: number): RoutedEdge {
  for (const offset of [0, -24, 24, -48, 48, -72, 72]) {
    const labelY = edge.labelY + offset;
    const left = edge.labelX - labelHalfWidth;
    const right = edge.labelX + labelHalfWidth;
    const top = labelY - 22;
    const bottom = labelY - 3;
    const clear = nodes.every((node) => {
      const nameWidth = [...entityDisplayName(node.entity.name)].reduce((width, character) => width + (character.charCodeAt(0) > 255 ? 15 : 8), 0);
      const overlapsName = left < node.x + nameWidth / 2 + 8 && right > node.x - nameWidth / 2 - 8 && top < node.y + 55 && bottom > node.y + 32;
      return !overlapsName;
    });
    if (clear) return { ...edge, labelY };
  }
  return edge;
}

function compareIds(left: { id: string }, right: { id: string }): number {
  return left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
}

function pairKey(relation: Relation): string {
  return JSON.stringify([relation.source_id, relation.target_id].sort());
}

function edgeGeometry(relation: Relation, source: GraphNode, target: GraphNode, lane: number): RoutedEdge {
  if (source === target) {
    const size = 72 + lane * 26;
    return {
      relation,
      path: `M ${source.x + 20} ${source.y - 18} C ${source.x + size} ${source.y - size * 1.7} ${source.x - size} ${source.y - size * 1.7} ${source.x - 20} ${source.y - 18}`,
      labelX: source.x,
      labelY: source.y - size * 1.3,
      anchorX: source.x,
      anchorY: source.y - size * 1.275 - 4.5,
      bounds: { minX: source.x - size, maxX: source.x + size, minY: source.y - size * 1.7, maxY: source.y },
    };
  }
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const direction = relation.source_id < relation.target_id ? 1 : -1;
  const controlX = (source.x + target.x) / 2 - (dy / distance) * lane * direction;
  const controlY = (source.y + target.y) / 2 + (dx / distance) * lane * direction;
  const startDistance = Math.max(1, Math.hypot(controlX - source.x, controlY - source.y));
  const endDistance = Math.max(1, Math.hypot(target.x - controlX, target.y - controlY));
  const startX = source.x + ((controlX - source.x) / startDistance) * nodeRadius;
  const startY = source.y + ((controlY - source.y) / startDistance) * nodeRadius;
  const endX = target.x - ((target.x - controlX) / endDistance) * (nodeRadius + 4);
  const endY = target.y - ((target.y - controlY) / endDistance) * (nodeRadius + 4);
  return {
    relation,
    path: `M ${startX} ${startY} Q ${controlX} ${controlY} ${endX} ${endY}`,
    labelX: (startX + 2 * controlX + endX) / 4,
    labelY: (startY + 2 * controlY + endY) / 4,
    anchorX: (startX + 2 * controlX + endX) / 4,
    anchorY: (startY + 2 * controlY + endY) / 4,
    bounds: { minX: Math.min(startX, endX, controlX), maxX: Math.max(startX, endX, controlX), minY: Math.min(startY, endY, controlY), maxY: Math.max(startY, endY, controlY) },
  };
}

/** Lay out only the supplied identities and edges; caller-owned facts remain unchanged. */
export function layoutGraph(graph: KnowledgeGraph, viewport?: GraphViewport): GraphLayout {
  const entities = [...new Map(graph.entities.map((entity) => [entity.id, entity])).values()].sort(compareIds);
  const expansion = Math.max(1, Math.sqrt(entities.length / 12));
  const width = viewport
    ? Math.max(320, Number.isFinite(viewport.width) ? viewport.width : 320) * expansion
    : Math.max(960, Math.ceil(Math.sqrt(entities.length) * 150));
  const height = viewport
    ? Math.max(420, Number.isFinite(viewport.height) ? viewport.height : 420) * expansion
    : Math.max(620, Math.ceil(width * 0.7));
  const nodes = entities.map((entity, index) => {
    const angle = index * Math.PI * (3 - Math.sqrt(5));
    const radius = Math.sqrt((index + 0.5) / Math.max(1, entities.length)) * Math.min(width, height) * 0.4;
    return { entity, x: width / 2 + Math.cos(angle) * radius, y: height / 2 + Math.sin(angle) * radius };
  });
  const byId = new Map(nodes.map((node) => [node.entity.id, node]));
  const relations = [...new Map(graph.relations.map((relation) => [relation.id, relation])).values()]
    .filter((relation) => byId.has(relation.source_id) && byId.has(relation.target_id))
    .sort(compareIds);
  const attractionPairs = [...new Map(relations.filter((relation) => relation.source_id !== relation.target_id).map((relation) => [pairKey(relation), relation])).values()];
  const spacing = Math.sqrt((width * height) / Math.max(1, nodes.length)) * 0.65;
  for (let iteration = 0; iteration < 160; iteration++) {
    const movement = new Map(nodes.map((node) => [node.entity.id, { x: 0, y: 0 }]));
    for (let index = 0; index < nodes.length; index++) {
      const node = nodes[index];
      for (let otherIndex = index + 1; otherIndex < nodes.length; otherIndex++) {
        const other = nodes[otherIndex];
        const dx = node.x - other.x;
        const dy = node.y - other.y;
        const distance = Math.max(1, Math.hypot(dx, dy));
        const force = (spacing * spacing) / distance;
        const nodeMove = movement.get(node.entity.id)!;
        const otherMove = movement.get(other.entity.id)!;
        nodeMove.x += (dx / distance) * force;
        nodeMove.y += (dy / distance) * force;
        otherMove.x -= (dx / distance) * force;
        otherMove.y -= (dy / distance) * force;
      }
    }
    for (const relation of attractionPairs) {
      const source = byId.get(relation.source_id)!;
      const target = byId.get(relation.target_id)!;
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const force = (distance * distance) / spacing;
      const sourceMove = movement.get(source.entity.id)!;
      const targetMove = movement.get(target.entity.id)!;
      sourceMove.x += (dx / distance) * force;
      sourceMove.y += (dy / distance) * force;
      targetMove.x -= (dx / distance) * force;
      targetMove.y -= (dy / distance) * force;
    }
    const temperature = 18 * (1 - iteration / 160) + 0.1;
    for (const node of nodes) {
      const delta = movement.get(node.entity.id)!;
      delta.x += (width / 2 - node.x) * 0.16;
      delta.y += (height / 2 - node.y) * 0.16;
      const distance = Math.max(1, Math.hypot(delta.x, delta.y));
      node.x = Math.min(width - 100, Math.max(100, node.x + (delta.x / distance) * Math.min(distance, temperature)));
      node.y = Math.min(height - 85, Math.max(135, node.y + (delta.y / distance) * Math.min(distance, temperature)));
    }
  }
  const groups = new Map<string, Relation[]>();
  for (const relation of relations) {
    const key = pairKey(relation);
    const group = groups.get(key) ?? [];
    group.push(relation);
    groups.set(key, group);
  }
  const routes: { relation: Relation; source: GraphNode; target: GraphNode; lane: number }[] = [];
  for (const group of groups.values()) {
    group.forEach((relation, index) => {
      const source = byId.get(relation.source_id)!;
      const target = byId.get(relation.target_id)!;
      const lane = source === target ? index : (index - (group.length - 1) / 2) * 62;
      routes.push({ relation, source, target, lane });
    });
  }
  const labelPadding = viewport ? Math.min(150, width / 4) : 150;
  const edges = routes.map(({ relation, source, target, lane }) => placeEdgeLabel(edgeGeometry(relation, source, target, lane), nodes, labelPadding));
  const left = Math.min(0, ...edges.map((edge) => Math.min(edge.bounds.minX, edge.labelX - labelPadding) - 20));
  const top = Math.min(0, ...edges.map((edge) => Math.min(edge.bounds.minY, edge.labelY - 24) - 20));
  const right = Math.max(width, ...edges.map((edge) => Math.max(edge.bounds.maxX, edge.labelX + labelPadding) + 20));
  const bottom = Math.max(height, ...edges.map((edge) => Math.max(edge.bounds.maxY, edge.labelY + 24) + 20));
  if (left < 0 || top < 0) {
    for (const node of nodes) {
      node.x -= left;
      node.y -= top;
    }
  }
  return {
    nodes,
    edges: routes.map(({ relation, source, target, lane }) => {
      const { bounds: _bounds, ...edge } = placeEdgeLabel(edgeGeometry(relation, source, target, lane), nodes, labelPadding);
      return edge;
    }),
    width: right - left,
    height: bottom - top,
  };
}
