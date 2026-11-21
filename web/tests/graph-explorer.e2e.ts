import { test } from "@e2e-dev/web";
import type { Browser, WebRoute } from "@e2e-dev/web";
import { expect } from "e2e";
import type { FactResult } from "../src/admin/contracts";

const domain = {
  id: "process", name: "工艺知识空间", version: "process-1", description: "工艺设备与材料关系", interpretation_notes: [],
  classes: Object.fromEntries([["Equipment", "设备"], ["Material", "材料"], ["ProcessStep", "工序"]].map(([type, label]) =>
    [type, { label, description: label, grain: "一条实体记录", properties: type === "Equipment"
      ? { temperature: { type: "number", required: false, description: "允许的温度", minimum: 0, maximum: 100 } } : {} }])),
  allowed_edges: { USES: { domain: ["Equipment"], range: ["Material"], description: "使用材料", properties: {} },
    PERFORMS: { domain: ["Equipment"], range: ["ProcessStep"], description: "执行工序", properties: {} } },
};
const evidence = [{ source_id: "process-notes", quote: "萃取釜使用乙醇，目标温度为0°C。" }];
const graph = {
  entities: [
    { id: "vessel", type: "Equipment", name: "萃取釜", aliases: ["提取设备"], properties: { temperature: 0, active: false }, evidence },
    { id: "solvent", type: "Material", name: "乙醇", aliases: [], properties: {}, evidence },
    { id: "step", type: "ProcessStep", name: "低温萃取", aliases: [], properties: {}, evidence },
  ],
  relations: [
    { id: "uses", source_id: "vessel", target_id: "solvent", type: "USES", properties: { amount: 0 }, evidence },
    { id: "performs", source_id: "vessel", target_id: "step", type: "PERFORMS", properties: {}, evidence },
  ],
  sources: [{ id: "process-notes", uri: "工艺记录.txt", text: evidence[0].quote }],
  total: 3, truncated: false, ontology_version: "process-1",
};
async function fulfill(route: WebRoute, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}
async function installGraph(browser: Browser) {
  const state = { failed: false, domainFailed: false, empty: false, truncated: false, queries: [] as Record<string, unknown>[] };
  await browser.route("**/api/v1/admin/session", (route) => fulfill(route, { authenticated: false, configured: false }));
  await browser.route("**/api/v1/ontology/domain", (route) => state.domainFailed
    ? fulfill(route, { detail: "本体定义暂时不可用" }, 503) : fulfill(route, domain));
  await browser.route("**/api/v1/ontology/query", (route) => {
    state.queries.push(JSON.parse(route.request.postData!) as Record<string, unknown>);
    if (state.failed) return fulfill(route, { detail: "图谱数据库暂时不可用" }, 503);
    return fulfill(route, state.empty ? { ...graph, entities: [], relations: [], sources: [], total: 0 }
      : { ...graph, truncated: state.truncated });
  });
  return state;
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`stored graph shows domain-neutral facts and evidence at ${viewport.width} pixels`, async ({ app, browser, screen }) => {
    await browser.setViewport(viewport);
    const state = await installGraph(browser);
    await app.open("/admin.html?view=ontology");
    await expect(screen.getByRole("heading", "已入库知识图谱", { exact: true })).toBeVisible();
    await expect(screen.getByRole("button", "实体：萃取釜（设备）", { exact: true })).toBeVisible();
    expect(state.queries[0].relation_types).toEqual(["USES", "PERFORMS"]);
    expect(state.queries[0].include_anchors).toBe(true);
    await screen.getByRole("button", "实体：萃取釜（设备）", { exact: true }).tap();
    await expect(browser.locator(".graph-inspector")).toContainText("temperature");
    await expect(browser.locator(".graph-properties")).toContainText("false");
    await expect(browser.locator(".graph-evidence").first()).toContainText("工艺记录.txt");
    await expect(browser.locator(".graph-evidence").first()).toContainText(evidence[0].quote);
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (viewport.width === 390) {
      expect(await browser.evaluate(() => {
        const canvas = document.querySelector(".graph-canvas")!.getBoundingClientRect();
        const names = [...document.querySelectorAll(".graph-node-name")].map((node) => node.getBoundingClientRect());
        return canvas.bottom <= window.innerHeight - 44 && names.every((name) => name.top >= 0 && name.bottom <= window.innerHeight);
      })).toBe(true);
      expect(await browser.evaluate(() => {
        const names = [...document.querySelectorAll(".graph-node-name")].map((node) => node.getBoundingClientRect());
        return [...document.querySelectorAll(".graph-edge-label")].some((label) => {
          const edge = label.getBoundingClientRect();
          return names.some((name) => edge.left < name.right && edge.right > name.left && edge.top < name.bottom && edge.bottom > name.top);
        });
      })).toBe(false);
    }
    await app.screenshot(`stored-graph-${viewport.width}`);
    await screen.getByRole("button", "关系：USES，萃取釜 → 乙醇", { exact: true }).tap();
    await expect(browser.locator(".graph-inspector")).toContainText("使用材料");
    await app.screenshot(`stored-relation-${viewport.width}`);
    if (viewport.width === 1440) {
      await screen.getByRole("button", "放大图谱", { exact: true }).tap();
      await expect(browser.locator(".graph-canvas-tools")).toContainText("125%");
      await screen.getByRole("button", "适应画布", { exact: true }).tap();
      await expect(browser.locator(".graph-canvas-tools")).toContainText("100%");
      await screen.getByRole("button", "实体：乙醇（材料）", { exact: true }).tap();
      await browser.keyboard.press("Tab");
      await browser.keyboard.press("Enter");
      await expect(browser.locator(".graph-inspector h3")).toHaveText("低温萃取");
    }
    const queryCount = state.queries.length;
    await screen.getByRole("button", "本体图谱", { exact: true }).tap();
    await expect(screen.getByRole("heading", "本体结构图", { exact: true })).toBeVisible();
    await expect(screen.getByRole("group", "本体类型关系图", { exact: true })).toBeVisible();
    await expect(browser.locator(".graph-node")).toHaveCount(3);
    await expect(browser.locator(".graph-edge")).toHaveCount(2);
    expect(state.queries.length).toBe(queryCount);
    await screen.getByRole("button", "类型：设备（Equipment）", { exact: true }).tap();
    await expect(screen.getByRole("complementary", "本体定义详情", { exact: true })).toContainText("允许的温度");
    await app.screenshot(`ontology-graph-${viewport.width}`);
    await screen.getByRole("button", "关系：USES，设备 → 材料", { exact: true }).tap();
    await expect(screen.getByRole("complementary", "本体定义详情", { exact: true })).toContainText("使用材料");
  });
}

