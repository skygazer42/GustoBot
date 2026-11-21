export type ChatSource = Record<string, unknown>;

export interface RecipeReference {
  id: string;
  version: string;
  servings?: number;
}

export interface ChatRequest {
  message: string;
  session_id?: string;
  file_path?: string;
  recipe_id?: string;
  recipe_version?: string;
  recipe_servings?: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  delivery?: "pending" | "sent" | "failed";
  attachmentName?: string;
  route?: string | null;
  routeLogic?: string | null;
  sources?: ChatSource[];
  clarificationOptions?: { label: string; question: string }[];
}

export interface ChatState {
  isTyping: boolean;
  replyProgress: string;
  replyDraft: string;
  isUploading: boolean;
  sessionId: string;
  userInput: string;
  messages: ChatMessage[];
  uploadStatus: string;
  attachedFilePath: string;
  attachedFileName: string;
  error: string;
}

interface ChatResult {
  sessionId: string;
  message: ChatMessage;
}

type ChatRunUpdate = { progress: string } | { delta: string };

const chatStepLabels: Readonly<Record<string, string>> = {
  planning: "正在理解问题…",
  retrieving: "正在检索并核对资料…",
  reading_recipe: "正在读取当前菜谱…",
  reading_attachment: "正在处理附件…",
  answering: "正在组织回答…",
  saving: "正在保存对话…"
};

export class ChatRunError extends Error {
  constructor(readonly status: number) {
    super("对话请求未完成");
  }
}

export function createChatRunId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

// SSE frames can span network chunks, including a CRLF or a UTF-8 character.
async function* readChatEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<unknown> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let dataLines: string[] = [];
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      let lineEnd = buffer.indexOf("\n");
      while (lineEnd !== -1) {
        const line = buffer.slice(0, lineEnd).replace(/\r$/, "");
        buffer = buffer.slice(lineEnd + 1);
        if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).replace(/^ /, ""));
        } else if (line === "" && dataLines.length > 0) {
          const event: unknown = JSON.parse(dataLines.join("\n"));
          dataLines = [];
          yield event;
        }
        lineEnd = buffer.indexOf("\n");
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export async function requestChatRun(
  apiBaseUrl: string,
  request: ChatRequest,
  threadId: string,
  userMessageId: string,
  signal: AbortSignal,
  onUpdate: (update: ChatRunUpdate) => void
): Promise<ChatResult> {
  const { message, ...forwardedProps } = request;
  const runId = createChatRunId();
  const response = await fetch(`${apiBaseUrl}/api/v1/chat/ag-ui`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({
      threadId, runId, state: {}, tools: [], context: [],
      messages: [{ id: userMessageId, role: "user", content: message }],
      forwardedProps
    }),
    signal
  });
  if (!response.ok) throw new ChatRunError(response.status);
  if (response.body === null || !response.headers.get("Content-Type")?.includes("text/event-stream")) {
    throw new Error("对话流响应无效");
  }
  let messageId: string | null = null;
  for await (const event of readChatEvents(response.body)) {
    if (!isRecord(event)) throw new Error("对话事件无效");
    switch (event.type) {
      case "STEP_STARTED":
        if (typeof event.stepName === "string" && Object.prototype.hasOwnProperty.call(chatStepLabels, event.stepName)) {
          onUpdate({ progress: chatStepLabels[event.stepName] });
        }
        break;
      case "TEXT_MESSAGE_START":
        if (event.role === "assistant" && typeof event.messageId === "string") messageId = event.messageId;
        break;
      case "TEXT_MESSAGE_CONTENT":
        if (messageId !== null && event.messageId === messageId && typeof event.delta === "string") {
          onUpdate({ delta: event.delta });
        }
        break;
      case "TEXT_MESSAGE_END":
        if (event.messageId === messageId) messageId = null;
        break;
      case "RUN_ERROR":
        throw new ChatRunError(typeof event.code === "string" ? Number(event.code) : 0);
      case "RUN_FINISHED":
        if (event.threadId === threadId && event.runId === runId) return parseChatResponse(event.result);
        throw new Error("对话完成事件与当前请求不匹配");
    }
  }
  throw new Error("对话流未完成");
}

interface UploadedFile {
  path: string;
  name: string;
}

interface MessagePart {
  text: string;
  href?: string;
}

const backendLabels: Readonly<Record<string, string>> = {
  milvus: "Milvus",
  postgres: "PostgreSQL",
  external: "外部检索"
};

let nextMessageId = 0;

