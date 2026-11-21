import { test } from "@e2e-dev/web";
import type { Browser, WebRoute } from "@e2e-dev/web";
import { expect } from "e2e";
import type { ConversationMessagePage, ConversationPage } from "../src/admin/contracts";

const conversation = {
  id: "conversation-a", title: "萃取工艺的温度记录", user_id: "device-a",
  created_at: "2026-11-20T08:00:00Z", updated_at: "2026-11-21T06:00:00Z",
  is_active: true, message_count: 2, last_message_preview: "记录要求目标温度为0°C。",
};
const messages = [
  { id: 1, session_id: conversation.id, message_type: "user_query", content: "这台设备的目标温度是多少？", message_metadata: null, order_index: 0, created_at: conversation.created_at },
  { id: 2, session_id: conversation.id, message_type: "agent_response", content: "记录要求目标温度为0°C。", message_metadata: { sources: [{ name: "工艺记录.txt", source_id: "source-a" }], model_calls: 0 }, order_index: 1, created_at: conversation.updated_at },
];
type StoredConversation = typeof conversation;
type StoredMessage = {
  id: number; session_id: string; message_type: string; content: string;
  message_metadata: Record<string, unknown> | null; order_index: number; created_at: string;
};

async function fulfill(route: WebRoute, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installHistory(browser: Browser) {
  const second = { ...conversation, id: "conversation-b", title: "设备清洗与维护", user_id: "device-b", last_message_preview: "清洗完成后需要核对密封圈。" };
  const state = {
    sessions: [conversation, second,
      { ...conversation, id: "conversation-deleted", title: "已结束的批次核对", is_active: false },
      { ...conversation, id: "conversation-empty", title: "尚未发送问题", message_count: 0, last_message_preview: null },
      ...Array.from({ length: 11 }, (_, index) => ({ ...conversation, id: `conversation-${index}`, title: `工艺批次记录 ${index + 1}` })),
    ] as Array<Omit<StoredConversation, "last_message_preview"> & { last_message_preview: string | null }>,
    messages: new Map<string, StoredMessage[]>([
      [conversation.id, messages],
      [second.id, messages.map((message) => ({ ...message, session_id: second.id, content: message.message_type === "user_query" ? "清洗后还需要检查什么？" : second.last_message_preview }))],
      ["conversation-empty", []],
    ]),
    listFailed: false,
    listGate: null as Promise<void> | null,
    failedMessages: new Set<string>(),
    gates: new Map<string, Promise<void>>(),
    listRequests: [] as Array<{ q: string; state: string; offset: number }>,
    messageRequests: [] as string[],
    unrelatedRequests: 0,
  };
  await browser.route("**/api/v1/admin/session", (route) => fulfill(route, { authenticated: false, configured: false }));
  await browser.route("**/api/v1/knowledge/**", (route) => { state.unrelatedRequests += 1; return fulfill(route, { detail: "不应读取文档目录" }, 500); });
  await browser.route("**/api/v1/ontology/**", (route) => { state.unrelatedRequests += 1; return fulfill(route, { detail: "不应读取图谱定义" }, 500); });
  await browser.route("**/api/v1/admin/conversations**", async (route) => {
    const url = new URL(route.request.url);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const limit = Number(url.searchParams.get("limit") ?? 12);
    if (url.pathname.endsWith("/messages")) {
      const id = decodeURIComponent(url.pathname.split("/").slice(-2)[0]);
      state.messageRequests.push(id);
      const session = state.sessions.find((item) => item.id === id);
      if (!session) return fulfill(route, { detail: "会话不存在" }, 404);
      const rows = state.messages.get(id) ?? [];
      const gate = state.gates.get(id);
      if (gate) await gate;
      if (state.failedMessages.has(id)) return fulfill(route, { detail: "消息暂时不可用" }, 503);
      return fulfill(route, { session, items: rows.slice(offset, offset + limit), total: rows.length, offset, limit });
    }
    if (state.listFailed) return fulfill(route, { detail: "会话列表暂时不可用" }, 503);
    const q = url.searchParams.get("q") ?? "";
    const filter = url.searchParams.get("state") ?? "all";
    state.listRequests.push({ q, state: filter, offset });
    if (state.listGate) await state.listGate;
    const matches = state.sessions.filter((session) => (
      !q || session.title.includes(q) || session.user_id?.includes(q)
      || state.messages.get(session.id)?.some((message) => message.content.includes(q))
    ) && (filter === "all" || session.is_active === (filter === "active")));
    return fulfill(route, { items: matches.slice(offset, offset + limit), total: matches.length, offset, limit });
  });
  return state;
}

test("stored conversations are reachable through the admin navigation", async ({ app, browser, screen }) => {
  const state = await installHistory(browser);
  await app.open("/admin.html?view=conversations");
  await expect(screen.getByRole("link", "对话记录", { exact: true })).toBeVisible();
  await expect(screen.getByRole("heading", "对话记录", { exact: true })).toBeVisible();
  await screen.getByRole("button", `查看对话：${conversation.title}`, { exact: true }).tap();
  await expect(browser.locator(".conversation-message-content")).toHaveCount(2);
  await expect(browser.locator(".conversation-workspace")).toContainText(messages[1].content);
  await screen.getByText("来源与执行信息", { exact: true }).tap();
  await expect(browser.locator(".conversation-workspace")).toContainText("工艺记录.txt");
  expect(state.unrelatedRequests).toBe(0);
});

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`conversation history is readable at ${viewport.width} pixels`, async ({ app, browser, screen }) => {
    await browser.setViewport(viewport);
    await installHistory(browser);
    await app.open("/admin.html?view=conversations");
    await expect(screen.getByRole("button", `查看对话：${conversation.title}`, { exact: true })).toBeVisible();
    await browser.evaluate(async () => { await document.fonts.ready; return null; });
    await app.screenshot(`history-list-${viewport.width}`);
    await screen.getByRole("button", `查看对话：${conversation.title}`, { exact: true }).tap();
    await expect(browser.locator(".conversation-message-content")).toHaveCount(2);
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await app.screenshot(`history-messages-${viewport.width}`);
    if (viewport.width === 390) {
      await screen.getByRole("button", "返回会话列表", { exact: true }).tap();
      await expect(screen.getByLabel("搜索对话", { exact: true })).toBeVisible();
      await expect(screen.getByRole("button", `查看对话：${conversation.title}`, { exact: true })).toHaveAttribute("aria-current", "true");
    }
  });
}