test("graph empty, failure and truncation remain distinct and retryable", async ({ app, browser, screen }) => {
  const state = await installGraph(browser);
  state.empty = true;
  await app.open("/admin.html?view=ontology");
  await expect(screen.getByRole("heading", "还没有已入库的图谱事实", { exact: true })).toBeVisible();
  state.failed = true;
  await screen.getByRole("button", "刷新", { exact: true }).tap();
  await expect(screen.getByRole("alert")).toContainText("图谱数据库暂时不可用");
  state.failed = false;
  state.empty = false;
  state.truncated = true;
  await screen.getByRole("button", "重试图谱读取", { exact: true }).tap();
  await expect(browser.locator(".graph-workspace-footer")).toContainText("当前为部分事实视图");
  await screen.getByRole("button", "实体：萃取釜（设备）", { exact: true }).tap();
  await screen.getByRole("button", "查看出向关系", { exact: true }).tap();
  await expect(browser.locator(".graph-workspace-heading")).toContainText("一跳出向关系");
  await expect(screen.getByRole("button", "实体：萃取釜（设备）", { exact: true })).toBeVisible();
  expect(state.queries[state.queries.length - 1].anchor_ids).toEqual(["vessel"]);
  await app.screenshot("graph-truncated-neighborhood");
});

test("the graph page reports a failed ontology load and can retry", async ({ app, browser, screen }) => {
  const state = await installGraph(browser);
  state.domainFailed = true;
  await app.open("/admin.html?view=ontology");
  await expect(screen.getByRole("alert")).toContainText("本体定义暂时不可用");
  expect(state.queries.length).toBe(0);
  state.domainFailed = false;
  await screen.getByRole("button", "重试本体读取", { exact: true }).tap();
  await expect(screen.getByRole("button", "实体：萃取釜（设备）", { exact: true })).toBeVisible();
});