export function createMessageId(): string {
  nextMessageId += 1;
  return `message-${nextMessageId}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseUploadResponse(value: unknown, fallbackFileName: string): UploadedFile {
  if (
    !isRecord(value) ||
    value.success !== true ||
    typeof value.file_path !== "string" ||
    value.file_path.trim().length === 0
  ) {
    throw new Error("上传响应无效");
  }

  const { file_path: path, original_name: originalName } = value;
  const name = typeof originalName === "string" && originalName.length > 0
    ? originalName
    : fallbackFileName;
  return { path, name };
}

export function parseChatResponse(value: unknown): ChatResult {
  if (!isRecord(value)) {
    throw new Error("对话响应无效");
  }

  const { message, session_id: sessionId, route, route_logic: routeLogic, sources } = value;
  if (
    typeof message !== "string" ||
    message.trim().length === 0 ||
    typeof sessionId !== "string" ||
    sessionId.trim().length === 0 ||
    (route != null && typeof route !== "string") ||
    (routeLogic != null && typeof routeLogic !== "string")
  ) {
    throw new Error("对话响应无效");
  }
  if (sources != null && (!Array.isArray(sources) || !sources.every(isRecord))) {
    throw new Error("来源响应无效");
  }

  const options: { label: string; question: string }[] = [];
  const metadata = isRecord(value.metadata) ? value.metadata : undefined;
  let displayMessage = message;
  if (route === "clarification" && Array.isArray(metadata?.choices)) {
    metadata.choices.forEach((choice, index) => {
      if (!isRecord(choice) || typeof choice.id !== "string" || typeof choice.name !== "string") {
        throw new Error("做法候选响应无效");
      }
      const time = isRecord(choice.summary) && typeof choice.summary.cook_time === "string" ? choice.summary.cook_time : "";
      options.push({ label: `${index + 1}. ${choice.name}${time ? ` · ${time}` : ""}`, question: `第 ${index + 1} 份` });
    });
    if (options.length > 0) {
      displayMessage = "找到几份同名做法，先选定一份，我们再接着聊。";
    }
  } else if (route === "clarification" && isRecord(metadata?.plan) && Array.isArray(metadata.plan.unsupported_conditions)) {
    const conditions = metadata.plan.unsupported_conditions;
    if (conditions.length > 0 && conditions.every((condition) => typeof condition === "string")) {
      const names = conditions.map((condition: string) => condition.replace(/\s*[（(][^）)]*[）)]\s*/g, "").trim()).filter(Boolean);
      displayMessage = `关于“${names.join("、")}”，现有资料还不足以确认。可以先核对这份做法已有的用量或步骤，也可以补充资料后继续问。`;
    }
  }

  return {
    sessionId,
    message: {
      id: createMessageId(),
      role: "assistant",
      content: displayMessage,
      route: route ?? null,
      routeLogic: routeLogic ?? null,
      sources: sources ?? [],
      clarificationOptions: options
    }
  };
}

export function availablePrompts(prompts: readonly string[], messages: readonly ChatMessage[]): string[] {
  const asked = new Set(messages.filter((message) => message.role === "user" && message.delivery === "sent")
    .map((message) => message.content.trim().replace(/[？?。！!]+$/, "")));
  return prompts.filter((prompt) => !asked.has(prompt.trim().replace(/[？?。！!]+$/, "")));
}

export function linkify(text: string): MessagePart[] {
  return text.split(/(https?:\/\/[^\s<>"']+)/gi).map((part) => ({
    text: part,
    href: /^https?:\/\//i.test(part) ? part : undefined
  }));
}

function formatSourceValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

export function formatSource(source: Readonly<ChatSource>): string {
  const backendName = formatSourceValue(source.backend);
  const backend = backendName.toLowerCase();
  const backendLabel = Object.prototype.hasOwnProperty.call(backendLabels, backend)
    ? backendLabels[backend]
    : backendName;
  const name = formatSourceValue(source.name) || formatSourceValue(source.title);
  const origin = formatSourceValue(source.source) || formatSourceValue(source.url);
  const docId = formatSourceValue(source.document_id ?? source.id);

  const parts = [backendLabel, name, origin !== name ? origin : ""].filter(Boolean);
  let label = parts.join(" · ");
  if (docId.length > 0 && docId !== origin && docId !== name) {
    label += `${label.length > 0 ? " " : ""}（文档 ${docId}）`;
  }
  return label || JSON.stringify(source);
}

export function getSourceUrl(source: Readonly<ChatSource>): string | null {
  const url = formatSourceValue(source.url ?? source.source).trim();
  return /^https?:\/\//i.test(url) ? url : null;
}
