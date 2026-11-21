import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "./load-typescript.mjs";

const api = loadTypeScript("../src/admin/api.ts");
const summary = {
  id: "conversation-a", title: "温度核对", user_id: null,
  created_at: "2026-11-21T08:00:00Z", updated_at: null,
  is_active: false, message_count: 0, last_message_preview: null,
};
const page = { items: [summary], total: 1, offset: 0, limit: 12 };

test("conversation pages preserve zero counts, inactive records and optional stored values", () => {
  assert.deepEqual(api.parseConversationPage(page), page);
  assert.deepEqual(api.parseConversationPage({ ...page, items: [], total: 0 }), { ...page, items: [], total: 0 });
  for (const value of ["<html>proxy failed</html>", {}, { ...page, total: -1 },
    { ...page, items: [{ ...summary, message_count: -1 }] },
    { ...page, items: [{ ...summary, is_active: "false" }] },
    { ...page, items: [{ ...summary, id: null }] }]) {
    assert.throws(() => api.parseConversationPage(value));
  }
});

test("stored messages preserve plain content and structured zero-valued metadata", () => {
  const message = { id: 1, message_type: "agent_response", content: "<b>0°C</b>",
    message_metadata: { model_calls: 0, checked: false, sources: [] }, order_index: 0,
    created_at: summary.created_at };
  const response = { session: { ...summary, message_count: 1 }, items: [message], total: 1, offset: 0, limit: 50 };
  assert.deepEqual(api.parseConversationMessages(response), response);
  assert.equal(api.parseConversationMessages({ ...response, items: [{ ...message, session_id: summary.id }] }).items[0].content, message.content);
  for (const value of [{ ...response, items: [{ ...message, content: null }] },
    { ...response, items: [{ ...message, message_metadata: [] }] },
    { ...response, items: [{ ...message, order_index: 0.5 }] },
    { ...response, session: null }, { ...response, offset: -1 }, { ...response, limit: 0 }]) {
    assert.throws(() => api.parseConversationMessages(value));
  }
});
