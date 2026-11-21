import axios from "axios";
import type {
  ConversationFilters,
  ConversationMessage,
  ConversationMessagePage,
  ConversationPage,
  ConversationSummary,
  DocumentContent,
  DomainDefinition,
  Entity,
  Evidence,
  FactResult,
  GraphDraft,
  GraphWriteResult,
  IngestionReceipt,
  KnowledgeAnswer,
  KnowledgeGraph,
  Properties,
  Relation,
  SourceChunk,
  SourceDetail,
  SourceFilters,
  SourcePage,
  SourceSummary,
} from "./contracts";

const client = axios.create({ baseURL: "/api/v1", timeout: 15_000 });
const sessionPath = "/admin/session";
const operationTimeout = 180_000;

export async function readAdminSession(signal: AbortSignal) {
  const { data } = await client.get<unknown>(sessionPath, { signal });
  if (
    !isRecord(data) ||
    typeof data.authenticated !== "boolean" ||
    typeof data.configured !== "boolean"
  ) {
    throw new Error("无法读取登录状态。");
  }
  return { authenticated: data.authenticated, configured: data.configured };
}

export async function signIn(password: string, signal: AbortSignal): Promise<void> {
  await client.post(sessionPath, { password }, { signal });
}

export async function signOut(signal: AbortSignal): Promise<void> {
  await client.delete(sessionPath, { signal });
}

export function observeSessionExpiry(onExpiry: () => void): () => void {
  const handler = client.interceptors.response.use(undefined, (error: unknown) => {
    if (
      axios.isAxiosError(error) &&
      error.response?.status === 401 &&
      error.config?.url !== sessionPath
    ) {
      onExpiry();
    }
    return Promise.reject(error);
  });
  return () => client.interceptors.response.eject(handler);
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const body: unknown = error.response?.data;
    const detail = isRecord(body) ? body.detail : undefined;
    if (typeof detail === "string") return detail;
    if (isRecord(detail) && typeof detail.message === "string")
      return detail.message;
    if (
      isRecord(detail) &&
      Array.isArray(detail.errors) &&
      detail.errors.every((item) => typeof item === "string")
    )
      return detail.errors.join("；");
    if (Array.isArray(detail)) {
      return detail
        .filter(isRecord)
        .map((item) =>
          typeof item.msg === "string" ? item.msg : "输入字段无效",
        )
        .join("；");
    }
    return error.code === "ECONNABORTED"
      ? "等待服务响应超时。请刷新核对任务状态后再重试。"
      : "无法完成请求，请检查服务连接后重试。";
  }
  return error instanceof Error ? error.message : "操作失败，请重试。";
}

export function isCancelled(error: unknown): boolean {
  return axios.isCancel(error);
}

