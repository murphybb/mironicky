import React, { useState, useEffect, useRef } from 'react';
import { RoutesPage, RouteDetailPage, ImportPage, ConfirmPage } from './pages1';
import { WorkbenchPage, FailuresPage, PackagesPage, TeamPage } from './pages2';
import { FrontierPage } from './frontier';
import { Menu, X, Route, FileInput, Network, AlertTriangle, Package, Users, Lightbulb } from 'lucide-react';
import {
  RouteRecord,
  CandidateRecord,
  FailureRecord,
  PackageRecord,
  SourceRecord,
  GraphNode,
  GraphEdge,
  listRoutes,
  getGraph,
  listCandidates,
  listFailures,
  listPackages,
  listSources,
  listWorkspaces,
  listHypotheses,
  listHypothesisTriggers,
  generateHypothesis,
  decideHypothesis,
  pollJob,
  getJobStatus,
  recomputeRoutes,
  scoreRoute,
  listVersions,
  getVersionDiff,
  lookupSourceScholarly,
  getExtractionResult,
  publishPackage,
  getPublishResult,
  listMemory,
  bindMemoryToCurrentRoute,
  memoryToHypothesisCandidate,
  getHypothesisPool,
  listHypothesisPoolCandidates,
  listHypothesisPoolRounds,
  runHypothesisPoolRound,
  finalizeHypothesisPool,
  getHypothesisMatch,
  getHypothesisSearchTreeNode,
  getAsyncJobUiState,
  getErrorMessage,
} from './api';
import { chooseWorkspaceToRestore, hasWorkspaceContent } from './workspace-restore-helpers';

const DEFAULT_WORKSPACE_ID = 'ws-default-1';
const WORKSPACE_STORAGE_KEY = 'mironicky.workspace_id';
const MOBILE_BREAKPOINT = 900;
const TOPBAR_ASYNC_POLL_TIMEOUT_MS = 120000;
const TOPBAR_ASYNC_POLL_INTERVAL_MS = 1200;

interface ExtractionContext {
  sourceId: string;
  jobId?: string | null;
  candidateBatchId?: string | null;
  status?: string | null;
  backendStatus?: string | null;
  jobCreatedAt?: string | null;
  jobStartedAt?: string | null;
  jobFinishedAt?: string | null;
  lastSyncedAt?: string | null;
  candidateIds?: string[];
  error?: { error_code?: string; message?: string } | null;
  degraded?: boolean;
  degradedReason?: string | null;
  partialFailureCount?: number;
}

interface RecentAsyncTask {
  kind: 'route' | 'hypothesis';
  status: 'running' | 'running_background' | 'completed' | 'failed';
  jobId?: string | null;
  submittedAt: string;
  finishedAt?: string | null;
  message: string;
  targetPage: 'routes' | 'detail';
  targetLabel: string;
}

const SHOW_INTERNAL_TOOLS =
  String((import.meta as any)?.env?.VITE_RESEARCH_INTERNAL_TOOLS || '').trim().toLowerCase() === 'true';

function normalizeSourceExtractionStatus(src: any): string {
  const extractStatus = String(src?.last_extract_status || '').toLowerCase();
  if (extractStatus) return extractStatus;
  const sourceStatus = String(src?.status || '').toLowerCase();
  if (sourceStatus === 'extracted') return 'succeeded';
  if (sourceStatus === 'extract_failed') return 'failed';
  if (sourceStatus === 'parsed' || sourceStatus === 'processing') return 'running';
  return sourceStatus;
}

function resolveInitialWorkspaceId() {
  if (typeof window === 'undefined') return DEFAULT_WORKSPACE_ID;
  const fromQuery = new URLSearchParams(window.location.search).get('workspace_id');
  if (fromQuery && fromQuery.trim()) return fromQuery.trim();
  const fromStorage = window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
  if (fromStorage && fromStorage.trim()) return fromStorage.trim();
  return DEFAULT_WORKSPACE_ID;
}

function resolveInitialPage() {
  if (typeof window === 'undefined') return 'routes';
  const raw = new URLSearchParams(window.location.search).get('page');
  const allowed = new Set(['routes', 'detail', 'import', 'confirm', 'workbench', 'frontier', 'failures', 'packages', 'team']);
  return raw && allowed.has(raw) ? raw : 'routes';
}

function syncUrlState(workspaceId: string, page: string) {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  url.searchParams.set('workspace_id', workspaceId);
  url.searchParams.set('page', page);
  window.history.replaceState({}, '', `${url.pathname}?${url.searchParams.toString()}${url.hash}`);
}

function shortenLabel(value: string, max = 42) {
  if (!value) return '';
  if (value.length <= max) return value;
  return `${value.slice(0, max)}...`;
}

function normalizeRouteTitle(title?: string) {
  const raw = String(title || '').trim();
  if (!raw) return '';
  return raw.replace(/^route:\s*/i, '').trim();
}

function formatTaskDateTime(value?: string | null) {
  if (!value) return '--';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return String(value);
  return dt.toLocaleString('zh-CN', { hour12: false });
}

