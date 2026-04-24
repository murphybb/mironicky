export interface ApiErrorEnvelope {
  error_code?: string;
  message?: string;
  details?: Record<string, unknown>;
  trace_id?: string | null;
  request_id?: string | null;
  provider?: string | null;
  degraded?: boolean;
}

export class ResearchApiError extends Error {
  status: number;
  envelope: ApiErrorEnvelope;

  constructor(status: number, envelope: ApiErrorEnvelope, fallbackMessage: string) {
    super(envelope.message || fallbackMessage);
    this.name = 'ResearchApiError';
    this.status = status;
    this.envelope = envelope;
  }
}

export interface ListResponse<T> {
  items: T[];
  total: number;
}

export interface FactorBreakdown {
  factor_name: string;
  normalized_value: number;
  status?: string;
}

export interface MemoryRecallClaimRef {
  claim_id: string;
}

export interface MemoryRecallItem {
  memory_type: string;
  memory_id: string;
  score: number;
  title: string;
  snippet: string;
  timestamp?: string | null;
  linked_claim_refs: MemoryRecallClaimRef[];
  trace_refs: Record<string, unknown>;
}

export interface MemoryRecallResponse {
  status: string;
  requested_method: string;
  applied_method: string;
  reason?: string | null;
  query_text: string;
  total: number;
  items: MemoryRecallItem[];
  trace_refs: Record<string, unknown>;
}

export interface RouteRecord {
  route_id: string;
  workspace_id: string;
  title: string;
  summary: string;
  status: string;
  confidence_score: number;
  confidence_grade: 'low' | 'medium' | 'high' | string;
  top_factors: FactorBreakdown[];
  conclusion: string;
  key_supports: string[];
  assumptions: string[];
  risks: string[];
  next_validation_action: string;
  relation_tags: string[];
  route_node_ids?: string[];
  route_edge_ids?: string[];
  degraded?: boolean;
  stale?: boolean;
  claim_ids?: string[];
  challenge_status?: 'clean' | 'needs_review' | 'weakened' | 'challenged' | string;
  challenge_refs?: {
    conflict_count: number;
    conflict_ids: string[];
  };
  memory_recall?: MemoryRecallResponse | null;
}

