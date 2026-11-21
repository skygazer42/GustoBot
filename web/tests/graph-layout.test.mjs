import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { loadTypeScript } from "./load-typescript.mjs";

const { cardEntityDisplayLines, cardEntityDisplayName, entityDisplayLabel, entityDisplayName, layoutCardGraph, layoutGraph } = loadTypeScript("../src/admin/graph-layout.ts");
const entity = (id, name = id) => ({ id, name, type: "Document", aliases: [], properties: {}, evidence: [] });
const relation = (id, source, target) => ({ id, type: "RELATED", source_id: source, target_id: target, properties: {}, evidence: [] });
const graph = (entities, relations = []) => ({ entities, relations, sources: [] });

test("graph layout preserves isolated identities and equal names without modifying facts", () => {
  const input = graph([entity("one", "相同名称"), entity("two", "相同名称"), entity("isolated")], [relation("edge", "one", "two")]);
  const before = structuredClone(input);
  const result = layoutGraph(input);
  assert.deepEqual(input, before);
  assert.equal(result.nodes.length, 3);
  assert.deepEqual(new Set(result.nodes.map(node => node.entity.id)), new Set(["one", "two", "isolated"]));
  for (const node of result.nodes) {
    assert.ok(Number.isFinite(node.x) && Number.isFinite(node.y));
    assert.ok(node.x >= 0 && node.x <= result.width && node.y >= 0 && node.y <= result.height);
  }
});

test("graph layout is deterministic for the same identities and does not invent missing endpoints", () => {
  const first = graph([entity("b"), entity("a")], [relation("present", "a", "b"), relation("missing", "a", "absent")]);
  const second = graph([...first.entities].reverse(), [...first.relations].reverse());
  assert.deepEqual(layoutGraph(first), layoutGraph(second));
  assert.deepEqual(layoutGraph(first).edges.map(edge => edge.relation.id), ["present"]);
  assert.equal(layoutGraph(graph([])).nodes.length, 0);
});

test("self relations and parallel directed relations retain distinct routes and identities", () => {
  const input = graph([entity("a"), entity("b")], [relation("ab-1", "a", "b"), relation("ab-2", "a", "b"), relation("ba", "b", "a"), relation("loop-1", "a", "a"), relation("loop-2", "a", "a")]);
  const result = layoutGraph(input);
  assert.equal(result.edges.length, 5);
  assert.equal(new Set(result.edges.map(edge => edge.path)).size, 5);
  for (const edge of result.edges) {
    assert.ok(!edge.path.includes("NaN") && !edge.path.includes("Infinity"));
    assert.ok(Number.isFinite(edge.labelX) && Number.isFinite(edge.labelY));
  }
});

test("bounded layout keeps a larger disconnected graph finite", () => {
  const result = layoutGraph(graph(Array.from({ length: 200 }, (_, index) => entity(`entity-${index}`))));
  assert.equal(result.nodes.length, 200);
  assert.ok(result.nodes.every(node => Number.isFinite(node.x) && Number.isFinite(node.y)));
  assert.equal(result.edges.length, 0);
});

test("small graph uses the mobile viewport without shrinking names into a desktop coordinate system", () => {
  const input = graph([entity("hub"), entity("left"), entity("right")], [relation("left-edge", "hub", "left"), relation("right-edge", "hub", "right")]);
  const result = layoutGraph(input, { width: 356, height: 420 });
  const scale = Math.min(356 / result.width, 420 / result.height);
  assert.ok(15 * scale >= 13, `Entity names would be only ${15 * scale}px`);
  assert.equal(result.nodes.length, 3);
  assert.equal(result.edges.length, 2);
  for (const edge of result.edges) {
    const coordinates = edge.path.match(/-?\d+(?:\.\d+)?/g).map(Number);
    const endpoint = { x: coordinates.at(-2), y: coordinates.at(-1) };
    const target = result.nodes.find(node => node.entity.id === edge.relation.target_id);
    assert.ok(Math.hypot(endpoint.x - target.x, endpoint.y - target.y) >= 29, "Arrow endpoint is hidden inside its node");
  }
});

