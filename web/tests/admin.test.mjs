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