export interface ClaimConflictRecord {
  conflict_id: string;
  workspace_id: string;
  new_claim_id: string;
  existing_claim_id: string;
  conflict_type: string;
  status: string;
  evidence: {
    new_text?: string;
    existing_text?: string;
    [key: string]: unknown;
  };
  source_ref: Record<string, unknown>;
  decision_note?: string | null;
  created_request_id?: string | null;
  resolved_request_id?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface GraphRAGCitation {
  claim_id: string;
  text: string;
  source_ref: Record<string, unknown>;
  score: number;
  graph_refs?: Record<string, unknown>;
  source_artifact_refs?: Record<string, unknown>[];
  retrieval_result_id?: string | null;
  view_type?: string | null;
  formal_refs?: Record<string, string>[];
  trace_refs?: Record<string, unknown>;
}

export interface GraphRAGResponse {
  workspace_id: string;
  question: string;
  answer: string;
  citations: GraphRAGCitation[];
  memory_recall: MemoryRecallResponse;
  trace_refs: Record<string, unknown>;
}

export interface IdSample {
  total: number;
  items: string[];
  truncated: boolean;
}

export interface CompactMappingSummary {
  keys: string[];
  total_keys: number;
  truncated: boolean;
}

export interface CrossDocumentClaimItem {
  claim_id: string;
  source_id: string;
  candidate_id: string;
  claim_type: string;
  semantic_type?: string | null;
  text: string;
  normalized_text: string;
  status: string;
  source_span: {
    start?: number | null;
    end?: number | null;
  };
  trace_summary: CompactMappingSummary;
  memory_summary: CompactMappingSummary;
}

export interface CrossDocumentConflictItem {
  conflict_id: string;
  new_claim_id: string;
  existing_claim_id: string;
  conflict_type: string;
  status: string;
  evidence: Record<string, unknown>;
  source_ref: Record<string, unknown>;
  decision_note?: string | null;
  created_request_id?: string | null;
  resolved_request_id?: string | null;
}

export interface CrossDocumentHistoricalRecallItem {
  recall_id: string;
  source_id: string;
  status: string;
  reason?: string | null;
  requested_method?: string | null;
  applied_method?: string | null;
  query_text: string;
  total: number;
  item_total: number;
  items: Array<{
    memory_id?: string | null;
    memory_type?: string | null;
    score?: number | null;
    title?: string | null;
    snippet?: string | null;
    linked_claim_refs: Array<{ claim_id?: string | null }>;
    source_ref: Record<string, unknown>;
  }>;
  items_truncated: boolean;
  trace_refs: CompactMappingSummary;
  error?: Record<string, unknown> | null;
  request_id?: string | null;
}

export interface CrossDocumentRouteBaseItem {
  route_id: string;
  title: string;
  summary: string;
  status: string;
  claim_ids: string[];
  route_node_ids: IdSample;
  route_edge_ids: IdSample;
}

export interface CrossDocumentRouteItem extends CrossDocumentRouteBaseItem {
  conclusion: string;
  version_id?: string | null;
  request_id?: string | null;
}

export interface CrossDocumentChallengedRouteItem extends CrossDocumentRouteBaseItem {
  challenge_status: string;
  challenge_refs: {
    conflict_count: number;
    conflict_ids: IdSample;
  };
}

export interface CrossDocumentUnresolvedGapItem {
  gap_type: string;
  status: string;
  conflict_id?: string | null;
  claim_ids: string[];
  recall_id?: string | null;
  source_id?: string | null;
  reason?: string | null;
  route_id?: string | null;
  conflict_ids?: IdSample | null;
}

export interface CrossDocumentReportResponse {
  workspace_id: string;
  summary: {
    claim_count: number;
    conflict_count: number;
    source_recall_count: number;
    route_count: number;
    challenged_route_count: number;
    unresolved_gap_count: number;
    section_limits: {
      claims: number;
      conflicts: number;
      historical_recall: number;
      routes: number;
      challenged_routes: number;
      unresolved_gaps: number;
    };
  };
  sections: {
    claims: CrossDocumentClaimItem[];
    conflicts: CrossDocumentConflictItem[];
    historical_recall: CrossDocumentHistoricalRecallItem[];
    routes: CrossDocumentRouteItem[];
    challenged_routes: CrossDocumentChallengedRouteItem[];
    unresolved_gaps: CrossDocumentUnresolvedGapItem[];
  };
  trace_refs: {
    request_id: string;
    claim_ids: IdSample;
    conflict_ids: IdSample;
    source_recall_ids: IdSample;
    route_ids: IdSample;
  };
}

export interface GraphNode {
  node_id: string;
  workspace_id: string;
  node_type: string;
  object_ref_type: string;
  object_ref_id: string;
  short_label: string;
  full_description: string;
  short_tags: string[];
  visibility: string;
  source_refs: unknown[];
  claim_id?: string | null;
  source_ref?: Record<string, unknown>;
  status: string;
  x?: number;
  y?: number;
}

export interface GraphEdge {
  edge_id: string;
  workspace_id: string;
  source_node_id: string;
  target_node_id: string;
  edge_type: string;
  object_ref_type: string;
  object_ref_id: string;
  strength: number;
  claim_id?: string | null;
  source_ref?: Record<string, unknown>;
  status: string;
}

export interface GraphResponse {
  workspace_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  memory_recall?: MemoryRecallResponse | null;
}

export interface CandidateRecord {
  candidate_id: string;
  workspace_id: string;
  source_id: string;
  candidate_batch_id?: string;
  candidate_type: string;
  semantic_type?: string | null;
  text: string;
  status: 'pending' | 'confirmed' | 'rejected' | string;
  source_span?: {
    desc?: string;
    mount?: string;
    text?: string;
    [key: string]: unknown;
  };
}

export interface FailureTargetRef {
  target_type: string;
  target_id: string;
}

export interface FailureRecord {
  failure_id: string;
  workspace_id: string;
  attached_targets?: FailureTargetRef[];
  observed_outcome: string;
  expected_difference: string;
  failure_reason: string;
  severity?: string;
  reporter?: string;
  created_at?: string;
  impact_summary?: Record<string, any>;
  impact_updated_at?: string | null;
  provenance?: Record<string, any>;
}

export interface PackageRecord {
  package_id: string;
  workspace_id: string;
  title: string;
  summary: string;
  status: string;
  traceability_refs?: Record<string, any>;
  replay_ready?: boolean;
}

export interface SourceRecord {
  source_id: string;
  workspace_id: string;
  source_type: string;
  title: string;
  content: string;
  status: string;
  metadata?: Record<string, unknown>;
  last_extract_job_id?: string | null;
  last_candidate_batch_id?: string | null;
  last_extract_status?: string | null;
  last_extract_error?: ApiErrorEnvelope | null;
  memory_recall?: MemoryRecallResponse | null;
  created_at?: string;
  updated_at?: string;
}

export interface WorkspaceSummaryRecord {
  workspace_id: string;
  source_count: number;
  candidate_count: number;
  node_count: number;
  edge_count: number;
  route_count: number;
  updated_at?: string | null;
}

export interface JobStatusResponse {
  job_id: string;
  job_type: string;
  status: string;
  workspace_id: string;
  request_id?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  result_ref?: { resource_type: string; resource_id: string } | null;
  error?: ApiErrorEnvelope | null;
}

export interface AsyncJobAcceptedResponse {
  job_id: string;
  job_type: string;
  status: string;
  workspace_id: string;
  status_url?: string;
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  timeoutMs?: number;
}

const JSON_HEADERS: Record<string, string> = {
  'Content-Type': 'application/json',
};
const REQUEST_TIMEOUT_MS = 15000;
const SOURCE_IMPORT_TIMEOUT_MS = 300000;
const JOB_SUCCESS_STATUSES = new Set(['succeeded', 'completed']);
const JOB_FAILURE_STATUSES = new Set(['failed', 'cancelled', 'canceled']);

export type AsyncJobUiState = 'running' | 'succeeded' | 'failed' | 'timeout' | 'unknown';

function normalizeJobStatus(status: unknown): string {
  return typeof status === 'string' ? status.trim().toLowerCase() : '';
}

export function getAsyncJobUiState(status?: string | null, errorCode?: string | null): AsyncJobUiState {
  const normalizedStatus = normalizeJobStatus(status);
  const normalizedError = String(errorCode || '').trim().toLowerCase();
  if (normalizedError === 'research.job_timeout' || normalizedError === 'research.request_timeout') {
    return 'timeout';
  }
  if (JOB_SUCCESS_STATUSES.has(normalizedStatus)) return 'succeeded';
  if (JOB_FAILURE_STATUSES.has(normalizedStatus)) return 'failed';
  if (!normalizedStatus) return 'unknown';
  return 'running';
}

export function getAsyncJobUiLabel(status?: string | null, errorCode?: string | null): string {
  const state = getAsyncJobUiState(status, errorCode);
  if (state === 'succeeded') return '已完成';
  if (state === 'failed') return '失败';
  if (state === 'timeout') return '前端轮询超时';
  if (state === 'running') return '处理中';
  return '未知';
}

function tryParseJson(raw: string): unknown {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function toErrorEnvelope(payload: unknown): ApiErrorEnvelope {
  if (!payload || typeof payload !== 'object') {
    return { message: typeof payload === 'string' ? payload : 'Request failed', details: {} };
  }
  const obj = payload as Record<string, unknown>;
  return {
    error_code: typeof obj.error_code === 'string' ? obj.error_code : undefined,
    message: typeof obj.message === 'string' ? obj.message : undefined,
    details: (obj.details as Record<string, unknown>) || {},
    trace_id: typeof obj.trace_id === 'string' ? obj.trace_id : null,
    request_id: typeof obj.request_id === 'string' ? obj.request_id : null,
    provider: typeof obj.provider === 'string' ? obj.provider : null,
    degraded: typeof obj.degraded === 'boolean' ? obj.degraded : undefined,
  };
}

async function request<T>(url: string, options: RequestOptions = {}): Promise<T> {
  const { body, headers, signal, timeoutMs = REQUEST_TIMEOUT_MS, ...rest } = options;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  if (signal) {
    if (signal.aborted) {
      controller.abort();
    } else {
      signal.addEventListener('abort', () => controller.abort(), { once: true });
    }
  }
  const init: RequestInit = {
    ...rest,
    headers: {
      ...(body === undefined ? {} : JSON_HEADERS),
      ...(headers || {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: controller.signal,
  };

  try {
    const response = await fetch(url, init);
    const raw = await response.text();
    const payload = tryParseJson(raw);

    if (!response.ok) {
      throw new ResearchApiError(response.status, toErrorEnvelope(payload), `HTTP ${response.status}`);
    }

    return payload as T;
  } catch (error) {
    if ((error as any)?.name === 'AbortError') {
      throw new ResearchApiError(
        408,
        {
          error_code: 'research.request_timeout',
          message: '璇锋眰瓒呮椂锛岃閲嶈瘯',
          details: { url, timeout_ms: timeoutMs },
        },
        'Request timed out'
      );
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

function normalizeRouteRecord(route: any): RouteRecord {
  const rawFactors = Array.isArray(route?.top_factors) ? route.top_factors : [];
  const topFactors: FactorBreakdown[] = rawFactors.map((f: any) => {
    const value = Number(f?.normalized_value ?? 0);
    const status = typeof f?.status === 'string' ? f.status : value >= 0 ? 'positive' : 'negative';
    return {
      factor_name: String(f?.factor_name ?? ''),
      normalized_value: value,
      status,
    };
  });

  return {
    route_id: String(route?.route_id ?? ''),
    workspace_id: String(route?.workspace_id ?? ''),
    title: String(route?.title ?? ''),
    summary: String(route?.summary ?? ''),
    status: String(route?.status ?? 'active'),
    confidence_score: Number(route?.confidence_score ?? 0),
    confidence_grade: String(route?.confidence_grade ?? 'low'),
    top_factors: topFactors,
    conclusion: String(route?.conclusion ?? ''),
    key_supports: Array.isArray(route?.key_supports) ? route.key_supports.map(String) : [],
    assumptions: Array.isArray(route?.assumptions) ? route.assumptions.map(String) : [],
    risks: Array.isArray(route?.risks) ? route.risks.map(String) : [],
    next_validation_action: String(route?.next_validation_action ?? ''),
    relation_tags: Array.isArray(route?.relation_tags) ? route.relation_tags.map(String) : [],
    route_node_ids: Array.isArray(route?.route_node_ids) ? route.route_node_ids.map(String) : [],
    route_edge_ids: Array.isArray(route?.route_edge_ids) ? route.route_edge_ids.map(String) : [],
    degraded: Boolean(route?.degraded),
    stale: Boolean(route?.stale),
    claim_ids: Array.isArray(route?.claim_ids) ? route.claim_ids.map(String) : [],
    challenge_status: String(route?.challenge_status ?? 'clean'),
    challenge_refs: {
      conflict_count: Number(route?.challenge_refs?.conflict_count ?? 0),
      conflict_ids: Array.isArray(route?.challenge_refs?.conflict_ids)
        ? route.challenge_refs.conflict_ids.map(String)
        : [],
    },
    memory_recall: normalizeMemoryRecall(route?.memory_recall),
  };
}

function normalizeMemoryRecall(recall: any): MemoryRecallResponse | null {
  if (!recall || typeof recall !== 'object') return null;
  const items = Array.isArray(recall?.items)
    ? recall.items.map((item: any) => ({
        memory_type: String(item?.memory_type ?? ''),
        memory_id: String(item?.memory_id ?? ''),
        score: Number(item?.score ?? 0),
        title: String(item?.title ?? ''),
        snippet: String(item?.snippet ?? ''),
        timestamp: item?.timestamp == null ? null : String(item.timestamp),
        linked_claim_refs: Array.isArray(item?.linked_claim_refs)
          ? item.linked_claim_refs
              .map((ref: any) => ({ claim_id: String(ref?.claim_id ?? '') }))
              .filter((ref: MemoryRecallClaimRef) => Boolean(ref.claim_id))
          : [],
        trace_refs: item?.trace_refs && typeof item.trace_refs === 'object' ? item.trace_refs : {},
      }))
    : [];

  return {
    status: String(recall?.status ?? ''),
    requested_method: String(recall?.requested_method ?? ''),
    applied_method: String(recall?.applied_method ?? ''),
    reason: recall?.reason == null ? null : String(recall.reason),
    query_text: String(recall?.query_text ?? ''),
    total: Number(recall?.total ?? items.length),
    items,
    trace_refs: recall?.trace_refs && typeof recall.trace_refs === 'object' ? recall.trace_refs : {},
  };
}

function normalizeSourceRecord(source: any): SourceRecord {
  return {
    ...source,
    source_id: String(source?.source_id ?? ''),
    workspace_id: String(source?.workspace_id ?? ''),
    source_type: String(source?.source_type ?? ''),
    title: String(source?.title ?? ''),
    content: String(source?.content ?? ''),
    status: String(source?.status ?? ''),
    metadata: source?.metadata && typeof source.metadata === 'object' ? source.metadata : {},
    last_extract_job_id: source?.last_extract_job_id == null ? null : String(source.last_extract_job_id),
    last_candidate_batch_id: source?.last_candidate_batch_id == null ? null : String(source.last_candidate_batch_id),
    last_extract_status: source?.last_extract_status == null ? null : String(source.last_extract_status),
    last_extract_error: source?.last_extract_error && typeof source.last_extract_error === 'object' ? source.last_extract_error : null,
    memory_recall: normalizeMemoryRecall(source?.memory_recall),
    created_at: source?.created_at == null ? undefined : String(source.created_at),
    updated_at: source?.updated_at == null ? undefined : String(source.updated_at),
  };
}

function normalizeGraph(graph: any): GraphResponse {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  const normalizedNodes = nodes.map((node: any, index: number) => ({
    ...node,
    x: Number.isFinite(node?.x) ? Number(node.x) : 120 + (index % 4) * 220,
    y: Number.isFinite(node?.y) ? Number(node.y) : 80 + Math.floor(index / 4) * 170,
    short_tags: Array.isArray(node?.short_tags) ? node.short_tags : [],
    source_refs: Array.isArray(node?.source_refs) ? node.source_refs : [],
    claim_id: node?.claim_id == null ? null : String(node.claim_id),
    source_ref: node?.source_ref && typeof node.source_ref === 'object' ? node.source_ref : {},
  }));
  const normalizedEdges = edges.map((edge: any) => ({
    ...edge,
    claim_id: edge?.claim_id == null ? null : String(edge.claim_id),
    source_ref: edge?.source_ref && typeof edge.source_ref === 'object' ? edge.source_ref : {},
  }));

  return {
    workspace_id: String(graph?.workspace_id ?? ''),
    nodes: normalizedNodes,
    edges: normalizedEdges as GraphEdge[],
    memory_recall: normalizeMemoryRecall(graph?.memory_recall),
  };
}

function normalizeCandidate(candidate: any): CandidateRecord {
  const sourceSpan = candidate?.source_span;
  const normalizedSourceSpan =
    sourceSpan && typeof sourceSpan === 'object'
      ? {
          ...sourceSpan,
          desc:
            (sourceSpan as any).desc ??
            (sourceSpan as any).description ??
            (sourceSpan as any).snippet ??
            '',
          mount:
            (sourceSpan as any).mount ??
            (sourceSpan as any).target ??
            (sourceSpan as any).mount_point ??
            '',
          text:
            (sourceSpan as any).text ??
            (sourceSpan as any).snippet ??
            (sourceSpan as any).desc ??
            '',
        }
      : undefined;

  return {
    candidate_id: String(candidate?.candidate_id ?? ''),
    workspace_id: String(candidate?.workspace_id ?? ''),
    source_id: String(candidate?.source_id ?? ''),
    candidate_batch_id: String(candidate?.candidate_batch_id ?? ''),
    candidate_type: String(candidate?.candidate_type ?? ''),
    semantic_type: candidate?.semantic_type == null ? null : String(candidate.semantic_type),
    text: String(candidate?.text ?? ''),
    status: String(candidate?.status ?? 'pending'),
    source_span: normalizedSourceSpan,
  };
}

function summarizeCandidateLabel(input: string, max = 56): string {
  const normalized = String(input || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '未命名节点';
  if (normalized.length <= max) return normalized;
  return `${normalized.slice(0, max)}...`;
}

function isNodeMatchedByCandidate(node: GraphNode, candidate: CandidateRecord): boolean {
  const candidateText = String(candidate?.text || '').trim();
  if (!candidateText) return false;
  const nodeLabel = String(node?.short_label || '').trim();
  const nodeDescription = String(node?.full_description || '').trim();
  if (!nodeLabel && !nodeDescription) return false;
  return (
    nodeDescription === candidateText ||
    nodeLabel === candidateText ||
    nodeLabel === summarizeCandidateLabel(candidateText)
  );
}

function buildCandidateSourceRef(candidate: CandidateRecord) {
  return {
    source_id: candidate.source_id,
    candidate_id: candidate.candidate_id,
    candidate_batch_id: candidate.candidate_batch_id || null,
    source_span: {
      desc: candidate.source_span?.desc || '',
      mount: candidate.source_span?.mount || '',
      text: candidate.source_span?.text || '',
    },
  };
}

function collectFailureIds(input: unknown, bucket: Set<string>) {
  if (!input) return;
  if (Array.isArray(input)) {
    for (const item of input) collectFailureIds(item, bucket);
    return;
  }
  if (typeof input !== 'object') return;

  const obj = input as Record<string, unknown>;
  const failureId = obj.failure_id;
  if (typeof failureId === 'string' && failureId.trim()) {
    bucket.add(failureId.trim());
  }

  const failureIds = obj.failure_ids;
  if (Array.isArray(failureIds)) {
    for (const id of failureIds) {
      if (typeof id === 'string' && id.trim()) bucket.add(id.trim());
    }
  }

  for (const key of Object.keys(obj)) {
    collectFailureIds(obj[key], bucket);
  }
}

function mapRetrievalItemToFailure(item: any, workspaceId: string, index: number): FailureRecord {
  return normalizeFailureRecord({
    failure_id: String(item?.result_id ?? `retrieval-failure-${index + 1}`),
    workspace_id: workspaceId,
    observed_outcome: String(item?.title ?? ''),
    expected_difference: String(item?.trace_refs?.date ?? item?.trace_refs?.observed_at ?? ''),
    failure_reason: String(item?.snippet ?? ''),
    severity: 'unknown',
    reporter: 'retrieval',
    attached_targets: [],
    impact_summary: {},
  });
}

function toStringArray(input: unknown): string[] {
  if (!Array.isArray(input)) return [];
  return input
    .map((item) => String(item || '').trim())
    .filter(Boolean);
}

function normalizeFailureImpactSummary(input: unknown, attachedTargets: FailureTargetRef[] = []) {
  const raw = input && typeof input === 'object' ? (input as Record<string, any>) : {};
  const attach =
    Array.isArray(raw.attach) && raw.attach.length > 0
      ? raw.attach
      : attachedTargets.map((target) => ({
          target_type: String(target?.target_type || ''),
          target_id: String(target?.target_id || ''),
        }));

  const invalidatedNodeIds = toStringArray(raw.invalidated_node_ids);
  const weakenedNodeIds = toStringArray(raw.weakened_node_ids);
  const invalidatedEdgeIds = toStringArray(raw.invalidated_edge_ids);
  const weakenedEdgeIds = toStringArray(raw.weakened_edge_ids);
  const createdGapNodeIds = toStringArray(raw.created_gap_node_ids);
  const createdBranchNodeIds = toStringArray(raw.created_branch_node_ids);
  const createdBranchEdgeIds = toStringArray(raw.created_branch_edge_ids);
  const affectedRouteIds = toStringArray(raw.affected_route_ids);

  const impact =
    Array.isArray(raw.impact) && raw.impact.length > 0
      ? raw.impact
      : [
          ...invalidatedNodeIds.map((id) => ({ kind: 'invalidated_node', id })),
          ...weakenedNodeIds.map((id) => ({ kind: 'weakened_node', id })),
          ...invalidatedEdgeIds.map((id) => ({ kind: 'invalidated_edge', id })),
          ...weakenedEdgeIds.map((id) => ({ kind: 'weakened_edge', id })),
          ...createdGapNodeIds.map((id) => ({ kind: 'gap_node', id })),
          ...createdBranchNodeIds.map((id) => ({ kind: 'branch_node', id })),
          ...createdBranchEdgeIds.map((id) => ({ kind: 'branch_edge', id })),
        ];

  const routes =
    Array.isArray(raw.routes) && raw.routes.length > 0
      ? raw.routes.map((route: any, index: number) => ({
          id: String(route?.id || route?.route_id || affectedRouteIds[index] || `route-${index + 1}`),
          name: String(route?.name || route?.title || route?.route_id || affectedRouteIds[index] || '未命名路线'),
          from: Number(route?.from ?? route?.score_before ?? route?.previous_score ?? 0),
          to: Number(route?.to ?? route?.score_after ?? route?.current_score ?? 0),
          status_before: route?.status_before ? String(route.status_before) : undefined,
          status_after: route?.status_after ? String(route.status_after) : undefined,
          impacted_edge_ids: toStringArray(route?.impacted_edge_ids),
          impacted_node_ids: toStringArray(route?.impacted_node_ids),
        }))
      : Array.isArray(raw.route_impacts) && raw.route_impacts.length > 0
      ? raw.route_impacts.map((route: any, index: number) => ({
          id: String(route?.route_id || affectedRouteIds[index] || `route-${index + 1}`),
          name: String(route?.title || route?.name || route?.route_id || affectedRouteIds[index] || '未命名路线'),
          from: Number(route?.from ?? route?.score_before ?? route?.previous_score ?? 0),
          to: Number(route?.to ?? route?.score_after ?? route?.current_score ?? 0),
          status_before: route?.status_before ? String(route.status_before) : undefined,
          status_after: route?.status_after ? String(route.status_after) : undefined,
          impacted_edge_ids: toStringArray(route?.impacted_edge_ids),
          impacted_node_ids: toStringArray(route?.impacted_node_ids),
        }))
      : affectedRouteIds.map((routeId) => ({
          id: routeId,
          name: routeId,
          from: 0,
          to: 0,
        }));

  return {
    ...raw,
    attach,
    impact,
    diff: {
      inv: Number(raw?.diff?.inv ?? invalidatedNodeIds.length),
      weak: Number(raw?.diff?.weak ?? weakenedEdgeIds.length),
      gap: Number(raw?.diff?.gap ?? createdGapNodeIds.length),
      branch: Number(raw?.diff?.branch ?? createdBranchNodeIds.length + createdBranchEdgeIds.length),
    },
    routes,
    invalidated_node_ids: invalidatedNodeIds,
    weakened_node_ids: weakenedNodeIds,
    invalidated_edge_ids: invalidatedEdgeIds,
    weakened_edge_ids: weakenedEdgeIds,
    affected_route_ids: affectedRouteIds,
    created_gap_node_ids: createdGapNodeIds,
    created_branch_node_ids: createdBranchNodeIds,
    created_branch_edge_ids: createdBranchEdgeIds,
  };
}

function normalizeFailureRecord(failure: any): FailureRecord {
  const attachedTargets = Array.isArray(failure?.attached_targets)
    ? failure.attached_targets.map((target: any) => ({
        target_type: String(target?.target_type ?? ''),
        target_id: String(target?.target_id ?? ''),
      }))
    : [];

  const provenance =
    failure?.provenance && typeof failure.provenance === 'object'
      ? failure.provenance
      : {
          ...(failure?.derived_from_validation_id ? { derived_from_validation_id: String(failure.derived_from_validation_id) } : {}),
          ...(failure?.derived_from_validation_result_id
            ? { derived_from_validation_result_id: String(failure.derived_from_validation_result_id) }
            : {}),
          ...(failure?.validation_id ? { validation_id: String(failure.validation_id) } : {}),
          ...(failure?.failure_source ? { failure_source: String(failure.failure_source) } : {}),
        };

  return {
    failure_id: String(failure?.failure_id ?? ''),
    workspace_id: String(failure?.workspace_id ?? ''),
    attached_targets: attachedTargets,
    observed_outcome: String(failure?.observed_outcome ?? ''),
    expected_difference: String(failure?.expected_difference ?? ''),
    failure_reason: String(failure?.failure_reason ?? ''),
    severity: failure?.severity ? String(failure.severity) : undefined,
    reporter: failure?.reporter ? String(failure.reporter) : undefined,
    created_at: failure?.created_at ? String(failure.created_at) : undefined,
    impact_summary: normalizeFailureImpactSummary(failure?.impact_summary, attachedTargets),
    impact_updated_at:
      failure?.impact_updated_at !== undefined && failure?.impact_updated_at !== null
        ? String(failure.impact_updated_at)
        : null,
    provenance,
  };
}

function describeError(error: unknown): Record<string, unknown> {
  if (error instanceof ResearchApiError) {
    return {
      status: error.status,
      error_code: error.envelope.error_code ?? null,
      message: error.message,
      details: error.envelope.details ?? {},
    };
  }
  if (error instanceof Error) return { message: error.message };
  return { message: String(error) };
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof ResearchApiError) {
    const message = String(error.message || '').trim();
    if (/crossref mailto is required/i.test(message)) {
      return '学术检索服务缺少 Crossref 联系邮箱配置（mailto）。请先在后端配置 crossref mailto 后重试。';
    }
    return message || '请求失败';
  }
  if (error instanceof Error) return error.message;
  return 'Unknown error';
}

export async function listRoutes(workspaceId: string): Promise<ListResponse<RouteRecord>> {
  const data = await request<ListResponse<any>>(`/api/v1/research/routes?workspace_id=${encodeURIComponent(workspaceId)}`);
  const items = Array.isArray(data?.items) ? data.items.map(normalizeRouteRecord) : [];
  return { items, total: Number(data?.total ?? items.length) };
}

export async function getRoute(routeId: string, workspaceId: string): Promise<RouteRecord> {
  const route = await request<any>(
    `/api/v1/research/routes/${encodeURIComponent(routeId)}?workspace_id=${encodeURIComponent(workspaceId)}`
  );
  return normalizeRouteRecord(route);
}

export async function generateRoutes(workspaceId: string, reason: string, maxCandidates?: number) {
  return request<any>(`/api/v1/research/routes/generate`, {
    method: 'POST',
    body: {
      workspace_id: workspaceId,
      reason,
      ...(maxCandidates === undefined ? {} : { max_candidates: maxCandidates }),
    },
  });
}

export async function scoreRoute(
  routeId: string,
  workspaceOrPayload: string | { workspace_id: string; template_id?: string | null; focus_node_ids?: string[] },
  templateId?: string | null,
  focusNodeIds?: string[]
) {
  const payload =
    typeof workspaceOrPayload === 'string'
      ? {
          workspace_id: workspaceOrPayload,
          ...(templateId === undefined ? {} : { template_id: templateId }),
          ...(focusNodeIds === undefined ? {} : { focus_node_ids: focusNodeIds }),
        }
      : workspaceOrPayload;

  return request<RouteRecord>(`/api/v1/research/routes/${encodeURIComponent(routeId)}/score`, {
    method: 'POST',
    body: {
      workspace_id: payload.workspace_id,
      ...(payload.template_id === undefined ? {} : { template_id: payload.template_id }),
      ...(payload.focus_node_ids === undefined ? {} : { focus_node_ids: payload.focus_node_ids }),
    },
  });
}

export async function getRoutePreview(routeId: string, workspaceId: string): Promise<any> {
  return request<any>(
    `/api/v1/research/routes/${encodeURIComponent(routeId)}/preview?workspace_id=${encodeURIComponent(workspaceId)}`
  );
}

export async function getGraph(workspaceId: string): Promise<GraphResponse> {
  const data = await request<any>(`/api/v1/research/graph/${encodeURIComponent(workspaceId)}`);
  return normalizeGraph(data);
}

export async function queryGraph(workspaceId: string, centerNodeId: string, maxHops = 1): Promise<GraphResponse> {
  const data = await request<any>(`/api/v1/research/graph/${encodeURIComponent(workspaceId)}/query`, {
    method: 'POST',
    body: {
      center_node_id: centerNodeId,
      max_hops: maxHops,
    },
  });
  return normalizeGraph(data);
}

export async function getGraphSupportChains(workspaceId: string, conclusionNodeId: string, maxChains = 5) {
  return request<any>(`/api/v1/research/graph/${encodeURIComponent(workspaceId)}/support-chains`, {
    method: 'POST',
    body: {
      workspace_id: workspaceId,
      conclusion_node_id: conclusionNodeId,
      max_chains: maxChains,
    },
  });
}

export async function getGraphPredictedLinks(workspaceId: string, nodeId: string, topK = 8) {
  return request<any>(`/api/v1/research/graph/${encodeURIComponent(workspaceId)}/predicted-links`, {
    method: 'POST',
    body: {
      workspace_id: workspaceId,
      node_id: nodeId,
      top_k: topK,
    },
  });
}

export async function getGraphDeepChains(workspaceId: string, nodeId: string, maxChains = 5) {
  return request<any>(`/api/v1/research/graph/${encodeURIComponent(workspaceId)}/deep-chains`, {
    method: 'POST',
    body: {
      workspace_id: workspaceId,
      node_id: nodeId,
      max_chains: maxChains,
    },
  });
}

export async function getGraphReport(workspaceId: string) {
  return request<any>(`/api/v1/research/graph/${encodeURIComponent(workspaceId)}/report`);
}

export async function listClaimConflicts(workspaceId: string): Promise<ListResponse<ClaimConflictRecord>> {
  const data = await request<{ items: ClaimConflictRecord[] }>(`/api/v1/research/conflicts/${encodeURIComponent(workspaceId)}`);
  const items = Array.isArray(data?.items) ? data.items : [];
  return { items, total: items.length };
}

export async function queryGraphRAG(workspaceId: string, question: string): Promise<GraphRAGResponse> {
  return request<GraphRAGResponse>('/api/v1/research/graphrag/query', {
    method: 'POST',
    body: {
      workspace_id: workspaceId,
      question,
    },
  });
}

export async function getCrossDocumentReport(workspaceId: string): Promise<CrossDocumentReportResponse> {
  return request<CrossDocumentReportResponse>(`/api/v1/research/reports/${encodeURIComponent(workspaceId)}/cross-document`);
}

export async function listVersions(workspaceId?: string) {
  const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : '';
  return request<ListResponse<any>>(`/api/v1/research/versions${query}`);
}

export async function getVersionDiff(versionId: string, workspaceId?: string) {
  const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : '';
  return request<any>(`/api/v1/research/versions/${encodeURIComponent(versionId)}/diff${query}`);
}

export async function listCandidates(workspaceId: string): Promise<ListResponse<CandidateRecord>> {
  const data = await request<ListResponse<any>>(`/api/v1/research/candidates?workspace_id=${encodeURIComponent(workspaceId)}`);
  const items = Array.isArray(data?.items) ? data.items.map(normalizeCandidate) : [];
  return { items, total: Number(data?.total ?? items.length) };
}

export async function listSources(workspaceId: string): Promise<ListResponse<SourceRecord>> {
  const data = await request<ListResponse<any>>(`/api/v1/research/sources?workspace_id=${encodeURIComponent(workspaceId)}`);
  const items = Array.isArray(data?.items) ? data.items.map(normalizeSourceRecord) : [];
  return { items, total: Number(data?.total ?? items.length) };
}

export async function listWorkspaces(): Promise<ListResponse<WorkspaceSummaryRecord>> {
  return request<ListResponse<WorkspaceSummaryRecord>>('/api/v1/research/workspaces');
}

export async function confirmCandidates(workspaceId: string, candidateIds: string[]) {
  return request<{ updated_ids: string[]; status: string }>(`/api/v1/research/candidates/confirm`, {
    method: 'POST',
    body: { workspace_id: workspaceId, candidate_ids: candidateIds },
  });
}

export async function rejectCandidates(workspaceId: string, candidateIds: string[], reason: string) {
  return request<{ updated_ids: string[]; status: string }>(`/api/v1/research/candidates/reject`, {
    method: 'POST',
    body: { workspace_id: workspaceId, candidate_ids: candidateIds, reason },
  });
}

export async function importSource(payload: {
  workspace_id: string;
  source_type: string;
  title?: string;
  content?: string;
  source_input_mode?: 'auto' | 'manual_text' | 'url' | 'local_file';
  source_url?: string;
  local_file?: {
    file_name: string;
    file_content_base64?: string;
    local_path?: string;
    mime_type?: string;
  };
  metadata?: Record<string, unknown>;
}) {
  return request<any>(`/api/v1/research/sources/import`, {
    method: 'POST',
    body: payload,
    timeoutMs: SOURCE_IMPORT_TIMEOUT_MS,
  });
}

export async function extractSource(sourceId: string, workspaceId: string) {
  return request<JobStatusResponse>(`/api/v1/research/sources/${encodeURIComponent(sourceId)}/extract`, {
    method: 'POST',
    body: { workspace_id: workspaceId, async_mode: true },
  });
}

export async function lookupSourceScholarly(
  sourceId: string,
  workspaceOrPayload: string | { workspace_id: string; force_refresh?: boolean },
  forceRefresh?: boolean
) {
  const payload =
    typeof workspaceOrPayload === 'string'
      ? {
          workspace_id: workspaceOrPayload,
          ...(forceRefresh === undefined ? {} : { force_refresh: forceRefresh }),
        }
      : workspaceOrPayload;

  return request<any>(`/api/v1/research/sources/${encodeURIComponent(sourceId)}/scholarly/lookup`, {
    method: 'POST',
    body: {
      workspace_id: payload.workspace_id,
      ...(payload.force_refresh === undefined ? {} : { force_refresh: payload.force_refresh }),
    },
  });
}

export async function getExtractionResult(sourceId: string, candidateBatchId: string, workspaceId?: string) {
  const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : '';
  return request<any>(
    `/api/v1/research/sources/${encodeURIComponent(sourceId)}/extraction-results/${encodeURIComponent(candidateBatchId)}${query}`
  );
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  return request<JobStatusResponse>(`/api/v1/research/jobs/${encodeURIComponent(jobId)}`);
}

export async function pollJob(jobId: string, timeoutMs = 30000, intervalMs = 1000) {
  const deadline = Date.now() + timeoutMs;
  let last = await getJobStatus(jobId);

  while (Date.now() < deadline) {
    const status = normalizeJobStatus(last.status);
    if (JOB_SUCCESS_STATUSES.has(status)) return last;
    if (JOB_FAILURE_STATUSES.has(status)) {
      throw new ResearchApiError(
        409,
        {
          ...(last.error || {}),
          error_code: last.error?.error_code || 'research.job_failed',
          message: last.error?.message || `job ${jobId} ${status}`,
          details: {
            ...(last.error?.details || {}),
            job_id: jobId,
            status: last.status,
            job_type: last.job_type,
            workspace_id: last.workspace_id,
          },
        },
        `job ${jobId} ${status}`
      );
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    last = await getJobStatus(jobId);
  }

  throw new ResearchApiError(
    408,
    {
      error_code: 'research.job_timeout',
      message: '鍓嶇杞瓒呮椂锛屼换鍔″彲鑳戒粛鍦ㄥ悗鍙板鐞嗕腑',
      details: {
        job_id: jobId,
        last_status: last.status,
        timeout_ms: timeoutMs,
      },
    },
    '鍓嶇杞瓒呮椂锛屼换鍔″彲鑳戒粛鍦ㄥ悗鍙板鐞嗕腑'
  );
}

export async function createGraphNode(payload: {
  workspace_id: string;
  node_type: string;
  object_ref_type: string;
  object_ref_id: string;
  short_label: string;
  full_description: string;
  short_tags?: string[];
  visibility?: string;
  source_refs?: Record<string, unknown>[];
  claim_id: string;
}) {
  return request<GraphNode>(`/api/v1/research/graph/nodes`, {
    method: 'POST',
    body: payload,
  });
}

export async function patchGraphNode(nodeId: string, payload: Record<string, unknown>) {
  return request<GraphNode>(`/api/v1/research/graph/nodes/${encodeURIComponent(nodeId)}`, {
    method: 'PATCH',
    body: payload,
  });
}

export async function deleteGraphNode(nodeId: string, workspaceId: string, reason = 'ui_archive') {
  return request<{ node_id?: string; status?: string }>(`/api/v1/research/graph/nodes/${encodeURIComponent(nodeId)}`, {
    method: 'DELETE',
    body: { workspace_id: workspaceId, reason },
  });
}

export async function createGraphEdge(payload: {
  workspace_id: string;
  source_node_id: string;
  target_node_id: string;
  edge_type: string;
  object_ref_type: string;
  object_ref_id: string;
  strength: number;
  claim_id: string;
}) {
  return request<GraphEdge>(`/api/v1/research/graph/edges`, {
    method: 'POST',
    body: payload,
  });
}

export async function hydrateConfirmedCandidatesToGraph(
  workspaceId: string,
  candidates: CandidateRecord[]
): Promise<{ patched_node_ids: string[]; patched_count: number }> {
  const confirmed = (Array.isArray(candidates) ? candidates : [])
    .filter((item) => String(item?.status || '').toLowerCase() === 'confirmed')
    .filter((item) => String(item?.candidate_id || '').trim() && String(item?.source_id || '').trim());
  if (confirmed.length === 0) {
    return { patched_node_ids: [], patched_count: 0 };
  }

  const graph = await getGraph(workspaceId);
  const patchedNodeIds: string[] = [];

  for (const node of graph.nodes) {
    const matched = confirmed.filter((candidate) => isNodeMatchedByCandidate(node, candidate));
    if (matched.length === 0) continue;

    const existingRefs = Array.isArray(node.source_refs) ? [...node.source_refs] : [];
    const existingCandidateIds = new Set(
      existingRefs
        .map((ref) => (ref && typeof ref === 'object' ? String((ref as any).candidate_id || '') : ''))
        .filter(Boolean)
    );
    let refsChanged = false;

    for (const candidate of matched) {
      if (existingCandidateIds.has(candidate.candidate_id)) continue;
      existingRefs.push(buildCandidateSourceRef(candidate));
      existingCandidateIds.add(candidate.candidate_id);
      refsChanged = true;
    }

    const currentLabel = String(node.short_label || '').trim();
    const preferredLabel = summarizeCandidateLabel(
      currentLabel || matched[0].text || node.full_description || ''
    );
    const labelChanged = preferredLabel !== currentLabel;

    if (!refsChanged && !labelChanged) continue;

    await patchGraphNode(node.node_id, {
      workspace_id: workspaceId,
      short_label: preferredLabel,
      source_refs: existingRefs,
    });
    patchedNodeIds.push(node.node_id);
  }

  return { patched_node_ids: patchedNodeIds, patched_count: patchedNodeIds.length };
}

export async function deleteGraphEdge(edgeId: string, workspaceId: string, reason = 'ui_archive') {
  return request<{ edge_id?: string; status?: string }>(`/api/v1/research/graph/edges/${encodeURIComponent(edgeId)}`, {
    method: 'DELETE',
    body: { workspace_id: workspaceId, reason },
  });
}

export async function recomputeRoutes(workspaceId: string, reason: string, failureId?: string) {
  return request<JobStatusResponse>(`/api/v1/research/routes/recompute`, {
    method: 'POST',
    headers: { 'x-research-llm-allow-fallback': 'true' },
    body: {
      workspace_id: workspaceId,
      reason,
      failure_id: failureId ?? null,
      async_mode: true,
    },
  });
}

export async function listPackages(workspaceId: string): Promise<ListResponse<PackageRecord>> {
  return request<ListResponse<PackageRecord>>(`/api/v1/research/packages?workspace_id=${encodeURIComponent(workspaceId)}`);
}

export async function publishPackage(packageId: string, workspaceId: string, asyncMode = true) {
  return request<AsyncJobAcceptedResponse>(`/api/v1/research/packages/${encodeURIComponent(packageId)}/publish`, {
    method: 'POST',
    body: {
      workspace_id: workspaceId,
      async_mode: asyncMode,
    },
  });
}

export async function getPublishResult(packageId: string, publishResultId: string, workspaceId?: string) {
  const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : '';
  return request<any>(
    `/api/v1/research/packages/${encodeURIComponent(packageId)}/publish-results/${encodeURIComponent(publishResultId)}${query}`
  );
}

export async function replayPackage(packageId: string, workspaceId: string) {
  return request<any>(
    `/api/v1/research/packages/${encodeURIComponent(packageId)}/replay?workspace_id=${encodeURIComponent(workspaceId)}`
  );
}

export async function createFailure(payload: {
  workspace_id: string;
  attached_targets: Array<{ target_type: string; target_id: string }>;
  observed_outcome: string;
  expected_difference: string;
  failure_reason: string;
  severity: string;
  reporter: string;
}) {
  const data = await request<FailureRecord>(`/api/v1/research/failures`, {
    method: 'POST',
    body: payload,
  });
  return normalizeFailureRecord(data);
}

export async function getFailure(failureId: string) {
  const data = await request<FailureRecord>(`/api/v1/research/failures/${encodeURIComponent(failureId)}`);
  return normalizeFailureRecord(data);
}

export async function createValidation(payload: {
  workspace_id: string;
  target_object: string;
  method: string;
  success_signal: string;
  weakening_signal: string;
  status?: string;
}) {
  return request<any>(`/api/v1/research/validations`, {
    method: 'POST',
    body: payload,
  });
}

export async function submitValidationResult(validationId: string, payload: {
  workspace_id: string;
  outcome: 'validated' | 'weakened' | 'failed';
  note?: string;
  target_type?: string;
  target_id?: string;
  reporter?: string;
}) {
  const data = await request<any>(`/api/v1/research/validations/${encodeURIComponent(validationId)}/results`, {
    method: 'POST',
    body: payload,
  });
  return {
    ...data,
    triggered_failure: data?.triggered_failure ? normalizeFailureRecord(data.triggered_failure) : null,
  };
}

export async function listHypothesisTriggers(workspaceId: string) {
  return request<ListResponse<{ trigger_id: string }>>(
    `/api/v1/research/hypotheses/triggers/list?workspace_id=${encodeURIComponent(workspaceId)}`
  );
}

export async function listHypotheses(workspaceId: string) {
  return request<ListResponse<any>>(`/api/v1/research/hypotheses?workspace_id=${encodeURIComponent(workspaceId)}`);
}

export async function generateHypothesis(workspaceId: string, triggerIds: string[]) {
  return request<JobStatusResponse>(`/api/v1/research/hypotheses/generate`, {
    method: 'POST',
    body: { workspace_id: workspaceId, trigger_ids: triggerIds, async_mode: true },
  });
}

export async function generateLiteratureFrontierHypothesis(payload: {
  workspace_id: string;
  source_ids: string[];
  research_goal: string;
  frontier_size?: number;
  max_rounds?: number;
  active_retrieval?: {
    enabled?: boolean;
    max_papers_per_burst?: number;
    max_bursts?: number;
  };
}) {
  return request<JobStatusResponse>(`/api/v1/research/hypotheses/generate`, {
    method: 'POST',
    body: {
      workspace_id: payload.workspace_id,
      source_ids: payload.source_ids,
      research_goal: payload.research_goal,
      mode: 'literature_frontier',
      async_mode: true,
      ...(payload.frontier_size === undefined ? {} : { frontier_size: payload.frontier_size }),
      ...(payload.max_rounds === undefined ? {} : { max_rounds: payload.max_rounds }),
      ...(payload.active_retrieval === undefined ? {} : { active_retrieval: payload.active_retrieval }),
    },
  });
}

export async function decideHypothesis(
  hypothesisId: string,
  action: 'promote' | 'reject' | 'defer',
  payload: {
    workspace_id: string;
    note: string;
    decision_source_type: string;
    decision_source_ref: string;
  }
) {
  return request<any>(`/api/v1/research/hypotheses/${encodeURIComponent(hypothesisId)}/${action}`, {
    method: 'POST',
    body: payload,
  });
}

export async function getHypothesisPool(poolId: string) {
  return request<any>(`/api/v1/research/hypotheses/pools/${encodeURIComponent(poolId)}`);
}

export async function listHypothesisPoolCandidates(poolId: string) {
  return request<ListResponse<any>>(`/api/v1/research/hypotheses/pools/${encodeURIComponent(poolId)}/candidates`);
}

export async function listHypothesisPoolRounds(poolId: string) {
  return request<ListResponse<any>>(`/api/v1/research/hypotheses/pools/${encodeURIComponent(poolId)}/rounds`);
}

export async function runHypothesisPoolRound(
  poolId: string,
  workspaceOrPayload: string | { workspace_id: string; async_mode?: boolean; max_matches?: number },
  maxMatches?: number
) {
  const payload =
    typeof workspaceOrPayload === 'string'
      ? {
          workspace_id: workspaceOrPayload,
          ...(maxMatches === undefined ? {} : { max_matches: maxMatches }),
        }
      : workspaceOrPayload;

  return request<AsyncJobAcceptedResponse>(`/api/v1/research/hypotheses/pools/${encodeURIComponent(poolId)}/run-round`, {
    method: 'POST',
    body: {
      workspace_id: payload.workspace_id,
      ...(payload.async_mode === undefined ? {} : { async_mode: payload.async_mode }),
      ...(payload.max_matches === undefined ? {} : { max_matches: payload.max_matches }),
    },
  });
}

export async function finalizeHypothesisPool(
  poolId: string,
  workspaceOrPayload: string | { workspace_id: string; async_mode?: boolean }
) {
  const payload =
    typeof workspaceOrPayload === 'string' ? { workspace_id: workspaceOrPayload } : workspaceOrPayload;

  return request<AsyncJobAcceptedResponse>(`/api/v1/research/hypotheses/pools/${encodeURIComponent(poolId)}/finalize`, {
    method: 'POST',
    body: {
      workspace_id: payload.workspace_id,
      ...(payload.async_mode === undefined ? {} : { async_mode: payload.async_mode }),
    },
  });
}

export async function controlHypothesisPool(
  poolId: string,
  payload: {
    workspace_id: string;
    action: 'pause' | 'resume' | 'stop' | 'force_finalize' | 'disable_retrieval' | 'add_sources';
    source_ids?: string[];
  }
) {
  return request<any>(`/api/v1/research/hypotheses/pools/${encodeURIComponent(poolId)}/control`, {
    method: 'POST',
    body: {
      workspace_id: payload.workspace_id,
      action: payload.action,
      ...(payload.source_ids === undefined ? {} : { source_ids: payload.source_ids }),
    },
  });
}

export async function patchHypothesisCandidate(
  candidateId: string,
  payload: {
    workspace_id: string;
    reasoning_chain: Record<string, unknown>;
    reset_review_state?: boolean;
  }
) {
  return request<any>(`/api/v1/research/hypotheses/candidates/${encodeURIComponent(candidateId)}`, {
    method: 'PATCH',
    body: {
      workspace_id: payload.workspace_id,
      reasoning_chain: payload.reasoning_chain,
      ...(payload.reset_review_state === undefined ? {} : { reset_review_state: payload.reset_review_state }),
    },
  });
}

export async function getHypothesisMatch(matchId: string) {
  return request<any>(`/api/v1/research/hypotheses/matches/${encodeURIComponent(matchId)}`);
}

export async function getHypothesisSearchTreeNode(nodeId: string) {
  return request<any>(`/api/v1/research/hypotheses/search-tree/${encodeURIComponent(nodeId)}`);
}

export async function listMemory(
  payloadOrWorkspaceId:
    | string
    | {
        workspace_id: string;
        view_types?: string[];
        query?: string;
        retrieve_method?: string;
        top_k_per_view?: number;
        metadata_filters_by_view?: Record<string, Record<string, unknown>>;
      }
) {
  const payload =
    typeof payloadOrWorkspaceId === 'string' ? { workspace_id: payloadOrWorkspaceId } : payloadOrWorkspaceId;

  return request<any>(`/api/v1/research/memory/list`, {
    method: 'POST',
    body: {
      workspace_id: payload.workspace_id,
      ...(payload.view_types === undefined ? {} : { view_types: payload.view_types }),
      ...(payload.query === undefined ? {} : { query: payload.query }),
      ...(payload.retrieve_method === undefined ? {} : { retrieve_method: payload.retrieve_method }),
      ...(payload.top_k_per_view === undefined ? {} : { top_k_per_view: payload.top_k_per_view }),
      ...(payload.metadata_filters_by_view === undefined
        ? {}
        : { metadata_filters_by_view: payload.metadata_filters_by_view }),
    },
  });
}

export async function bindMemoryToCurrentRoute(
  payloadOrWorkspaceId:
    | string
    | {
        workspace_id: string;
        route_id: string;
        memory_id: string;
        memory_view_type: string;
        note?: string;
      },
  memoryId?: string,
  memoryViewType?: string,
  routeId?: string,
  note?: string
) {
  const payload =
    typeof payloadOrWorkspaceId === 'string'
      ? {
          workspace_id: payloadOrWorkspaceId,
          route_id: routeId ?? '',
          memory_id: memoryId ?? '',
          memory_view_type: memoryViewType ?? '',
          ...(note === undefined ? {} : { note }),
        }
      : payloadOrWorkspaceId;

  return request<any>(`/api/v1/research/memory/actions/bind-to-current-route`, {
    method: 'POST',
    body: {
      workspace_id: payload.workspace_id,
      route_id: payload.route_id,
      memory_id: payload.memory_id,
      memory_view_type: payload.memory_view_type,
      ...(payload.note === undefined ? {} : { note: payload.note }),
    },
  });
}

export async function memoryToHypothesisCandidate(
  payloadOrWorkspaceId:
    | string
    | {
        workspace_id: string;
        memory_id: string;
        memory_view_type: string;
        note?: string;
      },
  memoryId?: string,
  memoryViewType?: string,
  note?: string
) {
  const payload =
    typeof payloadOrWorkspaceId === 'string'
      ? {
          workspace_id: payloadOrWorkspaceId,
          memory_id: memoryId ?? '',
          memory_view_type: memoryViewType ?? '',
          ...(note === undefined ? {} : { note }),
        }
      : payloadOrWorkspaceId;

  return request<any>(`/api/v1/research/memory/actions/memory-to-hypothesis-candidate`, {
    method: 'POST',
    body: {
      workspace_id: payload.workspace_id,
      memory_id: payload.memory_id,
      memory_view_type: payload.memory_view_type,
      ...(payload.note === undefined ? {} : { note: payload.note }),
    },
  });
}

async function retrieveFailurePattern(workspaceId: string): Promise<ListResponse<FailureRecord>> {
  const view = await request<any>(`/api/v1/research/retrieval/views/failure_pattern`, {
    method: 'POST',
    body: {
      workspace_id: workspaceId,
      retrieve_method: 'hybrid',
      top_k: 20,
    },
  });
  const items = Array.isArray(view?.items) ? view.items.map((item: any, idx: number) => mapRetrievalItemToFailure(item, workspaceId, idx)) : [];
  return { items, total: Number(view?.total ?? items.length) };
}

async function getExecutionSummary(workspaceId: string): Promise<any> {
  return request<any>(`/api/v1/research/executions/summary?workspace_id=${encodeURIComponent(workspaceId)}&limit=500`);
}

async function listFailureDetailsBySummary(workspaceId: string): Promise<ListResponse<FailureRecord>> {
  const summary = await getExecutionSummary(workspaceId);
  const ids = new Set<string>();
  collectFailureIds(summary, ids);
  const failureIds = Array.from(ids);
  if (failureIds.length === 0) return { items: [], total: 0 };

  const details = await Promise.all(
    failureIds.map(async (failureId) => {
      try {
        const item = await getFailure(failureId);
        return { item, failureId };
      } catch (error) {
        return { item: null, failureId, error };
      }
    })
  );
  const items = details
    .map((entry) => entry.item)
    .filter((item): item is FailureRecord => item !== null);
  if (failureIds.length > 0 && items.length === 0) {
    throw new ResearchApiError(
      502,
      {
        error_code: 'research.failure_details_unavailable',
        message: 'failed to load failure details',
        details: {
          workspace_id: workspaceId,
          failure_ids: failureIds,
        },
      },
      'failed to load failure details'
    );
  }
  return { items, total: items.length };
}

export async function listFailures(workspaceId: string): Promise<ListResponse<FailureRecord>> {
  let detailResult: ListResponse<FailureRecord> | null = null;
  let detailError: unknown = null;

  try {
    detailResult = await listFailureDetailsBySummary(workspaceId);
    if (detailResult.items.length > 0) return detailResult;
  } catch (error) {
    detailError = error;
  }

  try {
    return await retrieveFailurePattern(workspaceId);
  } catch (retrievalError) {
    if (detailError) {
      throw new ResearchApiError(
        502,
        {
          error_code: 'research.failures_unavailable',
          message: 'failed to load failures from detail and retrieval paths',
          details: {
            workspace_id: workspaceId,
            detail_error: describeError(detailError),
            retrieval_error: describeError(retrievalError),
          },
        },
        'failed to load failures'
      );
    }
    if (detailResult) return detailResult;
    throw retrievalError;
  }
}



