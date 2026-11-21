import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import { loadTypeScript } from "./load-typescript.mjs";

const require = createRequire(import.meta.url);
const vue = require("vue");

class FileInput {
  constructor(file) {
    this.files = [file];
    this.value = file.name;
  }
}

const chat = loadTypeScript("../src/lib/chat.ts");
const recipeData = loadTypeScript("../src/data/recipe.ts");

function createChat(recipeReference = null) {
  const requests = [];
  const axios = {
    post(url, body, config) {
      let resolve;
      let reject;
      const promise = new Promise((onResolve, onReject) => {
        resolve = (data) => onResolve({ data });
        reject = onReject;
      });
      requests.push({ url, body, config, resolve, reject });
      return promise;
    }
  };
  const fetchChat = (url, config) => new Promise((resolve, reject) => {
    const envelope = JSON.parse(config.body);
    const body = { message: envelope.messages[0].content, session_id: undefined, ...envelope.forwardedProps };
    const resultEvent = (result) => ({ type: "RUN_FINISHED", runId: envelope.runId, threadId: envelope.threadId, result });
    const headers = { "Content-Type": "text/event-stream" };
    requests.push({
      url, body, config, reject,
      resolve: (result) => resolve(new Response(`data: ${JSON.stringify(resultEvent(result))}\n\n`, { headers })),
      stream: () => {
        let writer;
        const bodyStream = new ReadableStream({ start: (controller) => { writer = controller; } });
        resolve(new Response(bodyStream, { headers }));
        return {
          push: (event) => writer.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\r\n\r\n`)),
          finish: (result) => {
            writer.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(resultEvent(result))}\n\n`));
            writer.close();
          },
          close: () => writer.close()
        };
      }
    });
  });
  const { useChat } = loadTypeScript("../src/composables/useChat.ts", {
    axios,
    vue,
    "../lib/chat": loadTypeScript("../src/lib/chat.ts", {}, { fetch: fetchChat })
  }, { HTMLInputElement: FileInput });
  const scope = vue.effectScope();
  const result = scope.run(() => useChat(recipeReference));
  return { ...result, requests, stop: () => scope.stop() };
}

function response(sessionId = "session-1", message = "真实回复") {
  return { message, session_id: sessionId, message_id: `reply-${sessionId}` };
}

function uploadResponse(name = "菜谱.txt", path = "/uploads/recipe.txt") {
  return { success: true, file_path: path, original_name: name };
}

function selectFile(name = "菜谱.txt") {
  const file = new File(["材料：鸡蛋一个"], name, { type: "text/plain" });
  const input = new FileInput(file);
  return { target: input };
}

test("serving quantities scale explicit numbers and preserve qualitative amounts", () => {
  assert.equal(recipeData.scaleQuantity("3", 3, 2), "4.5");
  assert.equal(recipeData.scaleQuantity("0", 4, 2), "0");
  for (const quantity of ["适量", "少许", "1–2", "1/2", "", null]) {
    assert.equal(recipeData.scaleQuantity(quantity, 4, 2), quantity);
  }
  assert.equal(recipeData.scaleQuantity("3", 4, null), "3");
  assert.equal(recipeData.scaleQuantity("3", null, 2), "3");
  assert.equal(recipeData.scaleQuantity(null, null, null), null);
});

test("suggestions exclude sent questions but remain available after a failed send", () => {
  const prompts = ["少油一点怎么做？", "只有一个鸡蛋呢？"];
  const messages = [
    { id: "sent", role: "user", delivery: "sent", content: " 少油一点怎么做? " },
    { id: "failed", role: "user", delivery: "failed", content: "只有一个鸡蛋呢？" }
  ];
  assert.deepEqual(chat.availablePrompts(prompts, messages), ["只有一个鸡蛋呢？"]);
  assert.deepEqual(chat.availablePrompts(prompts, [{ ...messages[0], delivery: "pending" }]), prompts);
});