async function waitForRouteCountIncrease(
  workspaceId: string,
  baselineCount: number,
  timeoutMs = 30000,
  intervalMs = 1500
) {
  const started = Date.now();
  while (Date.now() - started <= timeoutMs) {
    try {
      const latest = await listRoutes(workspaceId);
      const total = Number(latest?.total || latest?.items?.length || 0);
      if (total > baselineCount) {
        return true;
      }
    } catch {
      // 忽略短暂网络抖动，继续轮询。
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return false;
}

function isLlmInvalidOutputError(error: unknown) {
  const code = String((error as any)?.envelope?.error_code || (error as any)?.error_code || '').toLowerCase();
  return code === 'research.llm_invalid_output';
}

function isJobTimeoutError(error: unknown) {
  const code = String((error as any)?.envelope?.error_code || (error as any)?.error_code || '').toLowerCase();
  return code === 'research.job_timeout' || code === 'research.request_timeout';
}

function ResearchOpsPanel({
  workspaceId,
  selectedRouteId,
  selectedPackageId,
  hasActionableGraph,
  showToast,
  onRefresh,
}: {
  workspaceId: string;
  selectedRouteId?: string;
  selectedPackageId?: string;
  hasActionableGraph: boolean;
  showToast: (msg: string) => void;
  onRefresh: () => Promise<void>;
}) {
  const [output, setOutput] = useState('');
  const [versionId, setVersionId] = useState('');
  const [sourceId, setSourceId] = useState('');
  const [candidateBatchId, setCandidateBatchId] = useState('');
  const [publishResultId, setPublishResultId] = useState('');
  const [memoryId, setMemoryId] = useState('');
  const [memoryViewType, setMemoryViewType] = useState('');
  const [poolId, setPoolId] = useState('');
  const [matchId, setMatchId] = useState('');
  const [treeNodeId, setTreeNodeId] = useState('');

  const runOp = async (label: string, runner: () => Promise<unknown>, refresh = false) => {
    try {
      const result = await runner();
      setOutput(JSON.stringify(result, null, 2));
      if (refresh) await onRefresh();
      showToast(`${label}完成`);
    } catch (error) {
      showToast(getErrorMessage(error));
      setOutput(JSON.stringify({ 错误: getErrorMessage(error) }, null, 2));
    }
  };

  const routeId = (selectedRouteId || '').trim();
  const packageId = (selectedPackageId || '').trim();
  const memoryViewTypeValue = memoryViewType.trim() || 'failure_pattern';
  const scoreDisabledReason = !routeId ? '请先在首页选择一条路线后再评分。' : '';
  const versionDiffDisabledReason = !versionId.trim() ? '请先输入版本编号。' : '';
  const scholarlyDisabledReason = !sourceId.trim() ? '请先输入来源编号。' : '';
  const extractionResultDisabledReason =
    !sourceId.trim() || !candidateBatchId.trim()
      ? '请先输入来源编号和候选批次编号。'
      : '';
  const publishDisabledReason = !packageId ? '请先在知识包页选择一个知识包。' : '';
  const publishResultDisabledReason =
    !packageId || !publishResultId.trim()
      ? '请先选择知识包并输入发布结果编号。'
      : '';
  const bindMemoryDisabledReason =
    !memoryId.trim() || !routeId
      ? '请先输入记忆编号并选择路线。'
      : '';
  const memoryCandidateDisabledReason = !memoryId.trim() ? '请先输入记忆编号。' : '';
  const poolDisabledReason = !poolId.trim() ? '请先输入假设池编号。' : '';
  const matchDisabledReason = !matchId.trim() ? '请先输入匹配编号。' : '';
  const treeNodeDisabledReason = !treeNodeId.trim() ? '请先输入搜索树节点编号。' : '';

  return (
    <div className="ctx-bar" style={{ marginTop: '12px', display: 'block' }}>
      <div style={{ fontSize: '11px', fontFamily: 'var(--mono)', color: 'var(--text3)', marginBottom: '8px' }}>
        高级接口操作 · 工作区={workspaceId}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '8px' }}>
        <button
          className="btn"
          disabled={!hasActionableGraph}
          title={!hasActionableGraph ? '至少需要 2 个节点且存在 1 条连接，才能生成路线' : undefined}
          onClick={() =>
            runOp('路线生成', async () => {
              const accepted = await recomputeRoutes(workspaceId, 'ui_manual_generate');
              if (accepted?.job_id) {
                const completed = await pollJob(accepted.job_id, 120000, 1200);
                return { accepted, completed };
              }
              return accepted;
            }, true)
          }
        >
          路线生成
        </button>
        <button
          className="btn"
          onClick={() => runOp('路线评分', () => scoreRoute(routeId, workspaceId), true)}
          disabled={!routeId}
          title={scoreDisabledReason || undefined}
        >
          路线评分
        </button>
        <button className="btn" onClick={() => runOp('版本列表查询', () => listVersions(workspaceId))}>版本列表查询</button>
        <button
          className="btn"
          onClick={() => runOp('版本差异查询', () => getVersionDiff(versionId, workspaceId))}
          disabled={!versionId.trim()}
          title={versionDiffDisabledReason || undefined}
        >
          版本差异查询
        </button>
      </div>
      {!hasActionableGraph && (
        <div style={{ fontSize: '11px', fontFamily: 'var(--mono)', color: 'var(--text3)', marginBottom: '8px' }}>
          至少需要 2 个节点且存在 1 条连接，才能生成路线。
        </div>
      )}

      <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
        <input className="form-input" placeholder="请输入版本编号" value={versionId} onChange={(e) => setVersionId(e.target.value)} />
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '8px' }}>
        <button
          className="btn"
          onClick={() => runOp('来源学术检索', () => lookupSourceScholarly(sourceId, workspaceId, false))}
          disabled={!sourceId.trim()}
          title={scholarlyDisabledReason || undefined}
        >
          来源学术检索
        </button>
        <button
          className="btn"
          onClick={() => runOp('来源抽取结果查询', () => getExtractionResult(sourceId, candidateBatchId, workspaceId))}
          disabled={!sourceId.trim() || !candidateBatchId.trim()}
          title={extractionResultDisabledReason || undefined}
        >
          来源抽取结果查询
        </button>
        <button
          className="btn"
          onClick={() => runOp('知识包发布', () => publishPackage(packageId, workspaceId))}
          disabled={!packageId}
          title={publishDisabledReason || undefined}
        >
          知识包发布
        </button>
        <button
          className="btn"
          onClick={() => runOp('知识包发布结果查询', () => getPublishResult(packageId, publishResultId, workspaceId))}
          disabled={!packageId || !publishResultId.trim()}
          title={publishResultDisabledReason || undefined}
        >
          知识包发布结果查询
        </button>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
        <input className="form-input" placeholder="请输入来源编号" value={sourceId} onChange={(e) => setSourceId(e.target.value)} />
        <input className="form-input" placeholder="请输入候选批次编号" value={candidateBatchId} onChange={(e) => setCandidateBatchId(e.target.value)} />
        <input className="form-input" placeholder="请输入发布结果编号" value={publishResultId} onChange={(e) => setPublishResultId(e.target.value)} />
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '8px' }}>
        <button className="btn" onClick={() => runOp('记忆列表查询', () => listMemory(workspaceId))}>记忆列表查询</button>
        <button
          className="btn"
          onClick={() =>
            runOp('记忆绑定路线', () => bindMemoryToCurrentRoute(workspaceId, memoryId, memoryViewTypeValue, routeId, 'ui_bind_memory_to_route'))
          }
          disabled={!memoryId.trim() || !routeId}
          title={bindMemoryDisabledReason || undefined}
        >
          记忆绑定路线
        </button>
        <button
          className="btn"
          onClick={() => runOp('记忆转假设候选', () => memoryToHypothesisCandidate(workspaceId, memoryId, memoryViewTypeValue, 'ui_memory_to_hypothesis'))}
          disabled={!memoryId.trim()}
          title={memoryCandidateDisabledReason || undefined}
        >
          记忆转假设候选
        </button>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
        <input className="form-input" placeholder="请输入记忆编号" value={memoryId} onChange={(e) => setMemoryId(e.target.value)} />
        <input className="form-input" placeholder="记忆视图类型（默认失败模式）" value={memoryViewType} onChange={(e) => setMemoryViewType(e.target.value)} />
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '8px' }}>
        <button className="btn" onClick={() => runOp('获取假设池', () => getHypothesisPool(poolId))} disabled={!poolId.trim()} title={poolDisabledReason || undefined}>获取假设池</button>
        <button className="btn" onClick={() => runOp('假设池候选列表', () => listHypothesisPoolCandidates(poolId))} disabled={!poolId.trim()} title={poolDisabledReason || undefined}>假设池候选列表</button>
        <button className="btn" onClick={() => runOp('假设池轮次列表', () => listHypothesisPoolRounds(poolId))} disabled={!poolId.trim()} title={poolDisabledReason || undefined}>假设池轮次列表</button>
        <button className="btn" onClick={() => runOp('执行假设池一轮', () => runHypothesisPoolRound(poolId, workspaceId), true)} disabled={!poolId.trim()} title={poolDisabledReason || undefined}>执行假设池一轮</button>
        <button className="btn" onClick={() => runOp('完成假设池', () => finalizeHypothesisPool(poolId, workspaceId), true)} disabled={!poolId.trim()} title={poolDisabledReason || undefined}>完成假设池</button>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
        <input className="form-input" placeholder="请输入假设池编号" value={poolId} onChange={(e) => setPoolId(e.target.value)} />
        <input className="form-input" placeholder="请输入匹配编号" value={matchId} onChange={(e) => setMatchId(e.target.value)} />
        <input className="form-input" placeholder="请输入搜索树节点编号" value={treeNodeId} onChange={(e) => setTreeNodeId(e.target.value)} />
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
        <button className="btn" onClick={() => runOp('获取匹配详情', () => getHypothesisMatch(matchId))} disabled={!matchId.trim()} title={matchDisabledReason || undefined}>获取匹配详情</button>
        <button className="btn" onClick={() => runOp('获取搜索树节点', () => getHypothesisSearchTreeNode(treeNodeId))} disabled={!treeNodeId.trim()} title={treeNodeDisabledReason || undefined}>获取搜索树节点</button>
      </div>

      <textarea
        className="paste-area"
        style={{ marginTop: '10px', minHeight: '160px' }}
        value={output}
        readOnly
        placeholder="接口响应预览"
      />
    </div>
  );
}

