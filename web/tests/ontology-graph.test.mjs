import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "./load-typescript.mjs";

const { buildOntologyGraph, missingOntologyConstraints } = loadTypeScript("../src/admin/ontology-graph.ts");
const definition = (label) => ({ label, description: `${label}的定义`, grain: "一类对象", properties: { amount: { type: "number", required: true, description: "用量", minimum: 0 } } });
const domain = {
  id: "manufacturing", name: "生产知识空间", version: "v1", description: "生产对象与约束", interpretation_notes: [],
  classes: { Machine: definition("设备"), Tool: definition("设备"), Material: definition("材料"), Product: definition("产物") },
  allowed_edges: { USES: { domain: ["Machine", "Tool"], range: ["Material", "Product"], description: "使用对象", properties: {} } },
};

test("ontology projection keeps type identities and all declared directed combinations", () => {
  const graph = buildOntologyGraph(domain);
  assert.equal(graph.entities.length, 4);
  assert.deepEqual(graph.entities.filter((entity) => entity.name === "设备").map((entity) => entity.id), ["Machine", "Tool"]);
  assert.deepEqual(graph.relations.map((relation) => [relation.type, relation.source_id, relation.target_id]), [
    ["USES", "Machine", "Material"], ["USES", "Machine", "Product"],
    ["USES", "Tool", "Material"], ["USES", "Tool", "Product"],
  ]);
  assert.equal(new Set(graph.relations.map((relation) => relation.id)).size, 4);
});

test("ontology adapter does not create instance properties or evidence and does not mutate definitions", () => {
  const before = JSON.stringify(domain);
  const graph = buildOntologyGraph(domain);
  assert.deepEqual(graph.sources, []);
  for (const item of [...graph.entities, ...graph.relations]) {
    assert.deepEqual(item.properties, {});
    assert.deepEqual(item.evidence, []);
  }
  graph.entities[0].name = "修改视图";
  assert.equal(JSON.stringify(domain), before);
});

test("undefined endpoints are counted and omitted without inventing types", () => {
  const value = { ...domain, allowed_edges: { LINKS: { domain: ["Machine", "Missing"], range: ["Material", "Unknown"], description: "连接", properties: {} } } };
  const graph = buildOntologyGraph(value);
  assert.equal(graph.entities.length, 4);
  assert.deepEqual(graph.relations.map((relation) => [relation.source_id, relation.target_id]), [["Machine", "Material"]]);
  assert.equal(missingOntologyConstraints(value).length, 3);
  assert.equal(graph.entities.some((entity) => entity.id === "Missing" || entity.id === "Unknown"), false);
});

test("repeated endpoints deduplicate constraints and empty ontologies remain empty", () => {
  const value = { ...domain, allowed_edges: { SELF: { domain: ["Machine", "Machine"], range: ["Machine", "Machine"], description: "自关联", properties: {} } } };
  const graph = buildOntologyGraph(value);
  assert.equal(graph.relations.length, 1);
  assert.equal(graph.relations[0].source_id, graph.relations[0].target_id);
  assert.deepEqual(buildOntologyGraph({ ...domain, classes: {}, allowed_edges: {} }), { entities: [], relations: [], sources: [] });
});