const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatAdminDate(value: string): string {
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`);
  return dateFormatter.format(date);
}

function isStoredDate(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function isConversationSummary(value: unknown): value is ConversationSummary {
  return isRecord(value) &&
    typeof value.id === "string" && value.id.length > 0 &&
    typeof value.title === "string" &&
    (value.user_id === null || typeof value.user_id === "string") &&
    isStoredDate(value.created_at) &&
    (value.updated_at === null || isStoredDate(value.updated_at)) &&
    typeof value.is_active === "boolean" &&
    Number.isInteger(value.message_count) && Number(value.message_count) >= 0 &&
    (value.last_message_preview === null || typeof value.last_message_preview === "string");
}

function isConversationMessage(value: unknown): value is ConversationMessage {
  return isRecord(value) &&
    Number.isInteger(value.id) && Number(value.id) > 0 &&
    typeof value.message_type === "string" &&
    typeof value.content === "string" &&
    (value.message_metadata === null || isRecord(value.message_metadata)) &&
    Number.isInteger(value.order_index) &&
    isStoredDate(value.created_at);
}

function hasPageBounds(value: Record<string, unknown>): boolean {
  return Number.isInteger(value.total) && Number(value.total) >= 0 &&
    Number.isInteger(value.offset) && Number(value.offset) >= 0 &&
    Number.isInteger(value.limit) && Number(value.limit) > 0;
}

export function parseConversationPage(value: unknown): ConversationPage {
  if (!isRecord(value) || !hasPageBounds(value) ||
    !Array.isArray(value.items) || !value.items.every(isConversationSummary)) {
    throw new Error("对话列表响应无效，请重试。");
  }
  return value as unknown as ConversationPage;
}

export function parseConversationMessages(value: unknown): ConversationMessagePage {
  if (!isRecord(value) || !hasPageBounds(value) || !isConversationSummary(value.session) ||
    !Array.isArray(value.items) || !value.items.every(isConversationMessage)) {
    throw new Error("对话消息响应无效，请重试。");
  }
  return value as unknown as ConversationMessagePage;
}

export async function listConversations(
  filters: ConversationFilters,
  signal: AbortSignal,
): Promise<ConversationPage> {
  const { data } = await client.get<unknown>("/admin/conversations", { params: filters, signal });
  return parseConversationPage(data);
}

export async function readConversationMessages(
  sessionId: string,
  offset: number,
  signal: AbortSignal,
): Promise<ConversationMessagePage> {
  const { data } = await client.get<unknown>(`/admin/conversations/${encodeURIComponent(sessionId)}/messages`, {
    params: { offset, limit: 50 }, signal,
  });
  const page = parseConversationMessages(data);
  if (page.session.id !== sessionId) throw new Error("对话消息与当前会话不一致，请重试。");
  return page;
}

export function parseSourcePage(value: unknown): SourcePage {
  if (
    !isRecord(value) ||
    !isRecord(value.domain) ||
    !isRecord(value.stats) ||
    !Array.isArray(value.items) ||
    ![value.domain.id, value.domain.name, value.domain.version].every(
      (field) => typeof field === "string",
    ) ||
    ![
      value.total,
      value.offset,
      value.limit,
      value.stats.total,
      value.stats.ready,
      value.stats.pending,
      value.stats.processing,
      value.stats.failed,
      value.stats.withdrawn,
    ].every((count) => Number.isInteger(count) && Number(count) >= 0) ||
    !value.items.every(
      (item) =>
        isRecord(item) &&
        typeof item.source_id === "string" &&
        typeof item.version === "string" &&
        typeof item.title === "string" &&
        typeof item.status === "string",
    )
  ) {
    throw new Error("资料列表响应无效，请重试。");
  }
  return value as unknown as SourcePage;
}

export function parseRecipeRecord(text: string): Record<string, unknown> {
  let record: unknown;
  try {
    record = JSON.parse(text);
  } catch {
    throw new Error("菜谱记录不是有效的 JSON。");
  }
  if (!isRecord(record)) throw new Error("菜谱记录应为一个 JSON 对象。");
  return record;
}

export function parseProperties(
  text: string,
): Record<string, string | number | boolean> {
  let record: Record<string, unknown>;
  try {
    record = parseRecipeRecord(text);
  } catch {
    throw new Error("属性需要有效的 JSON 对象。");
  }
  if (
    !Object.values(record).every(
      (value) =>
        ["string", "number", "boolean"].includes(typeof value) &&
        (typeof value !== "number" || Number.isFinite(value)),
    )
  ) {
    throw new Error("属性只支持文字、有限数值和布尔值。");
  }
  return record as Record<string, string | number | boolean>;
}

export async function listSources(
  filters: SourceFilters,
  signal?: AbortSignal,
): Promise<SourcePage> {
  const response = await client.get("/knowledge/admin/sources", {
    params: filters,
    signal,
  });
  return parseSourcePage(response.data);
}
export async function readSource(
  source: Pick<SourceSummary, "source_id" | "version">,
  signal?: AbortSignal,
): Promise<SourceDetail> {
  const { data } = await client.get<SourceDetail>("/knowledge/admin/source", {
    params: { source_id: source.source_id, version: source.version },
    signal,
  });
  if (
    !isRecord(data) ||
    !isRecord(data.source) ||
    typeof data.text !== "string" ||
    !Array.isArray(data.jobs)
  )
    throw new Error("资料详情响应无效。");
  return data;
}

export async function readSourceChunk(
  source: Pick<SourceSummary, "source_id" | "version">,
  number: number,
  signal: AbortSignal,
): Promise<SourceChunk> {
  const { data } = await client.get<SourceChunk>("/knowledge/admin/chunk", {
    params: { source_id: source.source_id, version: source.version, number },
    signal,
  });
  if (
    !isRecord(data) ||
    data.number !== number ||
    !Number.isSafeInteger(data.total) ||
    data.total < number ||
    typeof data.content !== "string"
  ) {
    throw new Error("切片响应无效，请重试。");
  }
  return data;
}
export async function retrySource(
  source: SourceSummary,
): Promise<IngestionReceipt> {
  return (
    await client.post<IngestionReceipt>(
      "/knowledge/admin/retry",
      { source_id: source.source_id, version: source.version },
      { timeout: operationTimeout },
    )
  ).data;
}
export async function readDocument(
  source: Pick<SourceSummary, "source_id" | "version">,
  signal: AbortSignal,
): Promise<DocumentContent> {
  const { data } = await client.get<unknown>("/knowledge/admin/document", {
    params: { source_id: source.source_id, version: source.version },
    signal,
  });
  if (
    !isRecord(data) ||
    data.source_id !== source.source_id ||
    data.version !== source.version ||
    typeof data.revision !== "string" || !/^[a-f0-9]{64}$/.test(data.revision) ||
    typeof data.title !== "string" ||
    typeof data.text !== "string"
  ) {
    throw new Error("完整原文响应无效，请重试。");
  }
  return {
    source_id: data.source_id, version: data.version, revision: data.revision,
    title: data.title, text: data.text,
  };
}
export async function updateDocument(document: Readonly<DocumentContent>): Promise<IngestionReceipt> {
  const { data } = await client.put<IngestionReceipt>(
    "/knowledge/admin/document",
    {
      source_id: document.source_id,
      version: document.version,
      revision: document.revision,
      title: document.title,
      text: document.text,
    },
    { timeout: operationTimeout },
  );
  if (
    !isRecord(data) ||
    data.source_id !== document.source_id ||
    typeof data.version !== "string" || data.version.length === 0 ||
    typeof data.job_id !== "string" || data.kind !== "document" ||
    data.status !== "ready" || data.error !== null
  ) {
    throw new Error("未确认文档更新完成，请刷新核对后重试。");
  }
  return data;
}
export async function withdrawSource(source: SourceSummary): Promise<void> {
  await client.delete(
    `/knowledge/sources/${encodeURIComponent(source.source_id)}`,
  );
}
export async function deleteSource(
  source: Pick<SourceSummary, "source_id" | "version">,
): Promise<void> {
  const { data } = await client.delete<unknown>("/knowledge/admin/source", {
    params: { source_id: source.source_id, version: source.version },
    timeout: operationTimeout,
  });
  if (
    !isRecord(data) ||
    data.source_id !== source.source_id ||
    !Number.isSafeInteger(data.versions) ||
    Number(data.versions) < 1
  ) {
    throw new Error("删除结果响应无效，请刷新目录核对。");
  }
}
export async function uploadDocument(file: File): Promise<string> {
  const body = new FormData();
  body.append("file", file);
  const { data } = await client.post("/upload/file", body, {
    timeout: operationTimeout,
  });
  if (
    !isRecord(data) ||
    data.success !== true ||
    typeof data.asset_id !== "string"
  )
    throw new Error("上传响应无效。");
  return data.asset_id;
}
export async function ingestDocument(
  assetId: string,
  title: string,
): Promise<IngestionReceipt> {
  return (
    await client.post<IngestionReceipt>(
      "/knowledge/documents",
      { asset_id: assetId, metadata: { title } },
      { timeout: operationTimeout },
    )
  ).data;
}
export async function ingestText(
  title: string,
  text: string,
  sourceId: string,
): Promise<IngestionReceipt> {
  return (
    await client.post<IngestionReceipt>(
      "/knowledge/documents",
      { text, uri: title, source_id: sourceId, metadata: { title } },
      { timeout: operationTimeout },
    )
  ).data;
}
export async function ingestRecipe(
  name: string,
  record: Record<string, unknown>,
): Promise<IngestionReceipt> {
  return (
    await client.post<IngestionReceipt>(
      "/knowledge/recipes",
      { name, record },
      { timeout: operationTimeout },
    )
  ).data;
}
export async function getDomain(
  signal?: AbortSignal,
): Promise<DomainDefinition> {
  const { data } = await client.get<DomainDefinition>("/ontology/domain", {
    signal,
  });
  if (
    !isRecord(data) ||
    !isRecord(data.classes) ||
    !isRecord(data.allowed_edges)
  )
    throw new Error("本体定义响应无效。");
  return data;
}
export async function sourceFacts(
  source: SourceSummary,
  signal?: AbortSignal,
): Promise<FactResult> {
  const { data } = await client.get<FactResult>(
    "/ontology/admin/source-facts",
    {
      params: {
        source_id: source.source_id,
        version: source.version,
        limit: 50,
      },
      signal,
    },
  );
  return parseFactResult(data);
}

function isGraphEvidence(value: unknown): value is Evidence {
  return isRecord(value) && typeof value.source_id === "string" && typeof value.quote === "string";
}

function isGraphProperties(value: unknown): value is Properties {
  return isRecord(value) && Object.values(value).every((item) =>
    typeof item === "string" || typeof item === "boolean" || typeof item === "number" && Number.isFinite(item),
  );
}

function isGraphEntity(value: unknown): value is Entity {
  return isRecord(value) && typeof value.id === "string" && value.id.length > 0 &&
    typeof value.type === "string" && typeof value.name === "string" &&
    Array.isArray(value.aliases) && value.aliases.every((alias) => typeof alias === "string") &&
    isGraphProperties(value.properties) && Array.isArray(value.evidence) && value.evidence.every(isGraphEvidence);
}

function isGraphRelation(value: unknown): value is Relation {
  return isRecord(value) && typeof value.id === "string" && value.id.length > 0 &&
    typeof value.source_id === "string" && typeof value.target_id === "string" && typeof value.type === "string" &&
    isGraphProperties(value.properties) && Array.isArray(value.evidence) && value.evidence.every(isGraphEvidence);
}

function isGraphSource(value: unknown): value is KnowledgeGraph["sources"][number] {
  return isRecord(value) && typeof value.id === "string" && typeof value.text === "string" &&
    (value.uri === null || typeof value.uri === "string");
}

export function parseFactResult(value: unknown): FactResult {
  if (!isRecord(value) || !Array.isArray(value.entities) || !value.entities.every(isGraphEntity) ||
    !Array.isArray(value.relations) || !value.relations.every(isGraphRelation) ||
    !Array.isArray(value.sources) || !value.sources.every(isGraphSource) ||
    typeof value.total !== "number" || !Number.isSafeInteger(value.total) || value.total < 0 ||
    typeof value.truncated !== "boolean" || typeof value.ontology_version !== "string") {
    throw new Error("图谱响应无效。");
  }
  const ids = new Set(value.entities.map((entity) => entity.id));
  const relationIds = new Set(value.relations.map((relation) => relation.id));
  if (ids.size !== value.entities.length || relationIds.size !== value.relations.length ||
    value.relations.some((relation) => !ids.has(relation.source_id) || !ids.has(relation.target_id))) {
    throw new Error("图谱响应中的实体或关系身份无效。");
  }
  return {
    entities: value.entities, relations: value.relations, sources: value.sources,
    total: value.total, truncated: value.truncated, ontology_version: value.ontology_version,
  };
}

export async function queryGraph(
  domain: DomainDefinition,
  entityType: string,
  anchorId: string,
  signal: AbortSignal,
): Promise<FactResult> {
  const { data } = await client.post<unknown>("/ontology/query", {
    relation_types: Object.keys(domain.allowed_edges), include_anchors: true, max_hops: 1, limit: 100,
    ...(entityType ? { entity_type: entityType } : {}),
    ...(anchorId ? { anchor_ids: [anchorId] } : {}),
  }, { signal });
  return parseFactResult(data);
}
export async function extractGraph(
  source: SourceSummary,
  signal?: AbortSignal,
): Promise<GraphDraft> {
  return (
    await client.post<GraphDraft>(
      "/ontology/admin/extract",
      { source_id: source.source_id, version: source.version },
      { signal, timeout: operationTimeout },
    )
  ).data;
}
export async function validateGraph(
  source: SourceSummary,
  graph: KnowledgeGraph,
  signal?: AbortSignal,
): Promise<GraphDraft> {
  return (
    await client.post<GraphDraft>(
      "/ontology/admin/validate",
      { source_id: source.source_id, version: source.version, graph },
      { signal, timeout: operationTimeout },
    )
  ).data;
}
export async function saveGraph(
  source: SourceSummary,
  graph: KnowledgeGraph,
  signal?: AbortSignal,
): Promise<GraphWriteResult> {
  return (
    await client.post<GraphWriteResult>(
      "/ontology/admin/facts",
      { source_id: source.source_id, version: source.version, graph },
      { signal, timeout: operationTimeout },
    )
  ).data;
}
export async function queryKnowledge(
  question: string,
  signal?: AbortSignal,
): Promise<KnowledgeAnswer> {
  const { data } = await client.post<KnowledgeAnswer>(
    "/knowledge/query",
    { question },
    { signal, timeout: operationTimeout },
  );
  if (
    !isRecord(data) ||
    typeof data.message !== "string" ||
    !Array.isArray(data.sources) ||
    !isRecord(data.metadata)
  )
    throw new Error("问答响应无效。");
  return data;
}

export function sourceState(
  source: Pick<SourceSummary, "status">,
): "ready" | "pending" | "withdrawn" | "failed" {
  if (source.status === "ready" || source.status === "graph_ready") return "ready";
  if (source.status === "withdrawn" || source.status === "failed") return source.status;
  return "pending";
}
export function stateLabel(status: string): string {
  const names: Record<string, string> = {
    ready: "可检索",
    graph_ready: "图谱已就绪",
    pending: "等待处理",
    processing: "处理中",
    failed: "入库失败",
    cancelled: "任务已取消",
    withdrawn: "已停止检索",
  };
  return names[status] ?? status;
}

export function classifyAnswerStatus(status: unknown): {
  label: string;
  tone: "ready" | "pending" | "error" | "neutral";
} {
  const states: Record<
    string,
    { label: string; tone: "ready" | "pending" | "error" | "neutral" }
  > = {
    success: { label: "已返回回答", tone: "ready" },
    needs_clarification: { label: "需要确认条件", tone: "pending" },
    retrieval_unavailable: { label: "本次查询未完成", tone: "error" },
    no_results: { label: "未找到匹配记录", tone: "pending" },
    partial: { label: "证据或结果不完整", tone: "pending" },
    unknown: { label: "当前记录不足以判断", tone: "pending" },
    uncertain: { label: "结果存在不确定性", tone: "pending" },
    non_comparable: { label: "记录暂不可比较", tone: "pending" },
    error: { label: "查询失败", tone: "error" },
    failed: { label: "查询失败", tone: "error" },
  };
  return typeof status === "string" &&
    Object.prototype.hasOwnProperty.call(states, status)
    ? states[status]
    : {
        label:
          typeof status === "string" && status
            ? `返回状态：${status}`
            : "已收到响应，需人工核对",
        tone: "neutral",
      };
}