test("viewport dimensions remain finite for zero or nonfinite measurements", () => {
  const input = graph([entity("one")]);
  for (const viewport of [{ width: 0, height: 0 }, { width: NaN, height: Infinity }]) {
    const result = layoutGraph(input, viewport);
    assert.ok(Number.isFinite(result.width) && result.width >= 320);
    assert.ok(Number.isFinite(result.height) && result.height >= 420);
    assert.ok(result.nodes.every(node => Number.isFinite(node.x) && Number.isFinite(node.y)));
  }
});

test("long entity labels retain their distinguishing suffix without altering complete identities", () => {
  const first = "通用工艺说明文档 - Operation 1";
  const second = "通用工艺说明文档 - Operation 2";
  assert.ok(entityDisplayName(first).endsWith(first.slice(-6)));
  assert.ok(entityDisplayName(second).endsWith(second.slice(-6)));
  assert.notEqual(entityDisplayName(first), entityDisplayName(second));
  assert.equal(entityDisplayName("短名称"), "短名称");
  assert.equal([...entityDisplayName(first)].length, 12);
});

test("mobile relation labels leave space below the source entity name", () => {
  const input = graph([entity("vessel", "萃取釜"), entity("solvent", "乙醇"), entity("step", "低温萃取")], [relation("uses", "vessel", "solvent"), relation("performs", "vessel", "step")]);
  const result = layoutGraph(input, { width: 356, height: 420 });
  const source = result.nodes.find(node => node.entity.id === "vessel");
  const edge = result.edges.find(item => item.relation.id === "performs");
  assert.ok(edge.labelY - 22 > source.y + 55 || edge.labelY - 3 < source.y + 32);
});

const storedSourceGraph = JSON.parse(readFileSync(new URL("../design-lab/recipe-workspace-directions/snapshot.json", import.meta.url), "utf8").replace(/^\uFEFF/, "")).graph;

test("card layout keeps all stored identities and edges without changing source facts", () => {
  const before = structuredClone(storedSourceGraph);
  const result = layoutCardGraph(storedSourceGraph, { width: 1080, height: 620 });
  assert.equal(result.nodes.length, 15);
  assert.equal(result.edges.length, 14);
  assert.deepEqual(new Set(result.nodes.map(node => node.entity.id)), new Set(storedSourceGraph.entities.map(item => item.id)));
  assert.deepEqual(new Set(result.edges.map(edge => edge.relation.id)), new Set(storedSourceGraph.relations.map(item => item.id)));
  assert.deepEqual(storedSourceGraph, before);
  assert.deepEqual(layoutCardGraph({ ...storedSourceGraph, entities: [...storedSourceGraph.entities].reverse(), relations: [...storedSourceGraph.relations].reverse() }, { width: 1080, height: 620 }), result);
});

test("stored card graphs do not compress or overlap cards on desktop and mobile", () => {
  for (const viewport of [{ width: 1080, height: 620 }, { width: 356, height: 420 }]) {
    const result = layoutCardGraph(storedSourceGraph, viewport);
    assert.ok(result.width >= 1000, "A larger graph should retain a pannable canvas instead of shrinking its labels");
    for (let index = 0; index < result.nodes.length; index++) {
      const node = result.nodes[index];
      assert.ok(node.width >= 150 && node.height >= (node.group ? 44 : 60));
      for (const other of result.nodes.slice(index + 1)) {
        const gap = node.group && node.group === other.group ? 0 : 12;
        assert.ok(Math.abs(node.x - other.x) >= (node.width + other.width) / 2 + gap || Math.abs(node.y - other.y) >= (node.height + other.height) / 2 + gap, `${node.entity.id} overlaps ${other.entity.id}`);
      }
    }
  }
});

test("card arrows meet actual rectangle boundaries and keep a real curve midpoint", () => {
  const input = graph([entity("a"), entity("b")], [relation("ab-1", "a", "b"), relation("ab-2", "a", "b"), relation("ba", "b", "a"), relation("loop", "a", "a")]);
  const result = layoutCardGraph(input, { width: 1080, height: 620 });
  assert.equal(new Set(result.edges.map(edge => edge.path)).size, 4);
  for (const edge of result.edges) {
    const coordinates = edge.path.match(/-?\d+(?:\.\d+)?/g).map(Number);
    const source = result.nodes.find(node => node.entity.id === edge.relation.source_id);
    const target = result.nodes.find(node => node.entity.id === edge.relation.target_id);
    const startBoundary = Math.max(Math.abs(coordinates[0] - source.x) / (source.width / 2), Math.abs(coordinates[1] - source.y) / (source.height / 2));
    const endBoundary = Math.max(Math.abs(coordinates[6] - target.x) / (target.width / 2), Math.abs(coordinates[7] - target.y) / (target.height / 2));
    assert.ok(Math.abs(startBoundary - 1) < 0.00001);
    assert.ok(Math.abs(endBoundary - 1) < 0.00001);
    assert.ok(Math.abs(edge.anchorX - (coordinates[0] + 3 * coordinates[2] + 3 * coordinates[4] + coordinates[6]) / 8) < 0.00001);
    assert.ok(Math.abs(edge.anchorY - (coordinates[1] + 3 * coordinates[3] + 3 * coordinates[5] + coordinates[7]) / 8) < 0.00001);
  }
});

