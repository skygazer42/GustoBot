export interface ConversationFilters {
  q: string;
  state: "all" | "active" | "deleted";
  offset: number;
  limit: number;
}

export interface ConversationSummary {
  id: string;
  title: string;
  user_id: string | null;
  created_at: string;
  updated_at: string | null;
  is_active: boolean;
  message_count: number;
  last_message_preview: string | null;
}

export interface ConversationPage {
  items: ConversationSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface ConversationMessage {
  id: number;
  message_type: string;
  content: string;
  message_metadata: Record<string, unknown> | null;
  order_index: number;
  created_at: string;
}

export interface ConversationMessagePage {
  session: ConversationSummary;
  items: ConversationMessage[];
  total: number;
  offset: number;
  limit: number;
}

export interface SourceFilters {
  q: string;
  state: "all" | "ready" | "pending" | "processing" | "failed" | "withdrawn";
  kind: "all" | "document" | "recipe";
  offset: number;
  limit: number;
}

export interface JobSummary {
  id: string;
  status: string;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourceSummary {
  domain_id: string;
  source_id: string;
  version: string;
  uri: string;
  title: string;
  kind: "document" | "recipe" | "unknown";
  status: string;
  ontology_version: string;
  created_at: string;
  updated_at: string;
  chunks: number | null;
  entities: number | null;
  relations: number | null;
  latest_job: JobSummary | null;
}

export interface SourcePage {
  domain: { id: string; name: string; version: string };
  items: SourceSummary[];
  total: number;
  offset: number;
  limit: number;
  stats: {
    total: number;
    ready: number;
    pending: number;
    processing: number;
    failed: number;
    withdrawn: number;
  };
}

export interface SourceChunk {
  number: number;
  total: number;
  content: string;
}

export interface DocumentContent {
  source_id: string;
  version: string;
  revision: string;
  title: string;
  text: string;
}

export interface SourceDetail {
  source: SourceSummary;
  text: string;
  text_truncated: boolean;
  jobs: (JobSummary & {
    details: Record<string, unknown>;
    source_version: string;
  })[];
}

export interface IngestionReceipt {
  job_id: string;
  domain_id: string;
  source_id: string;
  version: string;
  ontology_version: string;
  kind: "document" | "recipe";
  status: string;
  details: Record<string, unknown>;
  error: string | null;
}

export interface Evidence {
  source_id: string;
  quote: string;
}
export type Properties = Record<string, string | number | boolean>;
export interface Entity {
  id: string;
  type: string;
  name: string;
  aliases: string[];
  properties: Properties;
  evidence: Evidence[];
}
export interface Relation {
  id: string;
  source_id: string;
  target_id: string;
  type: string;
  properties: Properties;
  evidence: Evidence[];
}
export interface KnowledgeGraph {
  entities: Entity[];
  relations: Relation[];
  sources: { id: string; text: string; uri: string | null }[];
}
export interface FactResult extends KnowledgeGraph {
  total: number;
  truncated: boolean;
  ontology_version: string;
}
export interface GraphDraft {
  graph: KnowledgeGraph;
  validation: { valid: boolean; errors: string[] };
}
export interface GraphWriteResult {
  entities: number;
  relations: number;
  sources: number;
}
export interface PropertyDefinition {
  type: string;
  required: boolean;
  description: string;
  minimum?: number | null;
  maximum?: number | null;
}
export interface DomainDefinition {
  id: string;
  name: string;
  version: string;
  description: string;
  classes: Record<
    string,
    {
      label: string;
      description: string;
      grain: string;
      properties: Record<string, PropertyDefinition>;
    }
  >;
  allowed_edges: Record<
    string,
    {
      domain: string[];
      range: string[];
      description: string;
      properties: Record<string, PropertyDefinition>;
    }
  >;
  interpretation_notes: string[];
}
export interface KnowledgeAnswer {
  message: string;
  route: string;
  route_logic: string;
  sources: Record<string, unknown>[];
  metadata: Record<string, unknown>;
}