test("clarification renders only actual recipe choices and keeps their order", () => {
  const parsed = chat.parseChatResponse({
    ...response(), route: "clarification",
    metadata: { choices: [
      { id: "variant-a", name: "番茄炒蛋", summary: { cook_time: "十分钟" } },
      { id: "variant-b", name: "番茄炒蛋", summary: {} }
    ] }
  });
  assert.deepEqual(parsed.message.clarificationOptions, [
    { label: "1. 番茄炒蛋 · 十分钟", question: "第 1 份" },
    { label: "2. 番茄炒蛋", question: "第 2 份" }
  ]);
  assert.doesNotMatch(parsed.message.content, /variant-a|variant-b/);
  assert.throws(() => chat.parseChatResponse({ ...response(), route: "clarification", metadata: { choices: [{ name: "缺少标识" }] } }));
});

test("unsupported preferences stay honest without exposing slot debugging text", () => {
  const parsed = chat.parseChatResponse({
    ...response(), route: "clarification",
    metadata: { plan: { unsupported_conditions: ["少油（低油用量偏好）"] } }
  });
  assert.match(parsed.message.content, /少油/);
  assert.match(parsed.message.content, /资料还不足以确认/);
  assert.doesNotMatch(parsed.message.content, /低油用量偏好|不粘锅|水炒/);
  assert.deepEqual(parsed.message.clarificationOptions, []);
});

test("each submission resolves current recipe servings without rewriting existing messages", async () => {
  let servings = 2;
  const client = createChat(() => ({ id: "recipe-a", version: "version-a", servings }));
  client.state.userInput = "用量是什么？";
  const first = client.sendMessage();
  assert.deepEqual(client.requests[0].body, {
    message: "用量是什么？", session_id: undefined,
    recipe_id: "recipe-a", recipe_version: "version-a", recipe_servings: 2
  });
  client.requests[0].resolve(response());
  await first;
  servings = 4;
  client.state.userInput = "现在呢？";
  const second = client.sendMessage();
  assert.equal(client.requests[1].body.message, "现在呢？");
  assert.equal(client.requests[1].body.recipe_servings, 4);
  assert.equal(client.requests[1].body.recipe_id, "recipe-a");
  assert.equal(client.requests[1].body.recipe_version, "version-a");
  assert.equal(client.state.messages[0].content, "用量是什么？");
  client.requests[1].resolve(response());
  await second;
  client.stop();
});

test("chat response preserves real sources and optional route fields", () => {
  const sources = [{ backend: "postgres", title: "食谱", url: "https://example.com/recipe" }];
  const parsed = chat.parseChatResponse({
    ...response(),
    route: "kb-query",
    route_logic: "知识库",
    sources
  });
  assert.equal(parsed.sessionId, "session-1");
  assert.equal(parsed.message.role, "assistant");
  assert.equal(parsed.message.content, "真实回复");
  assert.equal(parsed.message.routeLogic, "知识库");
  assert.deepEqual(parsed.message.sources, sources);
  assert.equal(typeof parsed.message.id, "string");
  assert.ok(parsed.message.id.length > 0);
});

test("chat response rejects malformed boundary data", () => {
  for (const value of [
    null,
    [],
    { ...response(), message: " " },
    { ...response(), session_id: " " },
    { ...response(), route: 2 },
    { ...response(), route_logic: {} },
    { ...response(), sources: {} },
    { ...response(), sources: [null] },
    { ...response(), sources: [[]] }
  ]) {
    assert.throws(() => chat.parseChatResponse(value));
  }
  assert.deepEqual(chat.parseChatResponse(response()).message.sources, []);
});

test("upload response requires success and a path and retains the selected filename fallback", () => {
  assert.deepEqual(chat.parseUploadResponse(uploadResponse(), "fallback.txt"), {
    name: "菜谱.txt",
    path: "/uploads/recipe.txt"
  });
  assert.equal(chat.parseUploadResponse({ success: true, file_path: "/uploads/file.txt" }, "本地.txt").name, "本地.txt");
  for (const value of [null, {}, { success: false, file_path: "x" }, { success: true, file_path: " " }]) {
    assert.throws(() => chat.parseUploadResponse(value, "本地.txt"));
  }
});