test("search and state filters reset list pagination and preserve their submitted scope", async ({ app, browser, screen }) => {
  const state = await installHistory(browser);
  await app.open("/admin.html?view=conversations");
  await expect(browser.locator(".conversation-list button")).toHaveCount(12);
  await screen.getByRole("button", "后一页会话", { exact: true }).tap();
  await expect(browser.locator(".conversation-list button")).toHaveCount(3);
  await screen.getByLabel("搜索对话", { exact: true }).fill("密封圈");
  await screen.getByRole("button", "搜索", { exact: true }).tap();
  await expect(browser.locator(".conversation-list button")).toHaveCount(1);
  await expect(browser.locator(".conversation-list")).toContainText("设备清洗与维护");
  expect(JSON.stringify(state.listRequests[state.listRequests.length - 1])).toBe(JSON.stringify({ q: "密封圈", state: "all", offset: 0 }));
  await screen.getByLabel("搜索对话", { exact: true }).fill("");
  await screen.getByRole("button", "搜索", { exact: true }).tap();
  await screen.getByLabel("会话状态", { exact: true }).selectOption({ value: "deleted" });
  await expect(browser.locator(".conversation-list button")).toHaveCount(1);
  await expect(browser.locator(".conversation-list")).toContainText("已结束的批次核对");
  expect(JSON.stringify(state.listRequests[state.listRequests.length - 1])).toBe(JSON.stringify({ q: "", state: "deleted", offset: 0 }));
});

test("list failures stay distinct from empty results and can be retried", async ({ app, browser, screen }) => {
  const state = await installHistory(browser);
  state.listFailed = true;
  await app.open("/admin.html?view=conversations");
  await expect(screen.getByRole("alert")).toContainText("会话列表暂时不可用");
  await expect(screen.getByText("还没有对话记录", { exact: true })).toHaveCount(0);
  await app.screenshot("history-list-error");
  state.listFailed = false;
  await screen.getByRole("button", "重试会话列表", { exact: true }).tap();
  await expect(browser.locator(".conversation-list button")).toHaveCount(12);
  state.sessions = [];
  await screen.getByRole("button", "刷新记录", { exact: true }).tap();
  await expect(screen.getByText("还没有对话记录", { exact: true })).toBeVisible();
  await app.screenshot("history-empty");
});

test("message errors can be retried and a real empty conversation has its own state", async ({ app, browser, screen }) => {
  const state = await installHistory(browser);
  state.failedMessages.add(conversation.id);
  await app.open("/admin.html?view=conversations");
  await screen.getByRole("button", `查看对话：${conversation.title}`, { exact: true }).tap();
  await expect(screen.getByRole("alert")).toContainText("消息暂时不可用");
  await expect(browser.locator(".conversation-message")).toHaveCount(0);
  state.failedMessages.clear();
  await screen.getByRole("button", "重试消息读取", { exact: true }).tap();
  await expect(browser.locator(".conversation-message-content")).toHaveCount(2);
  await screen.getByRole("button", "查看对话：尚未发送问题", { exact: true }).tap();
  await expect(screen.getByText("此会话暂无消息", { exact: true })).toBeVisible();
});