export default function App() {
  const [currentPage, setCurrentPage] = useState(resolveInitialPage);
  const [selRoute, setSelRoute] = useState(0);
  const [selFail, setSelFail] = useState<number | null>(0);
  const [selPkg, setSelPkg] = useState<number | null>(0);
  const [toastMsg, setToastMsg] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => {
    if (typeof window === 'undefined') return true;
    return window.innerWidth > MOBILE_BREAKPOINT;
  });
  
  const [routes, setRoutes] = useState<RouteRecord[]>([]);
  const [candidates, setCandidates] = useState<CandidateRecord[]>([]);
  const [failures, setFailures] = useState<FailureRecord[]>([]);
  const [packages, setPackages] = useState<PackageRecord[]>([]);
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [hypotheses, setHypotheses] = useState<any[]>([]);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [edgeColors] = useState<any>({
    supports:'#639922',requires:'#185FA5',weakens:'#E24B4A',gaps:'#B4B2A9'
  });

  const [loading, setLoading] = useState(true);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [workspaceId, setWorkspaceId] = useState(resolveInitialWorkspaceId);
  const [lastExtractionContext, setLastExtractionContext] = useState<ExtractionContext | null>(null);
  const extractionContextRef = useRef<ExtractionContext | null>(null);
  const fetchDataRef = useRef<() => Promise<void>>(async () => undefined);
  const workspaceRestoreAttemptedRef = useRef(false);
  const [isWorkspaceEditorOpen, setIsWorkspaceEditorOpen] = useState(false);
  const [workspaceDraft, setWorkspaceDraft] = useState('');
  const [isGeneratingRoute, setIsGeneratingRoute] = useState(false);
  const [isScoringRoute, setIsScoringRoute] = useState(false);
  const [isGeneratingHypothesis, setIsGeneratingHypothesis] = useState(false);
  const [recentAsyncTask, setRecentAsyncTask] = useState<RecentAsyncTask | null>(null);

  const goto = (pg: string) => {
    setCurrentPage(pg);
    if (typeof window !== 'undefined' && window.innerWidth <= MOBILE_BREAKPOINT) {
      setIsSidebarOpen(false);
    }
  };
  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(''), 2200);
  };

  useEffect(() => {
    extractionContextRef.current = lastExtractionContext;
  }, [lastExtractionContext]);

  const fetchData = async () => {
    if (!hasLoadedOnce) setLoading(true);
    const selectedRouteIdBeforeRefresh = routes[selRoute]?.route_id;
    const currentExtractionContext = extractionContextRef.current;
    try {
      const [resRoutes, resGraph, resCand, resFail, resPkg, resHyp, resSources] = await Promise.all([
        listRoutes(workspaceId),
        getGraph(workspaceId),
        listCandidates(workspaceId),
        listFailures(workspaceId),
        listPackages(workspaceId),
        listHypotheses(workspaceId),
        listSources(workspaceId),
      ]);
      
      setRoutes(resRoutes.items || []);
      setNodes(resGraph.nodes || []);
      setEdges(resGraph.edges || []);
      setCandidates(resCand.items || []);
      setFailures(resFail.items || []);
      setPackages(resPkg.items || []);
      setHypotheses(Array.isArray(resHyp.items) ? resHyp.items : []);
      setSources(Array.isArray(resSources.items) ? resSources.items : []);
      if (!workspaceRestoreAttemptedRef.current && workspaceId === DEFAULT_WORKSPACE_ID) {
        workspaceRestoreAttemptedRef.current = true;
        const currentWorkspaceSnapshot = {
          sourceCount: Array.isArray(resSources.items) ? resSources.items.length : Number(resSources.total || 0),
          nodeCount: Array.isArray(resGraph.nodes) ? resGraph.nodes.length : 0,
          edgeCount: Array.isArray(resGraph.edges) ? resGraph.edges.length : 0,
          routeCount: Array.isArray(resRoutes.items) ? resRoutes.items.length : Number(resRoutes.total || 0),
          candidateCount: Array.isArray(resCand.items) ? resCand.items.length : Number(resCand.total || 0),
        };
        if (!hasWorkspaceContent(currentWorkspaceSnapshot)) {
          const restoreTarget = chooseWorkspaceToRestore(
            workspaceId,
            currentWorkspaceSnapshot,
            (await listWorkspaces()).items || [],
            DEFAULT_WORKSPACE_ID
          );
          if (restoreTarget) {
            setWorkspaceId(restoreTarget);
            setLastExtractionContext(null);
            setHasLoadedOnce(false);
            setSelRoute(0);
            setSelFail(0);
            setSelPkg(0);
            setRecentAsyncTask(null);
            showToast(`已恢复已有数据工作区：${restoreTarget}`);
            return;
          }
        }
      }
      if (currentExtractionContext?.sourceId) {
        const latestSource = (Array.isArray(resSources.items) ? resSources.items : []).find(
          (item: any) => String(item?.source_id) === String(currentExtractionContext.sourceId)
        );
        if (latestSource) {
          let nextStatus = normalizeSourceExtractionStatus(latestSource) || currentExtractionContext.status || null;
          let nextBatchId =
            String(latestSource?.last_candidate_batch_id || currentExtractionContext.candidateBatchId || '').trim() || null;
          const nextJobId =
            String(latestSource?.last_extract_job_id || currentExtractionContext.jobId || '').trim() || null;
          let nextCandidateIds = currentExtractionContext.candidateIds;
          let nextPartialFailureCount = currentExtractionContext.partialFailureCount || 0;
          let nextDegradedReason =
            currentExtractionContext.degradedReason ||
            latestSource?.last_extract_error?.error_code ||
            null;
          let nextDegraded = Boolean(currentExtractionContext.degraded || nextDegradedReason);
          let nextError = latestSource?.last_extract_error || currentExtractionContext.error || null;
          let nextBackendStatus = currentExtractionContext.backendStatus || nextStatus || null;
          let nextJobCreatedAt = currentExtractionContext.jobCreatedAt || null;
          let nextJobStartedAt = currentExtractionContext.jobStartedAt || null;
          let nextJobFinishedAt = currentExtractionContext.jobFinishedAt || null;
          const sourceScopedCandidates = (Array.isArray(resCand.items) ? resCand.items : []).filter(
            (item: any) => String(item?.source_id) === String(currentExtractionContext.sourceId)
          );
          const sourceBatchIdList = Array.from(
            new Set(
              sourceScopedCandidates
                .map((item: any) => String(item?.candidate_batch_id || '').trim())
                .filter(Boolean)
            )
          );

          if (!nextBatchId && sourceBatchIdList.length > 0) {
            nextBatchId = sourceBatchIdList[sourceBatchIdList.length - 1];
          } else if (nextBatchId && sourceBatchIdList.length === 1 && sourceBatchIdList[0] !== nextBatchId) {
            // 当上下文批次与最新候选批次唯一值不一致时，优先回收最新批次，避免 confirm 页“0/0 假空”。
            nextBatchId = sourceBatchIdList[0];
          }

          if ((!Array.isArray(nextCandidateIds) || nextCandidateIds.length === 0) && sourceScopedCandidates.length > 0) {
            const scopedForIds = nextBatchId
              ? sourceScopedCandidates.filter(
                  (item: any) => String(item?.candidate_batch_id || '').trim() === String(nextBatchId)
                )
              : sourceScopedCandidates;
            if (scopedForIds.length > 0) {
              nextCandidateIds = scopedForIds.map((item: any) => String(item?.candidate_id));
            }
          }

          const activeStatuses = new Set(['running', 'pending', 'queued', 'processing']);
          const normalizedStatus = String(nextStatus || '').toLowerCase();
          const shouldSyncLiveJob =
            Boolean(nextJobId) &&
            (
              !normalizedStatus ||
              activeStatuses.has(normalizedStatus) ||
              !nextJobFinishedAt
            );

          if (shouldSyncLiveJob && nextJobId) {
            try {
              const liveJob = await getJobStatus(nextJobId);
              const liveStatus = String(liveJob?.status || '').toLowerCase();
              if (liveStatus) {
                nextBackendStatus = liveStatus;
                if (!normalizedStatus || activeStatuses.has(normalizedStatus)) {
                  nextStatus = liveStatus;
                }
              }
              nextJobCreatedAt = liveJob?.created_at || nextJobCreatedAt;
              nextJobStartedAt = liveJob?.started_at || nextJobStartedAt;
              nextJobFinishedAt = liveJob?.finished_at || nextJobFinishedAt;
              const liveBatchId = String(liveJob?.result_ref?.resource_id || '').trim();
              if (liveBatchId && !nextBatchId) {
                nextBatchId = liveBatchId;
              }
              if (liveJob?.error) {
                nextError = liveJob.error;
              }
            } catch {
              // 任务状态临时不可读时不阻断主流程。
            }
          }

          if (
            nextBatchId &&
            ['succeeded', 'completed'].includes(String(nextStatus || '').toLowerCase()) &&
            (!Array.isArray(nextCandidateIds) || nextCandidateIds.length === 0)
          ) {
            try {
              const extractionResult = await getExtractionResult(String(currentExtractionContext.sourceId), nextBatchId, workspaceId);
              if (Array.isArray(extractionResult?.candidate_ids)) {
                nextCandidateIds = extractionResult.candidate_ids.map((item: unknown) => String(item));
              }
              if (typeof extractionResult?.partial_failure_count === 'number') {
                nextPartialFailureCount = extractionResult.partial_failure_count;
              }
              if (extractionResult?.degraded_reason) {
                nextDegradedReason = extractionResult.degraded_reason;
              }
              nextDegraded = Boolean(extractionResult?.degraded || nextDegradedReason);
            } catch {
              // 获取 extraction result 失败时，保持已有上下文。
            }
          }

          setLastExtractionContext({
            ...currentExtractionContext,
            jobId: nextJobId,
            candidateBatchId: nextBatchId,
            status: nextStatus,
            backendStatus: nextBackendStatus || nextStatus,
            jobCreatedAt: nextJobCreatedAt,
            jobStartedAt: nextJobStartedAt,
            jobFinishedAt: nextJobFinishedAt,
            lastSyncedAt: new Date().toISOString(),
            candidateIds: nextCandidateIds,
            error: ['succeeded', 'completed'].includes(String(nextStatus || '').toLowerCase())
              ? null
              : nextError || currentExtractionContext.error || null,
            degraded: nextDegraded,
            degradedReason: nextDegradedReason,
            partialFailureCount: nextPartialFailureCount,
          });
        }
      }
      setSelRoute((prev) => {
        const nextRoutes = resRoutes.items || [];
        if (nextRoutes.length === 0) return 0;
        if (selectedRouteIdBeforeRefresh) {
          const stableIndex = nextRoutes.findIndex((item: any) => item?.route_id === selectedRouteIdBeforeRefresh);
          if (stableIndex >= 0) return stableIndex;
        }
        return Math.min(prev, nextRoutes.length - 1);
      });
      setSelFail((prev) => {
        if ((resFail.items || []).length === 0) return null;
        if (prev === null) return 0;
        return Math.min(prev, (resFail.items || []).length - 1);
      });
      setSelPkg((prev) => {
        if ((resPkg.items || []).length === 0) return null;
        if (prev === null) return 0;
        return Math.min(prev, (resPkg.items || []).length - 1);
      });
    } catch (error) {
      console.error('获取数据失败:', error);
      showToast(getErrorMessage(error));
    } finally {
      setLoading(false);
      setHasLoadedOnce(true);
    }
  };

  useEffect(() => {
    fetchDataRef.current = fetchData;
  }, [fetchData]);

  useEffect(() => {
    fetchData();
  }, [workspaceId]);

  useEffect(() => {
    if (!recentAsyncTask?.jobId || recentAsyncTask.status !== 'running_background') return;
    let cancelled = false;

    const pollInBackground = async () => {
      try {
        const latest = await getJobStatus(recentAsyncTask.jobId!);
        if (cancelled) return;
        const uiState = getAsyncJobUiState(latest.status, latest.error?.error_code);
        if (uiState === 'succeeded') {
          await fetchDataRef.current();
          if (cancelled) return;
          setRecentAsyncTask((prev) => {
            if (!prev || prev.jobId !== latest.job_id) return prev;
            return {
              ...prev,
              status: 'completed',
              finishedAt: latest.finished_at || new Date().toISOString(),
              message:
                prev.kind === 'route'
                  ? '路线已生成，可前往研究路线查看结果。'
                  : '假设已生成，可前往路线详情查看结果。',
            };
          });
          return;
        }
        if (uiState === 'failed') {
          setRecentAsyncTask((prev) => {
            if (!prev || prev.jobId !== latest.job_id) return prev;
            return {
              ...prev,
              status: 'failed',
              finishedAt: latest.finished_at || new Date().toISOString(),
              message: latest.error?.message || '后台任务失败，请查看错误提示。',
            };
          });
        }
      } catch {
        // 保持后台轮询状态，等待下一次轮询。
      }
    };

    void pollInBackground();
    const timer = window.setInterval(() => {
      void pollInBackground();
    }, 4000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [recentAsyncTask?.jobId, recentAsyncTask?.status]);

  useEffect(() => {
    window.localStorage.setItem(WORKSPACE_STORAGE_KEY, workspaceId);
    syncUrlState(workspaceId, currentPage);
  }, [workspaceId, currentPage]);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth > MOBILE_BREAKPOINT) {
        setIsSidebarOpen(true);
      }
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const openWorkspaceEditor = () => {
    setWorkspaceDraft(workspaceId);
    setIsWorkspaceEditorOpen(true);
  };

  const confirmWorkspaceSwitch = () => {
    const trimmed = workspaceDraft.trim();
    if (!trimmed) {
      showToast('请输入工作区编号');
      return;
    }
    if (trimmed === workspaceId) {
      setIsWorkspaceEditorOpen(false);
      return;
    }
    setWorkspaceId(trimmed);
    setLastExtractionContext(null);
    setHasLoadedOnce(false);
    setSelRoute(0);
    setSelFail(0);
    setSelPkg(0);
    setRecentAsyncTask(null);
    setIsWorkspaceEditorOpen(false);
    showToast(`工作区已切换：${trimmed}`);
  };

  const createRecentTask = (
    kind: 'route' | 'hypothesis',
    status: RecentAsyncTask['status'],
    message: string,
    options: Partial<RecentAsyncTask> = {}
  ): RecentAsyncTask => ({
    kind,
    status,
    submittedAt: options.submittedAt || new Date().toISOString(),
    finishedAt: options.finishedAt || null,
    jobId: options.jobId || null,
    message,
    targetPage: kind === 'route' ? 'routes' : 'detail',
    targetLabel: kind === 'route' ? '查看路线' : '查看假设',
  });

  const handleTopbarHypothesisGenerate = async () => {
    if (isGeneratingHypothesis) return;
    if (!(nodes.length > 1 && edges.length > 0)) {
      const message = `当前图谱为 ${nodes.length} 个节点 / ${edges.length} 条连接，至少需要 2 个节点且 1 条连接后再生成假设`;
      setRecentAsyncTask(
        createRecentTask('hypothesis', 'failed', message, {
          submittedAt: new Date().toISOString(),
          finishedAt: new Date().toISOString(),
        })
      );
      showToast(message);
      return;
    }
    setIsGeneratingHypothesis(true);
    try {
      const triggerResp = await listHypothesisTriggers(workspaceId);
      const triggerId = triggerResp.items?.[0]?.trigger_id;
      if (!triggerId) {
        const message = '未找到可用触发器，无法提交假设任务。';
        setRecentAsyncTask(
          createRecentTask('hypothesis', 'failed', message, {
            submittedAt: new Date().toISOString(),
            finishedAt: new Date().toISOString(),
          })
        );
        showToast(message);
        return;
      }
      const job = await generateHypothesis(workspaceId, [triggerId]);
      const submittedAt = new Date().toISOString();
      const acceptedJobId = String(job?.job_id || '').trim() || null;
      setRecentAsyncTask(
        createRecentTask(
          'hypothesis',
          acceptedJobId ? 'running' : 'completed',
          acceptedJobId ? '假设任务已提交，正在等待后端完成。' : '假设生成请求已完成。',
          {
            submittedAt,
            jobId: acceptedJobId,
          }
        )
      );
      if (acceptedJobId) {
        try {
          const completed = await pollJob(
            acceptedJobId,
            TOPBAR_ASYNC_POLL_TIMEOUT_MS,
            TOPBAR_ASYNC_POLL_INTERVAL_MS
          );
          await fetchData();
          setRecentAsyncTask(
            createRecentTask('hypothesis', 'completed', '假设已生成，可前往路线详情查看结果。', {
              submittedAt,
              jobId: acceptedJobId,
              finishedAt: completed?.finished_at || new Date().toISOString(),
            })
          );
          showToast('假设生成完成');
        } catch (error) {
          if (isJobTimeoutError(error)) {
            setRecentAsyncTask(
              createRecentTask('hypothesis', 'running_background', '前端轮询已超时，任务可能仍在后台处理中。', {
                submittedAt,
                jobId: acceptedJobId,
              })
            );
            showToast(`假设任务已提交（job ${acceptedJobId}），当前仍在后台处理中`);
          } else {
            setRecentAsyncTask(
              createRecentTask('hypothesis', 'failed', getErrorMessage(error), {
                submittedAt,
                jobId: acceptedJobId,
                finishedAt: new Date().toISOString(),
              })
            );
            throw error;
          }
        }
      } else {
        await fetchData();
        showToast('假设生成完成');
      }
    } catch (error) {
      setRecentAsyncTask(
        createRecentTask('hypothesis', 'failed', getErrorMessage(error), {
          submittedAt: new Date().toISOString(),
          finishedAt: new Date().toISOString(),
        })
      );
      showToast(getErrorMessage(error));
    } finally {
      setIsGeneratingHypothesis(false);
    }
  };

  const handleTopbarRouteGenerate = async () => {
    if (isGeneratingRoute) return;
    if (!(nodes.length > 1 && edges.length > 0)) {
      const message = '至少需要 2 个节点且存在 1 条连接，才能生成路线';
      setRecentAsyncTask(
        createRecentTask('route', 'failed', message, {
          submittedAt: new Date().toISOString(),
          finishedAt: new Date().toISOString(),
        })
      );
      showToast(message);
      return;
    }
    setIsGeneratingRoute(true);
    let generationCompleted = false;
    let lastAcceptedJobId: string | null = null;
    let stillRunningInBackground = false;
    const submittedAt = new Date().toISOString();
    let lastError: unknown = null;
    try {
      const maxAttempts = 1;
      for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        try {
          const accepted = await recomputeRoutes(workspaceId, 'ui_topbar_generate');
          lastAcceptedJobId = String(accepted?.job_id || '').trim() || null;
          setRecentAsyncTask(
            createRecentTask(
              'route',
              lastAcceptedJobId ? 'running' : 'completed',
              lastAcceptedJobId ? '路线任务已提交，正在等待后端完成。' : '路线生成请求已完成。',
              {
                submittedAt,
                jobId: lastAcceptedJobId,
              }
            )
          );
          showToast(
            lastAcceptedJobId
              ? attempt === 1
                ? `路线生成已提交（job ${lastAcceptedJobId}）`
                : `路线生成重试中（${attempt}/${maxAttempts}）`
              : '路线生成请求已完成'
          );
          if (lastAcceptedJobId) {
            try {
              const completed = await pollJob(
                lastAcceptedJobId,
                TOPBAR_ASYNC_POLL_TIMEOUT_MS,
                TOPBAR_ASYNC_POLL_INTERVAL_MS
              );
              await fetchData();
              setRecentAsyncTask(
                createRecentTask('route', 'completed', '路线已生成，可前往研究路线查看结果。', {
                  submittedAt,
                  jobId: lastAcceptedJobId,
                  finishedAt: completed?.finished_at || new Date().toISOString(),
                })
              );
            } catch (error) {
              if (isJobTimeoutError(error)) {
                stillRunningInBackground = true;
                setRecentAsyncTask(
                  createRecentTask('route', 'running_background', '前端轮询已超时，任务可能仍在后台处理中。', {
                    submittedAt,
                    jobId: lastAcceptedJobId,
                  })
                );
              } else {
                setRecentAsyncTask(
                  createRecentTask('route', 'failed', getErrorMessage(error), {
                    submittedAt,
                    jobId: lastAcceptedJobId,
                    finishedAt: new Date().toISOString(),
                  })
                );
                throw error;
              }
            }
          }
          generationCompleted = true;
          lastError = null;
          break;
        } catch (error) {
          lastError = error;
          if (!isLlmInvalidOutputError(error) || attempt >= maxAttempts) {
            break;
          }
        }
      }
      if (generationCompleted) {
        if (!lastAcceptedJobId) {
          await fetchData();
        }
        if (lastAcceptedJobId && stillRunningInBackground) {
          showToast(`路线任务已提交（job ${lastAcceptedJobId}），当前仍在后台处理中`);
        } else {
          showToast('路线生成完成');
        }
      } else if (lastError) {
        setRecentAsyncTask(
          createRecentTask('route', 'failed', getErrorMessage(lastError), {
            submittedAt,
            jobId: lastAcceptedJobId,
            finishedAt: new Date().toISOString(),
          })
        );
        showToast(getErrorMessage(lastError));
      } else {
        showToast('路线仍在后台处理中，可稍后刷新');
      }
    } catch (error) {
      setRecentAsyncTask(
        createRecentTask('route', 'failed', getErrorMessage(error), {
          submittedAt,
          jobId: lastAcceptedJobId,
          finishedAt: new Date().toISOString(),
        })
      );
      showToast(getErrorMessage(error));
    } finally {
      setIsGeneratingRoute(false);
    }
  };

  const handleTopbarRouteScore = async () => {
    if (isScoringRoute) return;
    const routeId = routes[selRoute]?.route_id;
    if (!routeId) {
      showToast('未选择路线');
      return;
    }
    setIsScoringRoute(true);
    try {
      await scoreRoute(routeId, workspaceId);
      await fetchData();
      showToast('路线评分完成');
    } catch (error) {
      showToast(getErrorMessage(error));
    } finally {
      setIsScoringRoute(false);
    }
  };

  const handleHypothesisDecision = async (action: 'promote' | 'defer' | 'reject', explicitHypothesisId?: string) => {
    try {
      let hypothesisId = explicitHypothesisId?.trim();

      if (!hypothesisId) {
        const hypothesesResp = await listHypotheses(workspaceId);
        hypothesisId = hypothesesResp.items?.[0]?.hypothesis_id;
      }

      if (!hypothesisId) {
        const triggerResp = await listHypothesisTriggers(workspaceId);
        const triggerId = triggerResp.items?.[0]?.trigger_id;
        if (!triggerId) {
          showToast('无法生成可用假设');
          return;
        }
        const job = await generateHypothesis(workspaceId, [triggerId]);
        const submittedAt = new Date().toISOString();
        const acceptedJobId = String(job?.job_id || '').trim() || null;
        if (acceptedJobId) {
          setRecentAsyncTask(
            createRecentTask('hypothesis', 'running', '假设任务已提交，正在等待后端完成。', {
              submittedAt,
              jobId: acceptedJobId,
            })
          );
          try {
            await pollJob(
              acceptedJobId,
              TOPBAR_ASYNC_POLL_TIMEOUT_MS,
              TOPBAR_ASYNC_POLL_INTERVAL_MS
            );
          } catch (error) {
            if (isJobTimeoutError(error)) {
              setRecentAsyncTask(
                createRecentTask('hypothesis', 'running_background', '前端轮询已超时，任务可能仍在后台处理中。', {
                  submittedAt,
                  jobId: acceptedJobId,
                })
              );
              showToast(`假设任务已提交（job ${acceptedJobId}），当前仍在后台处理中`);
              return;
            }
            throw error;
          }
        }
        const hypothesesResp = await listHypotheses(workspaceId);
        hypothesisId = hypothesesResp.items?.[0]?.hypothesis_id;
      }

      if (!hypothesisId) {
        showToast('无法生成可用假设');
        return;
      }

      await decideHypothesis(hypothesisId, action, {
        workspace_id: workspaceId,
        note: `ui_${action}`,
        decision_source_type: 'ui',
        decision_source_ref: 'route_detail_hypothesis_card',
      });
      showToast('假设决策已提交');
      await fetchData();
    } catch (error) {
      showToast(getErrorMessage(error));
    }
  };

  if (loading) {
    return <div className="app flex-center" style={{ justifyContent: 'center' }}>加载中...</div>;
  }

  const selectedRoute = routes[selRoute];
  const hasActionableGraph = nodes.length > 1 && edges.length > 0;
  const hasRoutes = routes.length > 0;
  const nodeTypeStats = nodes.reduce<Record<string, number>>((acc, node) => {
    const key = String(node?.node_type || '').toLowerCase();
    if (!key) return acc;
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const activeQuestion = normalizeRouteTitle(selectedRoute?.title) || '当前工作区研究问题';
  const staleRouteCount = routes.filter((item) => item?.stale).length;
  const sortedSourceTimes = sources
    .map((item) => item?.updated_at || item?.created_at)
    .filter((v): v is string => Boolean(v))
    .sort();
  const latestSourceTime = sortedSourceTimes.length > 0 ? sortedSourceTimes[sortedSourceTimes.length - 1] : undefined;
  const latestSourceLabel = latestSourceTime ? new Date(latestSourceTime).toLocaleString('zh-CN') : '未知';
  const recentTaskTone =
    recentAsyncTask?.status === 'failed'
      ? 'var(--red)'
      : recentAsyncTask?.status === 'completed'
      ? 'var(--green)'
      : 'var(--amber)';
  const recentTaskStatusLabel =
    recentAsyncTask?.status === 'running_background'
      ? '处理中（前端轮询超时）'
      : recentAsyncTask?.status === 'running'
      ? '处理中'
      : recentAsyncTask?.status === 'completed'
      ? '已完成'
      : recentAsyncTask?.status === 'failed'
      ? '失败'
      : '';

  return (
    <div className="app" style={{ flexDirection: 'row' }}>
      {/* Sidebar */}
      <div className={`sidebar ${isSidebarOpen ? 'open' : 'closed'}`}>
        <div className="sidebar-header">
          {isSidebarOpen && <span className="logo">米罗尼基</span>}
          <button className="icon-btn" onClick={() => setIsSidebarOpen(!isSidebarOpen)}>
            {isSidebarOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
        <div className="nav-vertical">
          <button className={`nav-item ${currentPage === 'routes' || currentPage === 'detail' ? 'active' : ''}`} onClick={() => goto('routes')} title="研究路线">
            <Route size={18} />
            {isSidebarOpen && <span>研究路线</span>}
          </button>
          <button className={`nav-item ${currentPage === 'import' || currentPage === 'confirm' ? 'active' : ''}`} onClick={() => goto('import')} title="导入材料">
            <FileInput size={18} />
            {isSidebarOpen && <span>导入材料</span>}
          </button>
          <button className={`nav-item ${currentPage === 'workbench' ? 'active' : ''}`} onClick={() => goto('workbench')} title="图谱工作台">
            <Network size={18} />
            {isSidebarOpen && <span>图谱工作台</span>}
          </button>
          <button className={`nav-item ${currentPage === 'frontier' ? 'active' : ''}`} onClick={() => goto('frontier')} title="假设前沿">
            <Lightbulb size={18} />
            {isSidebarOpen && <span>假设前沿</span>}
          </button>
          <button className={`nav-item ${currentPage === 'failures' ? 'active' : ''}`} onClick={() => goto('failures')} title="失败记录">
            <AlertTriangle size={18} />
            {isSidebarOpen && <span>失败记录</span>}
          </button>
          <button className={`nav-item ${currentPage === 'packages' ? 'active' : ''}`} onClick={() => goto('packages')} title="知识包">
            <Package size={18} />
            {isSidebarOpen && <span>知识包</span>}
          </button>
          <button className={`nav-item ${currentPage === 'team' ? 'active' : ''}`} onClick={() => goto('team')} title="团队空间">
            <Users size={18} />
            {isSidebarOpen && <span>团队空间</span>}
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="main-content">
        <div className="topbar">
          <div className="flex-center gap-6">
            {!isSidebarOpen && (
              <button className="icon-btn" onClick={() => setIsSidebarOpen(true)}>
                <Menu size={18} />
              </button>
            )}
            <span className="workspace" title={normalizeRouteTitle(selectedRoute?.title) || `工作区 ${workspaceId}`}>
              {shortenLabel(normalizeRouteTitle(selectedRoute?.title) || `工作区 ${workspaceId}`)}
            </span>
          </div>
          <div className="topbar-actions">
            <button className="btn" onClick={() => goto('failures')}>记录失败</button>
            <button className="btn" onClick={openWorkspaceEditor}>切换工作区</button>
            <button
              className="btn"
              onClick={handleTopbarRouteGenerate}
              disabled={!hasActionableGraph || isGeneratingRoute}
              title={
                isGeneratingRoute
                  ? '路线任务正在提交或轮询中'
                  : !hasActionableGraph
                  ? '至少需要 2 个节点且存在 1 条连接，才能生成路线'
                  : undefined
              }
            >
              {isGeneratingRoute ? '路线生成中...' : '生成路线'}
            </button>
            <button
              className="btn"
              onClick={handleTopbarRouteScore}
              disabled={!hasRoutes || isScoringRoute}
              title={!hasRoutes ? '当前没有可评分路线，请先生成路线' : undefined}
            >
              {isScoringRoute ? '评分中...' : '路线评分'}
            </button>
            <button
              className="btn btn-p"
              disabled={isGeneratingHypothesis || !hasActionableGraph}
              title={
                isGeneratingHypothesis
                  ? '假设任务正在提交或轮询中'
                  : !hasActionableGraph
                  ? '至少需要 2 个节点且存在 1 条连接，才能生成假设'
                  : undefined
              }
              onClick={handleTopbarHypothesisGenerate}
            >
              {isGeneratingHypothesis ? '生成假设中...' : '生成假设'}
            </button>
            {isWorkspaceEditorOpen && (
              <>
                <input
                  className="form-input"
                  style={{ width: '220px' }}
                  value={workspaceDraft}
                  onChange={(event) => setWorkspaceDraft(event.target.value)}
                  placeholder="输入工作区编号"
                />
                <button className="btn btn-p" onClick={confirmWorkspaceSwitch}>确认</button>
                <button className="btn" onClick={() => setIsWorkspaceEditorOpen(false)}>取消</button>
              </>
            )}
          </div>
        </div>

        {recentAsyncTask && (
          <div className="ctx-bar" style={{ padding: '10px 20px', background: 'var(--bg2)' }}>
            <div className="ctx-meta" style={{ justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px' }}>
              <div style={{ display: 'grid', gap: '4px' }}>
                <div style={{ fontSize: '12px', color: recentTaskTone }}>
                  {recentAsyncTask.kind === 'route' ? '路线任务' : '假设任务'} · {recentTaskStatusLabel}
                </div>
                <div className="meta" style={{ fontSize: '12px' }}>{recentAsyncTask.message}</div>
                <div className="meta">
                  job_id={recentAsyncTask.jobId || '未返回'} · 提交 {formatTaskDateTime(recentAsyncTask.submittedAt)} · 完成 {formatTaskDateTime(recentAsyncTask.finishedAt)}
                </div>
              </div>
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                {recentAsyncTask.status === 'running_background' && (
                  <button className="btn" onClick={() => void fetchData()}>
                    立即刷新
                  </button>
                )}
                {currentPage !== recentAsyncTask.targetPage && (
                  <button className="btn" onClick={() => goto(recentAsyncTask.targetPage)}>
                    {recentAsyncTask.targetLabel}
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {(currentPage === 'routes' || currentPage === 'detail') && (
          <div className="ctx-bar">
            <div className="ctx-q">{activeQuestion}</div>
            <div className="ctx-meta">
              <div className="meta"><div className="mdot mdot-g"></div>{nodes.length} 个节点 · 工作区 {workspaceId}</div>
              <div className="meta"><div className="mdot mdot-a"></div>{routes.length} 条路线</div>
              <div className="meta"><div className="mdot mdot-r"></div>最近来源更新 · {latestSourceLabel}</div>
              {staleRouteCount > 0 && <span className="stale-badge">{staleRouteCount} 条路线需更新</span>}
            </div>
          </div>
        )}

        <div className={`page ${currentPage === 'routes' ? 'active' : ''}`}>
          {currentPage === 'routes' && (
            <RoutesPage
              routes={routes}
              selRoute={selRoute}
              setSelRoute={setSelRoute}
              goto={goto}
              onGenerateRoute={handleTopbarRouteGenerate}
              isGeneratingRoute={isGeneratingRoute}
              nodeCount={nodes.length}
              edgeCount={edges.length}
              nodeTypeStats={nodeTypeStats}
            />
          )}
        </div>
        <div className={`page ${currentPage === 'detail' ? 'active' : ''}`}>
          {currentPage === 'detail' && (
            <RouteDetailPage
              routes={routes}
              selRoute={selRoute}
              goto={goto}
              showToast={showToast}
              workspaceId={workspaceId}
              hypotheses={hypotheses}
              failuresCount={failures.length}
              nodeCount={nodes.length}
              edgeCount={edges.length}
              nodeTypeStats={nodeTypeStats}
              onHypothesisDecision={handleHypothesisDecision}
            />
          )}
        </div>
        <div className={`page ${currentPage === 'import' ? 'active' : ''}`}>
          {currentPage === 'import' && (
            <ImportPage
              goto={goto}
              showToast={showToast}
              workspaceId={workspaceId}
              sources={sources}
              onImportCompleted={fetchData}
              onExtractionCompleted={setLastExtractionContext}
            />
          )}
        </div>
        <div className={`page ${currentPage === 'confirm' ? 'active' : ''}`}>
          {currentPage === 'confirm' && (
            <ConfirmPage
              candidates={candidates}
              extractionContext={lastExtractionContext}
              fetchData={fetchData}
              goto={goto}
              showToast={showToast}
              workspaceId={workspaceId}
            />
          )}
        </div>
        <div className={`page ${currentPage === 'workbench' ? 'active' : ''}`}>
          {currentPage === 'workbench' && <WorkbenchPage initialNodes={nodes} initialEdges={edges} edgeColors={edgeColors} goto={goto} showToast={showToast} workspaceId={workspaceId} onRefresh={fetchData} />}
        </div>
        <div className={`page ${currentPage === 'frontier' ? 'active' : ''}`}>
          {currentPage === 'frontier' && (
            <FrontierPage
              workspaceId={workspaceId}
              sources={sources}
              candidates={candidates}
              showToast={showToast}
              goto={goto}
              onRefresh={fetchData}
            />
          )}
        </div>
        <div className={`page ${currentPage === 'failures' ? 'active' : ''}`}>
          {currentPage === 'failures' && <FailuresPage failures={failures} selFail={selFail} setSelFail={setSelFail} goto={goto} showToast={showToast} workspaceId={workspaceId} onValidationSubmitted={fetchData} />}
        </div>
        <div className={`page ${currentPage === 'packages' ? 'active' : ''}`}>
          {currentPage === 'packages' && <PackagesPage packages={packages} selPkg={selPkg} setSelPkg={setSelPkg} goto={goto} showToast={showToast} workspaceId={workspaceId} />}
        </div>
        <div className={`page ${currentPage === 'team' ? 'active' : ''}`}>
          {currentPage === 'team' && (
            <>
              <TeamPage goto={goto} packages={packages} />
              {SHOW_INTERNAL_TOOLS && (
                <details className="ops-panel">
                  <summary>展开高级诊断与维护（需要内部 ID）</summary>
                  <ResearchOpsPanel
                    workspaceId={workspaceId}
                    selectedRouteId={routes[selRoute]?.route_id}
                    selectedPackageId={selPkg === null ? undefined : packages[selPkg]?.package_id}
                    hasActionableGraph={hasActionableGraph}
                    showToast={showToast}
                    onRefresh={fetchData}
                  />
                </details>
              )}
            </>
          )}
        </div>
      </div>

      <div id="toast" style={{
        position: 'fixed', bottom: '20px', left: '50%', transform: toastMsg ? 'translateX(-50%) translateY(0)' : 'translateX(-50%) translateY(20px)',
        background: 'var(--text)', color: 'var(--bg)', padding: '8px 16px', borderRadius: '8px', fontSize: '13px',
        opacity: toastMsg ? 1 : 0, transition: 'all .25s', pointerEvents: 'none', zIndex: 999, whiteSpace: 'nowrap'
      }}>
        {toastMsg}
      </div>
    </div>
  );
}