test("links allow only http and https and leave markup as ordinary text", () => {
  const parts = chat.linkify("<img src=x> javascript:alert(1) https://example.com/a http://example.org/b");
  assert.deepEqual(parts.filter((part) => part.href).map((part) => part.href), [
    "https://example.com/a",
    "http://example.org/b"
  ]);
  assert.equal(parts.map((part) => part.text).join(""), "<img src=x> javascript:alert(1) https://example.com/a http://example.org/b");
  for (const url of ["javascript:alert(1)", "data:text/html,<script>", "//example.com", "file:///tmp/a"]) {
    assert.equal(chat.getSourceUrl({ url }), null);
  }
  assert.equal(chat.getSourceUrl({ url: " https://example.com " }), "https://example.com");
  assert.equal(chat.getSourceUrl({ backend: "milvus", source: "https://zh.wikipedia.org/w/index.php?oldid=93383154" }), "https://zh.wikipedia.org/w/index.php?oldid=93383154");
  assert.equal(chat.getSourceUrl({ source: "preview://tomato-eggs" }), null);
});

test("source labels retain backend, title, origin and document identifiers", () => {
  assert.equal(chat.formatSource({ backend: "postgres", title: "鲁菜", source: "馆藏", document_id: 7 }), "PostgreSQL · 鲁菜 · 馆藏 （文档 7）");
  assert.equal(chat.formatSource({ title: "鲁菜", source: "鲁菜" }), "鲁菜");
  assert.equal(chat.formatSource({ custom: "source" }), '{"custom":"source"}');
});

test("suggestions fill or append a draft once without sending or truncating it", () => {
  const client = createChat();
  client.addQuestion("怎么做？");
  assert.equal(client.state.userInput, "怎么做？");
  client.addQuestion("需要多久？");
  assert.equal(client.state.userInput, "怎么做？\n需要多久？");
  client.addQuestion("需要多久？");
  assert.equal(client.state.userInput, "怎么做？\n需要多久？");
  assert.equal(client.requests.length, 0);
  const draft = "原".repeat(3999);
  client.state.userInput = draft;
  client.addQuestion("不能截断");
  assert.equal(client.state.userInput, draft);
  assert.match(client.state.error, /4000/);
  client.stop();
});

test("successful chat carries the session forward and uses stable distinct message IDs", async () => {
  const client = createChat();
  client.state.userInput = "  做法  ";
  const first = client.sendMessage();
  assert.equal(client.requests[0].url, "/api/v1/chat/ag-ui");
  assert.deepEqual(client.requests[0].body, { message: "做法", session_id: undefined });
  assert.equal(client.isBusy.value, true);
  const userId = client.state.messages[0].id;
  assert.equal(client.state.messages[0].delivery, "pending");
  assert.equal(client.state.messages[0].attachmentName, undefined);
  client.requests[0].resolve(response());
  await first;
  assert.equal(client.state.userInput, "");
  assert.equal(client.state.sessionId, "session-1");
  assert.equal(client.state.messages[0].id, userId);
  assert.equal(client.state.messages[0].delivery, "sent");
  assert.equal(client.state.messages[1].delivery, undefined);
  assert.equal(client.state.messages[1].attachmentName, undefined);
  assert.notEqual(client.state.messages[1].id, userId);
  client.state.userInput = "下一问";
  const next = client.sendMessage();
  assert.equal(client.requests[1].body.session_id, "session-1");
  client.requests[1].resolve(response("session-1", "下一答"));
  await next;
  assert.equal(new Set(client.state.messages.map((message) => message.id)).size, 4);
  client.stop();
});

test("selected recipes send exact identity and preserve the original question", async () => {
  const client = createChat({ id: "recipe-with-long-steps", version: "record-version" });
  client.state.userInput = "只有一个鸡蛋呢";
  const pending = client.sendMessage();
  assert.deepEqual(client.requests[0].body, {
    message: "只有一个鸡蛋呢", session_id: undefined,
    recipe_id: "recipe-with-long-steps", recipe_version: "record-version"
  });
  assert.equal(client.state.messages[0].content, "只有一个鸡蛋呢");
  client.requests[0].resolve(response());
  await pending;
  client.stop();
});