test("long transcripts page chronologically and render saved text as text", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1366, height: 768 });
  const state = await installHistory(browser);
  const literal = '<img src="invalid" onerror="window.historyInjected=true">';
  const rows = Array.from({ length: 52 }, (_, index): StoredMessage => ({
    id: index + 1, session_id: conversation.id, message_type: index % 2 ? "agent_response" : "user_query",
    content: index === 0 ? literal + "\n长记录需要保持完整可读。".repeat(70) : `第${index + 1}条消息`,
    message_metadata: null, order_index: index, created_at: conversation.created_at,
  }));
  state.messages.set(conversation.id, rows);
  state.sessions[0] = { ...state.sessions[0], message_count: rows.length };
  await app.open("/admin.html?view=conversations");
  await screen.getByRole("button", `查看对话：${conversation.title}`, { exact: true }).tap();
  await expect(browser.locator(".conversation-message-content")).toHaveCount(50);
  await expect(browser.locator(".conversation-message-content").nth(0)).toHaveText(rows[0].content);
  expect(await browser.evaluate(() => document.querySelectorAll(".conversation-message-content img").length)).toBe(0);
  await app.screenshot("history-long-transcript");
  await screen.getByRole("button", "更晚消息", { exact: true }).tap();
  await expect(browser.locator(".conversation-message-content")).toHaveCount(2);
  await expect(browser.locator(".conversation-message-content").nth(0)).toHaveText("第51条消息");
  await screen.getByRole("button", "更早消息", { exact: true }).tap();
  await expect(browser.locator(".conversation-message-content")).toHaveCount(50);
});

test("a delayed old transcript cannot overwrite the currently selected conversation", async ({ app, browser, screen }) => {
  const state = await installHistory(browser);
  let release!: () => void;
  state.gates.set(conversation.id, new Promise<void>((resolve) => { release = resolve; }));
  await app.open("/admin.html?view=conversations");
  await screen.getByRole("button", `查看对话：${conversation.title}`, { exact: true }).tap();
  await screen.getByRole("button", "查看对话：设备清洗与维护", { exact: true }).tap();
  await expect(browser.locator(".conversation-message-content").nth(1)).toHaveText("清洗完成后需要核对密封圈。");
  release();
  await browser.evaluate(async () => { await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))); return null; });
  await expect(browser.locator("#conversation-title")).toHaveText("设备清洗与维护");
  await expect(browser.locator(".conversation-message-content").nth(1)).toHaveText("清洗完成后需要核对密封圈。");
});

test("leaving during a refresh cannot start a transcript request after unmount", async ({ app, browser, screen }) => {
  const state = await installHistory(browser);
  await app.open("/admin.html?view=conversations");
  await screen.getByRole("button", `查看对话：${conversation.title}`, { exact: true }).tap();
  await expect(browser.locator(".conversation-message-content")).toHaveCount(2);
  let release!: () => void;
  state.listGate = new Promise<void>((resolve) => { release = resolve; });
  await screen.getByRole("button", "刷新记录", { exact: true }).tap();
  await expect(screen.getByRole("button", "刷新记录", { exact: true })).toBeDisabled();
  await screen.getByRole("link", "问答测试", { exact: true }).tap();
  await expect(screen.getByRole("heading", "问答测试", { exact: true })).toBeVisible();
  release();
  await browser.evaluate(async () => { await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))); return null; });
  expect(state.messageRequests.length).toBe(1);
});

test("real conversation history reads saved messages through the authenticated preview", async ({ app, browser, screen }) => {
  const password = process.env.GUSTOBOT_TEST_ADMIN_PASSWORD;
  if (!password) throw new Error("GUSTOBOT_TEST_ADMIN_PASSWORD is required for the real conversation history test.");
  await browser.setViewport({ width: 1440, height: 900 });
  const catalog = browser.waitForResponse("**/api/v1/admin/conversations?**");
  await app.open("/admin.html?view=conversations");
  await screen.getByLabel("管理员密码", { exact: true }).fill(password);
  await screen.getByRole("button", "登录", { exact: true }).tap();
  const returned = await catalog;
  expect(returned.status).toBe(200);
  const stored = await returned.json() as ConversationPage;
  const session = stored.items.find((item) => item.message_count > 0);
  if (!session) throw new Error("The preview needs one existing conversation with stored messages.");
  const transcript = browser.waitForResponse("**/api/v1/admin/conversations/*/messages?**");
  await screen.getByRole("button", `查看对话：${session.title}`, { exact: true }).tap();
  const detail = await transcript;
  expect(detail.status).toBe(200);
  const storedMessages = await detail.json() as ConversationMessagePage;
  expect(storedMessages.session.id).toBe(session.id);
  await expect(browser.locator(".conversation-message-content")).toHaveCount(storedMessages.items.length);
  await expect(browser.locator(".conversation-message-content").nth(0)).toHaveText(storedMessages.items[0].content);
  await app.screenshot("real-history-messages-1440");
  await browser.setViewport({ width: 390, height: 844 });
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(screen.getByRole("button", "返回会话列表", { exact: true })).toBeVisible();
  await app.screenshot("real-history-messages-390");
});