test("a small mobile card graph keeps both complete nodes in the initial viewport", () => {
  const result = layoutCardGraph(graph([entity("a"), entity("b")], [relation("ab", "a", "b")]), { width: 356, height: 420 });
  assert.equal(result.width, 356);
  assert.equal(result.height, 420);
  assert.ok(result.nodes.every(node => node.x - node.width / 2 >= 0 && node.x + node.width / 2 <= 356 && node.y - node.height / 2 >= 70 && node.y + node.height / 2 <= 390));
});

test("card labels preserve complete delimiter suffixes across domains", () => {
  const recipe = "番茄炒蛋 - Step 1";
  const process = "通用多阶段复杂工艺说明 - Stage 2";
  assert.ok(cardEntityDisplayName(recipe).endsWith("Step 1"));
  assert.ok(cardEntityDisplayName(process).endsWith("Stage 2"));
  assert.ok(!cardEntityDisplayName(recipe).includes("…tep"));
  assert.ok(!cardEntityDisplayName(process).includes("…tage"));
  assert.ok(cardEntityDisplayName(process).startsWith("通用"));
  assert.equal(cardEntityDisplayName("短名称"), "短名称");
  assert.equal(entityDisplayName(recipe), "番茄炒蛋 …Step 1");
});

test("ordered actions display their actual instruction with one number and retain source identities", () => {
  const step = { ...entity("step-id", "番茄炒蛋 - Step 2"), properties: { order: 2, instruction: "2:蛋液两边摊匀，煎好捞出备用。" } };
  const before = structuredClone(step);
  assert.equal(entityDisplayLabel(step), "2. 蛋液两边摊匀，煎好捞出备用。");
  assert.equal(cardEntityDisplayLines(step).join(""), "2. 蛋液两边摊匀，煎好捞出备用。");
  assert.deepEqual(cardEntityDisplayLines(step), ["2. 蛋液两边摊匀，", "煎好捞出备用。"]);
  assert.ok(cardEntityDisplayLines(step).length <= 2);
  assert.deepEqual(step, before);
  assert.equal(entityDisplayLabel(entity("salt", "盐")), "盐");
  assert.deepEqual(cardEntityDisplayLines(entity("salt", "盐")), ["盐"]);
  assert.equal(entityDisplayLabel({ ...step, properties: { order: 2, instruction: "200克材料加入容器" } }), "2. 200克材料加入容器");
  assert.equal(entityDisplayLabel({ ...step, properties: { order: "2", instruction: "加入材料" } }), step.name);
});

test("a stored star graph groups repeated entity types and gives its hub a distinct readable size", () => {
  const result = layoutCardGraph(storedSourceGraph, { width: 1080, height: 604 });
  const hub = result.nodes.find(node => node.hub);
  const byType = new Map();
  for (const node of result.nodes) {
    if (node === hub) continue;
    const group = byType.get(node.entity.type) ?? [];
    group.push(node);
    byType.set(node.entity.type, group);
  }
  for (const group of [...byType.values()].filter(items => items.length > 1)) {
    assert.equal(new Set(group.map(node => node.x)).size, 1, "Repeated types should form a readable column instead of a disconnected bottom strip");
    const ordered = [...group].sort((left, right) => left.y - right.y);
    const orders = ordered.map(node => node.entity.properties.order).filter(order => typeof order === "number");
    assert.deepEqual(orders, [...orders].sort((left, right) => left - right));
  }
  assert.ok(hub.width > 160 && hub.height > 64);
  assert.ok(result.width <= 1080 && result.height <= 604, "The stored graph should fit its desktop workspace without compressed labels");
});

