import axios from "axios";
import type {
  DomainDefinition,
  FactResult,
  GraphDraft,
  GraphWriteResult,
  IngestionReceipt,
  KnowledgeAnswer,
  KnowledgeGraph,
  SourceChunk,
  SourceDetail,
  SourceFilters,
  SourcePage,
  SourceSummary,
} from "./contracts";

const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const client = axios.create({ baseURL: `${base}/api/v1`, timeout: 15_000 });
const operationTimeout = 180_000;

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
export async function withdrawSource(source: SourceSummary): Promise<void> {
  await client.delete(
    `/knowledge/sources/${encodeURIComponent(source.source_id)}`,
  );
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
  if (
    !isRecord(data) ||
    !Array.isArray(data.entities) ||
    !Array.isArray(data.relations) ||
    !Array.isArray(data.sources)
  )
    throw new Error("图谱响应无效。");
  return data;
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
    withdrawn: "已撤回",
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
