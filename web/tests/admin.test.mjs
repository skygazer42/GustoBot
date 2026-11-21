import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "./load-typescript.mjs";

const api = loadTypeScript("../src/admin/api.ts");
const emptyPage = {
  domain: { id: "recipes", name: "菜谱空间", version: "1" },
  items: [], total: 0, offset: 0, limit: 6,
  stats: { total: 0, ready: 0, pending: 0, processing: 0, failed: 0, withdrawn: 0 }
};

test("source catalog preserves a real empty result and zero counts", () => {
  assert.deepEqual(api.parseSourcePage(emptyPage), emptyPage);
  for (const value of ["<html>proxy error</html>", {}, { ...emptyPage, stats: {} }, { ...emptyPage, total: -1 }, { ...emptyPage, items: [{}] }]) {
    assert.throws(() => api.parseSourcePage(value));
  }
});

test("graph properties preserve false, zero and an empty literal string", () => {
  assert.deepEqual(api.parseProperties('{"amount":0,"checked":false,"note":""}'), { amount: 0, checked: false, note: "" });
  for (const text of ["null", "[]", "not json", '{"nested":{}}', '{"empty":null}', '{"array":[]}']) assert.throws(() => api.parseProperties(text));
});

test("stored graph responses preserve real identities, empty graphs and scalar values", () => {
  const empty = { entities: [], relations: [], sources: [], total: 0, truncated: false, ontology_version: "v1" };
  assert.deepEqual(api.parseFactResult(empty), empty);
  const entity = { id: "one", type: "Equipment", name: "设备", aliases: [], properties: { count: 0, active: false, note: "" }, evidence: [] };
  const relation = { id: "edge", source_id: "one", target_id: "two", type: "CONNECTS", properties: {}, evidence: [] };
  const graph = { ...empty, entities: [entity, { ...entity, id: "two" }], relations: [relation], total: 2 };
  assert.deepEqual(api.parseFactResult(graph).entities[0].properties, entity.properties);
  for (const value of [{ ...graph, entities: [entity, entity] }, { ...graph, relations: [relation, relation] },
    { ...graph, relations: [{ ...relation, target_id: "missing" }] }, { ...graph, total: -1 },
    { ...graph, entities: [{ ...entity, evidence: [{}] }] }, { ...graph, entities: [{ ...entity, properties: { nested: {} } }] }]) {
    assert.throws(() => api.parseFactResult(value));
  }
});

test("graph overview requests real relationships, isolated entities and bounded neighbor expansion", async () => {
  const requests = [];
  const empty = { entities: [], relations: [], sources: [], total: 0, truncated: false, ontology_version: "v1" };
  const local = loadTypeScript("../src/admin/api.ts", { axios: { create: () => ({ post(path, body, config) {
    requests.push({ path, body, config }); return Promise.resolve({ data: empty });
  } }) } });
  const signal = new AbortController().signal;
  const definition = { allowed_edges: { CONNECTS: {}, SUPPORTS: {} } };
  await local.queryGraph(definition, "", "", signal);
  await local.queryGraph(definition, "Equipment", "one", signal);
  assert.deepEqual(requests[0].body, { relation_types: ["CONNECTS", "SUPPORTS"], include_anchors: true, max_hops: 1, limit: 100 });
  assert.deepEqual(requests[1].body.anchor_ids, ["one"]);
  assert.equal(requests[1].body.entity_type, "Equipment");
  assert.equal(requests[0].config.signal, signal);
  assert.equal(requests[0].path, "/ontology/query");
});

test("a structured recipe must be a JSON object", () => {
  assert.deepEqual(api.parseRecipeRecord('{"主食材":[["番茄","2个"]]}'), { 主食材: [["番茄", "2个"]] });
  for (const value of ["false", "[]", "null", "{"]) assert.throws(() => api.parseRecipeRecord(value));
});

test("publication states do not turn failures into ready sources", () => {
  assert.equal(api.sourceState({ status: "graph_ready" }), "ready");
  assert.equal(api.sourceState({ status: "failed" }), "failed");
  assert.equal(api.sourceState({ status: "withdrawn" }), "withdrawn");
  assert.equal(api.stateLabel("failed"), "入库失败");
});

test("detail requests send only the exact identity, without list fields", async () => {
  let received;
  const client = {
    get(path, config) { received = { path, config }; return Promise.resolve({ data: { source: { source_id: " source/a ", version: "v1" }, text: "原文", jobs: [] } }); }
  };
  const local = loadTypeScript("../src/admin/api.ts", { axios: { create: () => client } });
  await local.readSource({ source_id: " source/a ", version: "v1", title: "清单字段不能变成查询参数", kind: "document" });
  assert.deepEqual(received.config.params, { source_id: " source/a ", version: "v1" });
  assert.equal(received.path, "/knowledge/admin/source");
});

test("document deletion confirms the latest version of the exact source identity", async () => {
  let received;
  const source = { source_id: " source/a ", version: "v1", title: "资料" };
  const local = loadTypeScript("../src/admin/api.ts", { axios: { create: () => ({
    delete(path, config) {
      received = { path, config };
      return Promise.resolve({ data: { source_id: source.source_id, versions: 2 } });
    }
  }) } });
  await local.deleteSource(source);
  assert.equal(received.path, "/knowledge/admin/source");
  assert.deepEqual(received.config.params, { source_id: source.source_id, version: source.version });
});