test("stored star edges spread at the hub and avoid unrelated card interiors", () => {
  const result = layoutCardGraph(storedSourceGraph, { width: 1080, height: 604 });
  const hub = result.nodes.find(node => node.hub);
  const ports = new Set();
  for (const edge of result.edges) {
    const coordinates = edge.path.match(/-?\d+(?:\.\d+)?/g).map(Number);
    if (edge.relation.source_id === hub.entity.id) ports.add(`${coordinates[0]},${coordinates[1]}`);
    for (let sample = 1; sample < 80; sample++) {
      const t = sample / 80;
      const x = (1 - t) ** 3 * coordinates[0] + 3 * (1 - t) ** 2 * t * coordinates[2] + 3 * (1 - t) * t ** 2 * coordinates[4] + t ** 3 * coordinates[6];
      const y = (1 - t) ** 3 * coordinates[1] + 3 * (1 - t) ** 2 * t * coordinates[3] + 3 * (1 - t) * t ** 2 * coordinates[5] + t ** 3 * coordinates[7];
      for (const node of result.nodes) {
        if ([edge.relation.source_id, edge.relation.target_id].includes(node.entity.id)) continue;
        assert.ok(Math.abs(x - node.x) >= node.width / 2 || Math.abs(y - node.y) >= node.height / 2, `${edge.relation.id} crosses ${node.entity.id}`);
      }
    }
  }
  assert.equal(ports.size, result.edges.filter(edge => edge.relation.source_id === hub.entity.id).length, "Hub edges should not share a single port");
});

test("repeated side types share compact containers while members retain exact identities and order", () => {
  const result = layoutCardGraph(storedSourceGraph, { width: 1080, height: 604 });
  assert.equal(result.groups.length, 2);
  const groupedIds = new Set();
  for (const group of result.groups) {
    assert.equal(group.width, 184);
    const members = group.entityIds.map(id => result.nodes.find(node => node.entity.id === id));
    assert.ok(members.length > 1);
    assert.equal(group.height, 36 + 24 + members.length * 44);
    members.forEach((node, index) => {
      groupedIds.add(node.entity.id);
      assert.equal(node.entity.type, group.type);
      assert.equal(node.group, group.type);
      assert.equal(node.width, 160);
      assert.equal(node.height, 44);
      assert.equal(node.x - node.width / 2, group.x + 12);
      assert.equal(node.y - node.height / 2, group.y + 36 + 12 + index * 44);
      assert.ok(node.y + node.height / 2 <= group.y + group.height - 12);
      if (index) assert.equal(node.y - members[index - 1].y, 44);
    });
    const orders = members.map(node => node.entity.properties.order).filter(order => typeof order === "number");
    assert.deepEqual(orders, [...orders].sort((left, right) => left - right));
  }
  assert.equal(groupedIds.size, 10);
  assert.equal(result.nodes.filter(node => !node.group).length, 5);
  assert.equal(result.nodes.length, storedSourceGraph.entities.length);
  assert.equal(result.edges.length, storedSourceGraph.relations.length);
  assert.equal(layoutGraph(storedSourceGraph).groups, undefined);
  assert.equal(layoutCardGraph(graph([entity("one"), entity("two")], [relation("edge", "one", "two")])).groups, undefined);
});

test("shared containers stay aligned with their rows when edge bounds translate the graph", () => {
  const hub = layoutCardGraph(storedSourceGraph).nodes.find(node => node.hub).entity.id;
  const withLoops = { ...storedSourceGraph, relations: [...storedSourceGraph.relations, ...Array.from({ length: 10 }, (_, index) => relation(`loop-${index}`, hub, hub))] };
  const result = layoutCardGraph(withLoops, { width: 1080, height: 604 });
  assert.ok(result.nodes.find(node => node.hub).y > 310, "Self loops should force the graph down from its original center");
  for (const group of result.groups) {
    const first = result.nodes.find(node => node.entity.id === group.entityIds[0]);
    const last = result.nodes.find(node => node.entity.id === group.entityIds.at(-1));
    assert.equal(first.x - first.width / 2, group.x + 12);
    assert.equal(first.y - first.height / 2, group.y + 48);
    assert.equal(last.y + last.height / 2, group.y + group.height - 12);
    assert.ok(group.x >= 0 && group.y >= 0 && group.x + group.width <= result.width && group.y + group.height <= result.height);
  }
});