test("progress and partial reply are visible before completion and a broken stream can be retried", async () => {
  const client = createChat();
  client.state.userInput = "这道菜怎么做？";
  const first = client.sendMessage();
  const stream = client.requests[0].stream();
  stream.push({ type: "STEP_STARTED", stepName: "retrieving" });
  stream.push({ type: "TEXT_MESSAGE_START", role: "assistant", messageId: "preview" });
  stream.push({ type: "TEXT_MESSAGE_CONTENT", messageId: "preview", delta: "先准备食材" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(client.state.replyProgress, "正在检索并核对资料…");
  assert.equal(client.state.replyDraft, "先准备食材");
  assert.equal(client.state.messages.length, 1);
  stream.close();
  await first;
  assert.equal(client.state.replyDraft, "");
  assert.equal(client.state.messages[0].delivery, "failed");
  assert.equal(client.state.userInput, "这道菜怎么做？");
  const retry = client.sendMessage();
  client.requests[1].stream().finish({ ...response(), sources: [{ source: "菜谱原文" }] });
  await retry;
  assert.equal(client.state.messages.length, 2);
  assert.equal(client.state.messages[1].sources[0].source, "菜谱原文");
  assert.equal(client.state.replyProgress, "");
  client.stop();
});

test("a recipe reference getter can enter generic chat without sending stale recipe fields", async () => {
  let reference = { id: "recipe-a", version: "version-a", servings: 3 };
  const client = createChat(() => reference);
  client.state.userInput = "当前菜怎么做？";
  const selected = client.sendMessage();
  client.requests[0].resolve(response());
  await selected;

  client.resetSession();
  reference = null;
  client.state.userInput = "普通问题";
  const generic = client.sendMessage();
  assert.deepEqual(client.requests[1].body, {
    message: "普通问题", session_id: undefined
  });
  client.requests[1].resolve(response("generic-session"));
  await generic;
  client.stop();
});

test("switching recipes after reset aborts old requests and keeps the new recipe session", async () => {
  let reference = { id: "recipe-a", version: "version-a" };
  const client = createChat(() => reference);
  client.state.userInput = "第一道菜的问题";
  const previous = client.sendMessage();
  client.resetSession();
  reference = { id: "recipe-b", version: "version-b" };
  client.state.userInput = "第二道菜的问题";
  const current = client.sendMessage();
  assert.equal(client.requests[0].config.signal.aborted, true);
  assert.equal(client.requests[1].body.recipe_id, "recipe-b");
  assert.equal(client.requests[1].body.recipe_version, "version-b");
  assert.equal(client.requests[1].body.session_id, undefined);
  client.requests[0].resolve(response("old-recipe-session", "旧菜回复"));
  await previous;
  assert.equal(client.state.sessionId, "");
  assert.equal(client.state.messages.length, 1);
  assert.equal(client.state.isTyping, true);
  client.requests[1].resolve(response("new-recipe-session", "新菜回复"));
  await current;
  assert.equal(client.state.sessionId, "new-recipe-session");
  assert.deepEqual(client.state.messages.map((message) => message.content), ["第二道菜的问题", "新菜回复"]);
  client.stop();
});

test("selected recipes reject uploads and conflicting attachments before HTTP requests", async () => {
  const client = createChat({ id: "recipe-a", version: "version-a" });
  await client.onFileSelected(selectFile());
  assert.equal(client.requests.length, 0);
  assert.ok(client.state.error.length > 0);
  assert.equal(client.state.isUploading, false);

  client.state.userInput = "看看用量";
  client.state.attachedFilePath = "/uploads/existing.txt";
  client.state.attachedFileName = "已有附件.txt";
  await client.sendMessage();
  assert.equal(client.requests.length, 0);
  assert.equal(client.state.messages.length, 0);
  assert.equal(client.state.userInput, "看看用量");
  assert.equal(client.state.attachedFilePath, "/uploads/existing.txt");
  assert.ok(client.state.error.length > 0);
  client.stop();
});

test("oversized drafts stay intact while long valid questions use recipe references", async () => {
  const client = createChat({ id: "long-recipe", version: "full-record-version" });
  const draft = "原".repeat(4001);
  client.state.userInput = draft;
  await client.sendMessage();
  assert.equal(client.state.userInput, draft);
  assert.match(client.state.error, /4000/);
  assert.equal(client.requests.length, 0);
  assert.equal(client.state.messages.length, 0);
  client.state.userInput = "原".repeat(3500);
  const pending = client.sendMessage();
  assert.equal(client.state.userInput.length, 3500);
  assert.equal(client.requests.length, 1);
  assert.equal(client.requests[0].body.message, "原".repeat(3500));
  assert.equal(client.requests[0].body.recipe_id, "long-recipe");
  assert.equal(client.state.error, "");
  client.requests[0].resolve(response());
  await pending;
  client.stop();
});

test("failed chat keeps the draft and attachment and retry reuses the same user bubble", async () => {
  const client = createChat();
  client.state.userInput = "请分析这份食谱";
  client.state.attachedFilePath = "/uploads/recipe.txt";
  client.state.attachedFileName = "菜谱.txt";
  const first = client.sendMessage();
  const userId = client.state.messages[0].id;
  assert.equal(client.state.messages[0].delivery, "pending");
  assert.equal(client.state.messages[0].attachmentName, "菜谱.txt");
  assert.equal(client.requests[0].body.file_path, "/uploads/recipe.txt");
  assert.equal("ingest_incremental" in client.requests[0].body, false);
  assert.equal("delivery" in client.requests[0].body, false);
  assert.equal("attachmentName" in client.requests[0].body, false);
  client.requests[0].reject(new Error("network"));
  await first;
  assert.equal(client.state.messages.length, 1);
  assert.equal(client.state.messages[0].delivery, "failed");
  assert.equal(client.state.userInput, "请分析这份食谱");
  assert.equal(client.state.attachedFilePath, "/uploads/recipe.txt");
  assert.ok(client.state.error.length > 0);
  assert.equal(client.isBusy.value, false);
  const retry = client.sendMessage();
  assert.equal(client.state.messages.length, 1);
  assert.equal(client.state.messages[0].id, userId);
  assert.equal(client.state.messages[0].delivery, "pending");
  client.requests[1].resolve(response());
  await retry;
  assert.equal(client.state.messages.length, 2);
  assert.equal(client.state.messages[0].delivery, "sent");
  assert.equal(client.state.messages[0].attachmentName, "菜谱.txt");
  assert.equal(client.state.attachedFilePath, "");
  assert.equal(client.state.attachedFileName, "");
  assert.equal(client.state.error, "");
  client.stop();
});

test("editing a failed question preserves its failed status while a new question gets its own delivery state", async () => {
  const client = createChat();
  client.state.userInput = "没有发送成功的问题";
  const first = client.sendMessage();
  client.requests[0].reject(new Error("network"));
  await first;
  const failedId = client.state.messages[0].id;
  assert.equal(client.state.messages[0].delivery, "failed");
  client.state.userInput = "编辑后的新问题";
  const current = client.sendMessage();
  assert.equal(client.state.messages.length, 2);
  assert.equal(client.state.messages[0].id, failedId);
  assert.equal(client.state.messages[0].delivery, "failed");
  assert.notEqual(client.state.messages[1].id, failedId);
  assert.equal(client.state.messages[1].delivery, "pending");
  client.requests[1].resolve(response());
  await current;
  assert.equal(client.state.messages[0].delivery, "failed");
  assert.equal(client.state.messages[1].delivery, "sent");
  assert.equal(client.state.messages[2].delivery, undefined);
  client.stop();
});

test("an attachment name stays on its user message after the active attachment is removed and chat succeeds", async () => {
  const client = createChat();
  client.state.userInput = "分析文件";
  client.state.attachedFilePath = "/uploads/recipe.txt";
  client.state.attachedFileName = "原始菜谱.txt";
  const pending = client.sendMessage();
  assert.equal(client.state.messages[0].attachmentName, "原始菜谱.txt");
  client.removeAttachment();
  assert.equal(client.state.attachedFileName, "");
  assert.equal(client.state.messages[0].attachmentName, "原始菜谱.txt");
  client.requests[0].resolve(response());
  await pending;
  assert.equal(client.state.messages[0].delivery, "sent");
  assert.equal(client.state.messages[0].attachmentName, "原始菜谱.txt");
  client.stop();
});

test("malformed success is reported as a failure without a fake assistant reply", async () => {
  const client = createChat();
  client.state.userInput = "保留草稿";
  const pending = client.sendMessage();
  client.requests[0].resolve({ message: "missing session" });
  await pending;
  assert.equal(client.state.messages.length, 1);
  assert.equal(client.state.messages[0].delivery, "failed");
  assert.equal(client.state.userInput, "保留草稿");
  assert.ok(client.state.error.length > 0);
  client.stop();
});

test("a successful request preserves a draft edited while waiting", async () => {
  const client = createChat();
  client.state.userInput = "第一问";
  const pending = client.sendMessage();
  client.state.userInput = "等待期间写下的新问题";
  client.requests[0].resolve(response());
  await pending;
  assert.equal(client.state.userInput, "等待期间写下的新问题");
  assert.equal(client.state.messages.length, 2);
  client.stop();
});

test("reset aborts chat and ignores old success without clearing a newer request", async () => {
  const client = createChat();
  client.state.userInput = "旧会话";
  const old = client.sendMessage();
  client.resetSession();
  assert.equal(client.requests[0].config.signal.aborted, true);
  client.state.userInput = "新会话";
  const current = client.sendMessage();
  client.requests[0].resolve(response("old-session"));
  await old;
  assert.equal(client.state.sessionId, "");
  assert.equal(client.state.messages.length, 1);
  assert.equal(client.state.isTyping, true);
  assert.equal(client.state.messages[0].delivery, "pending");
  client.requests[1].resolve(response("new-session"));
  await current;
  assert.equal(client.state.sessionId, "new-session");
  assert.equal(client.state.messages[0].delivery, "sent");
  client.stop();
});

test("reset ignores old chat failures", async () => {
  const client = createChat();
  client.state.userInput = "旧会话";
  const old = client.sendMessage();
  client.resetSession();
  client.requests[0].reject(new Error("late failure"));
  await old;
  assert.equal(client.state.error, "");
  assert.equal(client.state.messages.length, 0);
  client.stop();
});

test("uploads use multipart file and a failed replacement retains the existing attachment", async () => {
  const client = createChat();
  const event = selectFile();
  const first = client.onFileSelected(event);
  assert.equal(client.requests[0].url, "/api/v1/upload/file");
  assert.equal(client.requests[0].body.get("file").name, "菜谱.txt");
  client.requests[0].resolve(uploadResponse());
  await first;
  assert.equal(event.target.value, "");
  assert.equal(client.state.attachedFileName, "菜谱.txt");
  const replacement = client.onFileSelected(selectFile("另一份.txt"));
  client.requests[1].reject(new Error("network"));
  await replacement;
  assert.equal(client.state.attachedFilePath, "/uploads/recipe.txt");
  assert.equal(client.state.attachedFileName, "菜谱.txt");
  assert.match(client.state.uploadStatus, /菜谱.txt/);
  assert.ok(client.state.error.length > 0);
  assert.equal(client.state.isUploading, false);
  client.stop();
});

test("removing an attachment cancels pending upload and ignores its late success", async () => {
  const client = createChat();
  const pending = client.onFileSelected(selectFile());
  client.removeAttachment();
  assert.equal(client.requests[0].config.signal.aborted, true);
  client.requests[0].resolve(uploadResponse());
  await pending;
  assert.equal(client.state.attachedFilePath, "");
  assert.equal(client.state.uploadStatus, "");
  assert.equal(client.state.isUploading, false);
  client.stop();
});

test("reset invalidates both successful and failed uploads", async () => {
  for (const outcome of ["resolve", "reject"]) {
    const client = createChat();
    const pending = client.onFileSelected(selectFile());
    client.resetSession();
    assert.equal(client.requests[0].config.signal.aborted, true);
    client.requests[0][outcome](outcome === "resolve" ? uploadResponse() : new Error("late failure"));
    await pending;
    assert.equal(client.state.attachedFilePath, "");
    assert.equal(client.state.error, "");
    assert.equal(client.state.uploadStatus, "");
    client.stop();
  }
});

test("scope disposal aborts requests and prevents all late chat and upload writes", async () => {
  for (const type of ["chat", "upload"]) {
    for (const outcome of ["resolve", "reject"]) {
      const client = createChat();
      client.state.userInput = "销毁前的问题";
      const pending = type === "chat" ? client.sendMessage() : client.onFileSelected(selectFile());
      client.stop();
      const snapshot = JSON.stringify(client.state);
      assert.equal(client.requests[0].config.signal.aborted, true);
      const data = type === "chat" ? response() : uploadResponse();
      client.requests[0][outcome](outcome === "resolve" ? data : new Error("late failure"));
      await pending;
      assert.equal(JSON.stringify(client.state), snapshot);
    }
  }
});