test("document deletion rejects an invalid receipt and preserves request failures", async () => {
  const failure = new Error("删除失败");
  const local = loadTypeScript("../src/admin/api.ts", { axios: { create: () => ({
    delete() { return Promise.reject(failure); }
  }) } });
  await assert.rejects(local.deleteSource({ source_id: "doc", version: "v1" }), (error) => error === failure);
  for (const data of [{}, { source_id: "other", versions: 1 }, { source_id: "doc", versions: 0 }, { source_id: "doc", versions: 1.5 }]) {
    const invalid = loadTypeScript("../src/admin/api.ts", { axios: { create: () => ({
      delete() { return Promise.resolve({ data }); }
    }) } });
    await assert.rejects(invalid.deleteSource({ source_id: "doc", version: "v1" }), /删除结果响应无效/);
  }
});

test("document editor reads the complete pinned source and saves only its editable fields", async () => {
  const content = { source_id: "doc/a", version: "v1", revision: "a".repeat(64), title: "完整文档", text: "正文".repeat(11000) };
  const requests = [];
  const receipt = { job_id: "revision-job", domain_id: "recipes", source_id: content.source_id,
    version: "v2", kind: "document", status: "ready", error: null, details: {} };
  const local = loadTypeScript("../src/admin/api.ts", { axios: { create: () => ({
    get(path, config) { requests.push({ path, config }); return Promise.resolve({ data: content }); },
    put(path, body, config) { requests.push({ path, body, config }); return Promise.resolve({ data: receipt }); }
  }) } });
  const signal = new AbortController().signal;
  assert.deepEqual(await local.readDocument(content, signal), content);
  assert.deepEqual(requests[0].config.params, { source_id: "doc/a", version: "v1" });
  assert.equal(requests[0].config.signal, signal);
  assert.equal(requests[0].path, "/knowledge/admin/document");
  assert.deepEqual(await local.updateDocument({ ...content, extra: "not editable" }), receipt);
  assert.deepEqual(requests[1].body, content);
  assert.equal(requests[1].path, "/knowledge/admin/document");
});

test("document editing preserves failures and rejects partial or mismatched results", async () => {
  const content = { source_id: "doc", version: "v1", revision: "a".repeat(64), title: "原文", text: "正文" };
  const failure = new Error("版本冲突");
  const failed = loadTypeScript("../src/admin/api.ts", { axios: { create: () => ({
    put() { return Promise.reject(failure); }
  }) } });
  await assert.rejects(failed.updateDocument(content), (error) => error === failure);
  for (const data of [null, { ...content, source_id: "other" }, { ...content, version: "v2" }, { ...content, text: null }, { ...content, revision: undefined }, { ...content, revision: "" }]) {
    const local = loadTypeScript("../src/admin/api.ts", { axios: { create: () => ({
      get() { return Promise.resolve({ data }); }
    }) } });
    await assert.rejects(local.readDocument(content, new AbortController().signal), /完整原文响应无效/);
  }
  for (const data of [{}, { source_id: "other", version: "v2", status: "ready", kind: "document" },
    { source_id: "doc", version: "v2", status: "failed", kind: "document" },
    { source_id: "doc", version: "v2", status: "processing", kind: "document" }]) {
    const local = loadTypeScript("../src/admin/api.ts", { axios: { create: () => ({
      put() { return Promise.resolve({ data }); }
    }) } });
    await assert.rejects(local.updateDocument(content), /未确认文档更新完成/);
  }
});

test("text submission retries keep the draft source identity", async () => {
  const bodies = [];
  const local = loadTypeScript("../src/admin/api.ts", { axios: { create: () => ({ post(path, body) { bodies.push(body); return Promise.resolve({ data: {} }); } }) } });
  await local.ingestText("手记", "同一段原文", "manual:one-draft");
  await local.ingestText("手记", "同一段原文", "manual:one-draft");
  assert.equal(bodies[0].source_id, bodies[1].source_id);
  assert.equal(bodies[0].source_id, "manual:one-draft");
});

test("formal validation errors remain visible at the API boundary", () => {
  const error = { isAxiosError: true, response: { data: { detail: { errors: ["关系的终点应为食材", "证据不属于当前原文"] } } } };
  assert.equal(api.errorMessage(error), "关系的终点应为食材；证据不属于当前原文");
});

test("question outcomes follow business status rather than HTTP success", () => {
  assert.equal(api.classifyAnswerStatus("needs_clarification").tone, "pending");
  assert.equal(api.classifyAnswerStatus("retrieval_unavailable").tone, "error");
  assert.equal(api.classifyAnswerStatus("no_results").label, "未找到匹配记录");
  assert.equal(api.classifyAnswerStatus("success").label, "已返回回答");
  assert.equal(api.classifyAnswerStatus(undefined).tone, "neutral");
  assert.equal(api.classifyAnswerStatus("unrecognized").tone, "neutral");
  assert.equal(api.classifyAnswerStatus("__proto__").tone, "neutral");
});