test("a late graph filter response cannot replace a newer scope", async ({ app, browser, screen }) => {
  await installGraph(browser);
  let release!: () => void;
  let announce!: () => void;
  let finish!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const started = new Promise<void>((resolve) => { announce = resolve; });
  const finished = new Promise<void>((resolve) => { finish = resolve; });
  await browser.route("**/api/v1/ontology/query", async (route) => {
    const body = JSON.parse(route.request.postData!) as { entity_type?: string };
    if (body.entity_type === "Equipment") {
      announce();
      await gate;
      try { await fulfill(route, graph); } finally { finish(); }
      return;
    }
    return fulfill(route, body.entity_type === "Material"
      ? { ...graph, entities: [graph.entities[1]], relations: [], total: 1 } : graph);
  });
  await app.open("/admin.html?view=ontology");
  await expect(browser.locator(".graph-node")).toHaveCount(3);
  await screen.getByLabel("起点类型", { exact: true }).selectOption({ value: "Equipment" });
  await started;
  await screen.getByLabel("起点类型", { exact: true }).selectOption({ value: "Material" });
  await expect(browser.locator(".graph-node")).toHaveCount(1);
  release();
  await finished;
  await expect(browser.locator(".graph-node")).toHaveCount(1);
  await expect(screen.getByRole("button", "实体：乙醇（材料）", { exact: true })).toBeVisible();
});

test("real stored facts render with their returned identities and evidence", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  const response = browser.waitForResponse("**/api/v1/ontology/query", { timeout: 30_000 });
  await app.open("/admin.html?view=ontology");
  const password = process.env.GUSTOBOT_TEST_ADMIN_PASSWORD;
  if (password) {
    await screen.getByLabel("管理员密码", { exact: true }).fill(password);
    await screen.getByRole("button", "登录", { exact: true }).tap();
  }
  const result = await response;
  expect(result.status).toBe(200);
  const facts = await result.json() as FactResult;
  expect(facts.entities.length > 0).toBe(true);
  expect(facts.relations.length > 0).toBe(true);
  await expect(browser.locator(".graph-node")).toHaveCount(facts.entities.length);
  await expect(browser.locator(".graph-edge")).toHaveCount(facts.relations.length);
  await app.screenshot("real-stored-graph");
  const relation = facts.relations[0];
  const source = facts.entities.find((entity) => entity.id === relation.source_id)!;
  const target = facts.entities.find((entity) => entity.id === relation.target_id)!;
  await screen.getByRole("button", `关系：${relation.type}，${source.name} → ${target.name}`, { exact: true }).first().tap();
  await expect(browser.locator(".graph-inspector h3")).toHaveText(facts.relations[0].type);
  await expect(browser.locator(".graph-evidence").first()).toBeVisible();
  await app.screenshot("real-stored-relation-evidence");
  await screen.getByRole("button", "本体图谱", { exact: true }).tap();
  await expect(screen.getByRole("heading", "本体结构图", { exact: true })).toBeVisible();
  await app.screenshot("real-ontology-definition");
});
