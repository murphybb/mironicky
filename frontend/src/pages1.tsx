import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  confirmCandidates,
  rejectCandidates,
  importSource,
  extractSource,
  getExtractionResult,
  getJobStatus,
  getAsyncJobUiLabel,
  getAsyncJobUiState,
  hydrateConfirmedCandidatesToGraph,
  listSources,
  pollJob,
  getErrorMessage,
} from './api';
import { getCandidateBulkConfirmDialogCopy } from './candidate-bulk-actions-helpers';

function formatDate(value?: string) {
  if (!value) return '';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleDateString('zh-CN');
}

function formatDateTime(value?: string | null) {
  if (!value) return '--';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return String(value);
  return dt.toLocaleString('zh-CN', { hour12: false });
}

function formatDurationLabel(seconds?: number | null) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return '--';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}分${String(secs).padStart(2, '0')}秒`;
}

function typeLabel(type: string) {
  if (type === 'paper') return '文献';
  if (type === 'note') return '笔记';
  if (type === 'feedback') return '反馈';
  if (type === 'failure_record') return '失败记录';
  if (type === 'dialogue') return '对话';
  return type || '来源';
}

function candidateTypeLabel(type: string) {
  const normalized = String(type || '').toLowerCase();
  if (normalized === 'evidence' || normalized === 'e') return '证据';
  if (normalized === 'assumption' || normalized === 'a') return '推理前提';
  if (normalized === 'conflict' || normalized === 'c') return '冲突信号';
  if (normalized === 'failure' || normalized === 'f') return '失败记录';
  if (normalized === 'gap' || normalized === 'validation' || normalized === 'g') return '证据缺口';
  return type || '候选';
}

function semanticTypeLabel(type: string) {
  const normalized = String(type || '').toLowerCase();
  const map: Record<string, string> = {
    concept: '概念',
    entity: '实体',
    claim: '主张',
    hypothesis: '研究假设',
    evidence: '证据',
    method: '方法',
    result: '结果',
    finding: '发现',
    definition: '定义',
    condition: '条件',
    limitation: '局限',
    citation: '引用',
    question: '问题',
  };
  return map[normalized] || type;
}

function factorLabel(name: string) {
  const normalized = String(name || '').trim();
  const map: Record<string, string> = {
    confirmed_evidence_coverage: '已确认关键证据覆盖率',
    next_action_clarity: '下一步动作清晰度',
    execution_cost_feasibility: '执行成本可行性',
    validation_backing: '验证支撑强度',
    upstream_inspiration: '上游启发价值',
    assumption_burden: '前提依赖风险',
    evidence_quality: '证据质量',
    cross_source_consistency: '跨来源一致性',
    unresolved_conflict_pressure: '未解冲突压力',
    failure_pressure: '失败压力',
    private_dependency_pressure: '私有依赖压力',
    missing_validation_pressure: '验证缺口压力',
    execution_time_feasibility: '执行时间可行性',
    expected_signal_strength: '预期信号强度',
    dependency_readiness: '依赖就绪度',
    traceability_completeness: '可追溯完整度',
  };
  return map[normalized] || '其他评估因子';
}

function normalizeValidationAction(text?: string) {
  const raw = String(text || '').trim();
  if (!raw) return '暂无验证动作。';
  const matched = raw.match(/^Validate conclusion node\s+(.+?)\s+with an ablation or controlled experiment$/i);
  if (matched) {
    return `请围绕结论节点“${matched[1]}”设计对照实验或消融实验，并验证关键证据是否稳定支撑该结论。`;
  }
  const executeMatched = raw.match(/^Execute validation:\s*(.+)$/i);
  if (executeMatched) {
    return `执行验证：${executeMatched[1]}`;
  }
  return raw.replace(/\bnode_[a-z0-9_]+\b/gi, '相关节点');
}

function normalizeExtractionStatus(status?: string | null, errorCode?: string | null) {
  return getAsyncJobUiLabel(status, errorCode);
}

function normalizeDegradedReason(reason?: string | null) {
  const key = String(reason || '').trim().toLowerCase();
  if (!key) return '本次结果使用了降级路径，请优先复核候选质量。';
  if (key === 'research.llm_timeout') return '模型处理超时，本次结果由降级路径补齐，建议复核候选质量。';
  if (key === 'research.llm_invalid_output') return '模型输出不稳定，本次结果由降级路径补齐，建议复核候选质量。';
  return `本次结果触发了降级路径（${key}），建议复核候选质量。`;
}

function normalizeSourceMountLabel(sourceSpan?: { mount?: string; desc?: string; text?: string } | null) {
  const mount = String(sourceSpan?.mount || '').trim();
  const desc = String(sourceSpan?.desc || '').trim();
  const text = String(sourceSpan?.text || '').trim();
  const parts = [mount || '未提供定位'];
  if (desc && desc !== mount) parts.push(desc);
  if (text && text !== desc) parts.push(text.length > 48 ? `${text.slice(0, 48)}...` : text);
  return parts.filter(Boolean).join(' · ');
}

function normalizeRouteTitle(title?: string) {
  const raw = String(title || '').trim();
  if (!raw) return '未命名路线';
  return raw.replace(/^route:\s*/i, '').trim();
}

function relationTagLabel(tag?: string) {
  const key = String(tag || '').toLowerCase();
  const map: Record<string, string> = {
    direct_support: '直接支撑',
    recombination: '重组支撑',
    recombined_support: '重组支撑',
    conflict_path: '冲突路径',
    weak_support: '弱支撑',
    upstream_inspiration: '上游启发',
  };
  return map[key] || '未标注';
}

function normalizeRouteSummary(summary?: string) {
  const raw = String(summary || '').trim();
  if (!raw) return '暂无路线摘要。';
  return raw
    .replace(/\bnode_[a-z0-9_]+\b/gi, '相关节点')
    .replace(/Risk signal from/gi, '风险信号来自')
    .replace(/validation backing/gi, '验证支撑')
    .replace(/upstream inspiration/gi, '上游启发');
}

function normalizeRiskText(text?: string) {
  const raw = String(text || '').trim();
  if (!raw) return '当前未检测到冲突证据。';
  return raw
    .replace(/Risk signal from/gi, '风险信号来自')
    .replace(/because/gi, '，原因：');
}

function isActionableHypothesis(hypothesis: any) {
  const status = String(hypothesis?.status || '').toLowerCase();
  if (!status) return true;
  const terminalStatuses = new Set([
    'promoted_for_validation',
    'promoted',
    'accepted',
    'deferred',
    'rejected',
    'archived',
    'resolved',
    'validated',
    'invalidated',
  ]);
  return !terminalStatuses.has(status);
}

function sourceErrorDetails(src: any): Record<string, unknown> {
  const error = src?.last_extract_error;
  return error && typeof error === 'object' && (error as any).details && typeof (error as any).details === 'object'
    ? ((error as any).details as Record<string, unknown>)
    : {};
}

function sourceStatusMeta(src: any) {
  const sourceStatus = String(src?.status || '').toLowerCase();
  const extractStatus = String(src?.last_extract_status || '').toLowerCase();
  if (sourceStatus === 'extract_failed' || sourceStatus === 'failed' || extractStatus === 'failed') {
    return { className: 'sb-failed', label: '抽取失败' };
  }
  if (sourceStatus === 'extracted' || extractStatus === 'succeeded' || extractStatus === 'completed') {
    return { className: 'sb-done', label: '已抽取' };
  }
  if (sourceStatus === 'parsed') return { className: 'sb-parsed', label: '已解析' };
  if (sourceStatus === 'raw') return { className: 'sb-raw', label: '原始' };
  return { className: 'sb-pending', label: '待处理' };
}

function normalizeSourceDerivedStatus(src: any): string {
  const extractStatus = String(src?.last_extract_status || '').toLowerCase();
  if (extractStatus) return extractStatus;
  const sourceStatus = String(src?.status || '').toLowerCase();
  if (sourceStatus === 'extracted') return 'succeeded';
  if (sourceStatus === 'extract_failed') return 'failed';
  if (sourceStatus === 'parsed' || sourceStatus === 'processing') return 'running';
  return sourceStatus;
}

function inspectSourceMetadataConsistency(src: any) {
  const metadata = src?.metadata && typeof src.metadata === 'object' ? src.metadata : {};
  const publicationYear = Number((metadata as any)?.publication_year);
  const textForYear = `${src?.title || ''}\n${src?.content || ''}`;
  const yearMatches = Array.from(new Set((textForYear.match(/\b(19|20)\d{2}\b/g) || []).map((item) => Number(item))));
  const suggestedYear = yearMatches.length > 0 ? Math.max(...yearMatches) : null;
  const yearMismatch =
    Number.isFinite(publicationYear) &&
    suggestedYear !== null &&
    suggestedYear >= 1900 &&
    Math.abs(Number(publicationYear) - suggestedYear) >= 1;

  const topicClusters = Array.isArray((metadata as any)?.topic_clusters) ? (metadata as any).topic_clusters : [];
  const rawKeywords = topicClusters
    .flatMap((cluster: any) => (Array.isArray(cluster?.keywords) ? cluster.keywords : []))
    .map((keyword: any) => String(keyword || '').trim())
    .filter(Boolean);

  const pollutedKeywords = rawKeywords.filter((keyword: string) =>
    /[\\/:]/.test(keyword) ||
    /^(downloads?|users?|desktop|html|tmp|file|local)$/i.test(keyword) ||
    /(?:\.pdf|\.docx)$/i.test(keyword) ||
    /guohangjiang|nal_report/i.test(keyword)
  );
  const cleanedKeywords = rawKeywords.filter((keyword: string) => !pollutedKeywords.includes(keyword));

  const coreSignals = ['武汉大学', '品牌', '声誉', '舆情', '治理', '传播', '风险', '危机'];
  const titleAndContent = `${src?.title || ''}\n${src?.content || ''}`;
  const expectedCore = coreSignals.filter((signal) => titleAndContent.includes(signal));
  const missingCore = expectedCore.filter(
    (signal) => !cleanedKeywords.some((keyword: string) => keyword.includes(signal))
  );
  const suggestedTopics = cleanedKeywords.length > 0 ? cleanedKeywords.slice(0, 5) : expectedCore.slice(0, 5);

  return {
    publicationYear: Number.isFinite(publicationYear) ? publicationYear : null,
    suggestedYear,
    yearMismatch,
    pollutedKeywords,
    missingCore,
    suggestedTopics,
  };
}

export function RoutesPage({
  routes,
  selRoute,
  setSelRoute,
  goto,
  onGenerateRoute,
  isGeneratingRoute = false,
  nodeCount = 0,
  edgeCount = 0,
  nodeTypeStats = {},
}: any) {
  const [routeFilter, setRouteFilter] = useState<'all' | 'active' | 'stale'>('all');
  const displayedRoutes = useMemo(() => {
    return routes
      .map((rt: any, index: number) => ({ rt, index }))
      .filter(({ rt }: any) => {
        if (routeFilter === 'active') return rt?.status === 'active' && !rt?.stale;
        if (routeFilter === 'stale') return Boolean(rt?.stale);
        return true;
      });
  }, [routes, routeFilter]);

  useEffect(() => {
    if (!displayedRoutes.length) return;
    const selectedStillVisible = displayedRoutes.some((item: any) => item.index === selRoute);
    if (!selectedStillVisible) {
      setSelRoute(displayedRoutes[0].index);
    }
  }, [displayedRoutes, selRoute, setSelRoute]);

  const r = routes[selRoute];
  if (!r) {
    const hasChainInputs = nodeCount > 1 && edgeCount > 0;
    const evidenceCount = Number(nodeTypeStats?.evidence || nodeTypeStats?.e || 0);
    const assumptionCount = Number(nodeTypeStats?.assumption || nodeTypeStats?.a || 0);
    const conflictCount = Number(nodeTypeStats?.conflict || 0);
    const failureCount = Number(nodeTypeStats?.failure || nodeTypeStats?.f || 0);
    return (
      <div className="routes-layout">
        <div className="route-list-panel">
          <div className="empty" style={{ padding: '16px' }}>
            <div className="empty-desc">
              {hasChainInputs
                ? `当前图谱已满足成链门槛（${nodeCount} 节点 / ${edgeCount} 条连接），但还没有可展示路线。当前结构：证据 ${evidenceCount}，前提 ${assumptionCount}，冲突 ${conflictCount}，失败 ${failureCount}。`
                : `当前图谱为 ${nodeCount} 个节点 / ${edgeCount} 条连接，尚不满足成链条件（至少 2 个节点且 1 条连接）。`}
            </div>
            <div className="topbar-actions" style={{ marginTop: '12px' }}>
              {hasChainInputs && (
                <button
                  className="btn btn-p"
                  onClick={() => onGenerateRoute?.()}
                  disabled={isGeneratingRoute}
                  title={isGeneratingRoute ? '路线任务正在提交或轮询中' : undefined}
                >
                  {isGeneratingRoute ? '生成中...' : '立即生成路线'}
                </button>
              )}
              <button className="btn" onClick={() => goto('import')}>前往导入资料</button>
              <button className="btn" onClick={() => goto('confirm')}>前往候选确认</button>
            </div>
          </div>
        </div>
        <div className="preview-panel">
          <div className="empty" style={{ padding: '16px' }}>
            <div className="empty-desc">完成入图后可在这里查看路线预览。</div>
            <button className="btn btn-p" onClick={() => goto('workbench')} style={{ marginTop: '12px' }}>前往图谱工作台</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="routes-layout">
      <div className="route-list-panel">
        <div className="panel-hdr">
          <span className="panel-lbl">候选路线</span>
          <div className="chips">
            <button className={`chip ${routeFilter === 'all' ? 'on' : ''}`} onClick={() => setRouteFilter('all')}>全部</button>
            <button className={`chip ${routeFilter === 'active' ? 'on' : ''}`} onClick={() => setRouteFilter('active')}>进行中</button>
            <button className={`chip ${routeFilter === 'stale' ? 'on' : ''}`} onClick={() => setRouteFilter('stale')}>需更新</button>
          </div>
        </div>
        <div className="rlist">
          {displayedRoutes.map(({ rt, index }: any) => {
            const lvClass = rt.confidence_grade === 'high' ? 'h' : rt.confidence_grade === 'medium' ? 'm' : 'l';
            const tag = rt.relation_tags?.[0] || '未标注';
            return (
              <div key={rt.route_id} className={`rcard lv-${lvClass} ${selRoute === index ? 'sel' : ''}`} onClick={() => setSelRoute(index)}>
                <div className="rc-top">
                  <div className="rc-title">{normalizeRouteTitle(rt.title)}</div>
                  <div className="rc-score">
                    <div className={`sc-num lv-${lvClass}`}>{rt.confidence_score}</div>
                    <div className="sc-lbl">置信度</div>
                  </div>
                </div>
                <div className="rc-sum">{normalizeRouteSummary(rt.summary)}</div>
                <div className="rc-factors">
                  {rt.top_factors?.map((f: any, fi: number) => (
                    <React.Fragment key={fi}>
                      <div className="factor">
                    <span className={`fv ${f.status === 'positive' ? 'pos' : 'neg'}`}>{f.normalized_value > 0 ? '+' : ''}{f.normalized_value}</span>
                        <span className="fn">{factorLabel(f.factor_name)}</span>
                  </div>
                </React.Fragment>
                  ))}
                </div>
                <div className="rc-foot">
                  <span className={`rbadge ${String(tag).toLowerCase().includes('direct') ? 'direct' : 'recombo'}`}>{relationTagLabel(tag)}</span>
                  {rt.stale && <span className="stale-tag">需更新</span>}
                </div>
              </div>
            );
          })}
          {!displayedRoutes.length && <div className="text-muted">当前筛选条件下没有路线。</div>}
        </div>
      </div>
      <div className="preview-panel">
        <div className="prev-hdr">
          <span className="panel-lbl">推理链预览</span>
          <div className="topbar-actions">
            <button className="btn" onClick={() => goto('detail')}>路线详情</button>
            <button className="btn btn-p" onClick={() => goto('workbench')}>进入工作台</button>
          </div>
        </div>
        <div className="prev-body">
          <div className="prev-title">{normalizeRouteTitle(r.title)}</div>
          <div className="score-row">
            <div className={`big-score lv-${r.confidence_grade === 'high' ? 'h' : r.confidence_grade === 'medium' ? 'm' : 'l'}`}>{r.confidence_score}</div>
            <div className="pf-list">
              {r.top_factors?.map((f: any, fi: number) => (
                <div key={fi} className="pf">
                  <span className={`pf-v ${f.status === 'positive' ? 'pos' : 'neg'}`}>{f.normalized_value > 0 ? '+' : ''}{f.normalized_value}</span>
                  <div className={`pf-bar ${f.status === 'positive' ? 'pos' : 'neg'}`} style={{ width: `${Math.abs(f.normalized_value) * 2}px` }}></div>
                  <span className="pf-n">{factorLabel(f.factor_name)}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="chain-lbl">推理链摘要</div>
          <div className="cnode">
            <div className="ncol"><div className="ndot nd-c"></div><div className="nline"></div></div>
            <div className="ncont">
              <div className="ntype">结论</div>
              <div className="nlabel">{r.conclusion}</div>
              <div className="ntags"><span className="ntag info">结论节点</span></div>
            </div>
          </div>
          {r.key_supports?.map((ev: any, i: number) => (
            <div key={i} className="cnode">
              <div className="ncol"><div className="ndot nd-e"></div>{(i < r.key_supports.length - 1 || r.assumptions?.length > 0) && <div className="nline"></div>}</div>
              <div className="ncont">
                <div className="ntype">证据</div>
                <div className="nlabel">{ev}</div>
              </div>
            </div>
          ))}
          {r.assumptions?.map((asm: any, i: number) => (
            <div key={i} className="cnode">
              <div className="ncol"><div className="ndot nd-a"></div>{i < r.assumptions.length - 1 && <div className="nline"></div>}</div>
              <div className="ncont">
                <div className="ntype">推理前提</div>
                <div className="nlabel">{asm}</div>
                <div className="ntags">{r.risks?.includes(asm) && <span className="ntag risk">高风险</span>}</div>
              </div>
            </div>
          ))}
          <div className="divider" style={{ marginTop: '16px' }}></div>
          <div className="nv-box">
            <div className="nv-lbl">下一步验证</div>
            <div className="nv-text">{normalizeValidationAction(r.next_validation_action)}</div>
            <button className="nv-btn" onClick={() => goto('detail')}>查看完整简报</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function RouteDetailPage({
  routes,
  selRoute,
  goto,
  onHypothesisDecision,
  hypotheses = [],
  failuresCount = 0,
  nodeCount = 0,
  edgeCount = 0,
  nodeTypeStats = {},
}: any) {
  const r = routes[selRoute];
  if (!r) {
    const evidenceCount = Number(nodeTypeStats?.evidence || nodeTypeStats?.e || 0);
    const assumptionCount = Number(nodeTypeStats?.assumption || nodeTypeStats?.a || 0);
    return (
      <div className="detail-layout">
        <div className="detail-main">
          <button className="back-btn" onClick={() => goto('routes')}>返回路线列表</button>
          <div className="empty" style={{ padding: '16px' }}>
            <div className="empty-desc">
              当前无路线详情。图谱现状：{nodeCount} 节点 / {edgeCount} 连接（证据 {evidenceCount}，前提 {assumptionCount}）。请先补齐可连接证据链后再生成路线。
            </div>
            <div className="topbar-actions" style={{ marginTop: '12px' }}>
              <button className="btn" onClick={() => goto('import')}>前往导入资料</button>
              <button className="btn btn-p" onClick={() => goto('workbench')}>前往图谱工作台</button>
            </div>
          </div>
        </div>
        <div className="detail-side">
          <div className="side-hdr">候选假设</div>
          <div className="side-body">
            <div style={{ fontSize: '12px', color: 'var(--text2)', lineHeight: 1.6 }}>
              先完成入图并生成路线后，这里才会显示路线相关假设。            </div>
          </div>
        </div>
      </div>
    );
  }
  const lvClass = r.confidence_grade === 'high' ? 'h' : r.confidence_grade === 'medium' ? 'm' : 'l';

  const routeHypotheses = useMemo(() => {
    if (!Array.isArray(hypotheses)) return [];
    const routeId = String(r.route_id || '');
    const routeNodeIds = new Set((Array.isArray(r.route_node_ids) ? r.route_node_ids : []).map(String));

    const collectRefs = (value: unknown, bucket: Set<string>) => {
      if (!value) return;
      if (typeof value === 'string') {
        bucket.add(value);
        return;
      }
      if (Array.isArray(value)) {
        value.forEach((item) => collectRefs(item, bucket));
        return;
      }
      if (typeof value === 'object') {
        Object.values(value as Record<string, unknown>).forEach((item) => collectRefs(item, bucket));
      }
    };

    const extractRefIds = (hyp: any) => {
      const refs = new Set<string>();
      collectRefs(hyp?.route_id, refs);
      collectRefs(hyp?.route_ids, refs);
      collectRefs(hyp?.reasoning_chain_id, refs);
      collectRefs(hyp?.reasoning_chain_ids, refs);
      collectRefs(hyp?.related_object_ids, refs);
      collectRefs(hyp?.trigger_object_ids, refs);
      collectRefs(hyp?.object_ref_id, refs);
      collectRefs(hyp?.object_ref_ids, refs);
      return refs;
    };

    const related = hypotheses.filter((hyp: any) => {
      const refs = extractRefIds(hyp);
      return Array.from(refs).some((id) => id === routeId || routeNodeIds.has(id));
    });

    const scoped = (related.length > 0 ? related : hypotheses).filter((hyp: any) => isActionableHypothesis(hyp));
    return scoped.slice(0, 4);
  }, [hypotheses, r.route_id, r.route_node_ids]);

  const riskText = normalizeRiskText(r.risks?.[0]);
  const assumptionCount = r.assumptions?.length || 0;
  const riskCount = r.risks?.length || 0;

  return (
    <div className="detail-layout">
      <div className="detail-main">
        <button className="back-btn" onClick={() => goto('routes')}>返回路线列表</button>
        <div className="hero-box">
          <div className="hero-title">{normalizeRouteTitle(r.title)}</div>
          <div className="hero-meta">
            <span className={`hero-score lv-${lvClass}`}>{r.confidence_score}</span>
            <span style={{ fontSize: '11px', color: 'var(--text3)', fontFamily: 'var(--mono)' }}>置信度</span>
            <span className={`status-pill ${r.status === 'active' ? 'sp-active' : 'sp-stale'}`}>{r.status === 'active' ? '进行中' : '需更新'}</span>
            {r.relation_tags?.[0] && <span className="status-pill" style={{ background: 'var(--blue-bg)', color: 'var(--blue)', borderColor: 'var(--blue-border)' }}>{relationTagLabel(r.relation_tags[0])}</span>}
          </div>
        </div>

        <div className="section">
          <div className="sec-title">{`关键证据（${r.key_supports?.length || 0} / 6）`}</div>
          {r.key_supports?.map((ev: any, i: number) => (
            <div key={i} className="ev-card">
              <div className="ev-top">
                <span className="ev-title">证据节点</span>
                <span className="ev-src">已抽取</span>
              </div>
              <div className="ev-body">{ev}</div>
            </div>
          ))}
          {!r.key_supports?.length && <div className="text-muted">暂无证据节点。</div>}
        </div>

        <div className="section">
          <div className="sec-title">{`推理前提（${assumptionCount}）`}</div>
          {riskCount > 0 && (
            <div className="text-muted" style={{ marginBottom: '8px' }}>
              其中 {riskCount} 条涉及高风险提示，详见下方“冲突与风险”。
            </div>
          )}
          {r.assumptions?.map((asm: any, i: number) => {
            const isRisk = r.risks?.includes(asm);
            return (
              <div key={i} className="assume-card" style={!isRisk ? { borderColor: 'var(--border)', background: 'var(--bg2)' } : {}}>
                <div className="assume-label" style={!isRisk ? { color: 'var(--text2)' } : {}}>{asm}</div>
                <div className="ntags">
                  {isRisk && <span className="ntag warn">高风险</span>}
                </div>
              </div>
            );
          })}
          {!r.assumptions?.length && <div className="text-muted">暂无推理前提。</div>}
        </div>

        <div className="section">
          <div className="sec-title">冲突与风险</div>
          <div className="conflict-card">
            <div style={{ fontSize: '12px', color: 'var(--red)', fontWeight: 500, marginBottom: '4px' }}>风险提示</div>
            <div style={{ fontSize: '12px', color: 'var(--text2)', lineHeight: 1.5 }}>{riskText}</div>
          </div>
        </div>

        <div className="section">
          <div className="sec-title">下一步验证动作</div>
          <div className="nv-box">
            <div className="nv-lbl">验证目标</div>
            <div className="nv-text">{normalizeValidationAction(r.next_validation_action)}</div>
            <button className="nv-btn" onClick={() => goto(failuresCount > 0 ? 'failures' : 'workbench')}>
              {failuresCount > 0 ? '提交验证结果' : '前往工作台记录失败'}
            </button>
            <div className="text-muted" style={{ marginTop: '8px' }}>
              {failuresCount > 0 ? '将进入失败记录页并提交本轮验证结果。' : '当前尚无失败记录，请先在工作台选中节点后点击“挂载失败”。'}
            </div>
          </div>
        </div>
      </div>

      <div className="detail-side">
        <div className="side-hdr">候选假设</div>
        <div className="side-body">
          {routeHypotheses.map((hyp: any) => (
            <div className="hyp-card" key={hyp.hypothesis_id || hyp.title}>
               <div className="hyp-title">{hyp.title || hyp.statement || '未命名假设'}</div>
              <div className="hyp-body">{normalizeRouteSummary(hyp.summary || hyp.rationale || '暂无假设摘要。')}</div>
              <div className="hyp-actions">
                <button className="hyp-btn accept" onClick={() => onHypothesisDecision?.('promote', hyp.hypothesis_id)}>接受</button>
                <button className="hyp-btn" onClick={() => onHypothesisDecision?.('defer', hyp.hypothesis_id)}>延后</button>
                <button className="hyp-btn" style={{ color: 'var(--red)' }} onClick={() => onHypothesisDecision?.('reject', hyp.hypothesis_id)}>拒绝</button>
              </div>
            </div>
          ))}
          {routeHypotheses.length === 0 && (
            <div style={{ fontSize: '12px', color: 'var(--text2)', lineHeight: 1.6, marginBottom: '8px' }}>
              当前没有可操作的候选假设。你可以先在顶部触发“生成假设”。            </div>
          )}

          <div className="side-hdr" style={{ margin: '0 -16px', padding: '12px 16px 10px' }}>相关检索</div>
          <div style={{ marginTop: '12px' }}>
              <div style={{ fontSize: '12px', color: 'var(--text2)', lineHeight: 1.6, marginBottom: '8px' }}>
                当前路线标签：{(Array.isArray(r.relation_tags) ? r.relation_tags : []).map((item: string) => relationTagLabel(item)).join('、') || '无'}
              </div>
            <button className="btn" style={{ fontSize: '11px', width: '100%' }} onClick={() => goto('import')}>查看来源材料</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ImportPage({ goto, showToast, workspaceId, onImportCompleted, onExtractionCompleted, sources = [] }: any) {
  const titleRef = useRef<HTMLInputElement>(null);
  const contentRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedSourceType, setSelectedSourceType] = useState<'paper' | 'note' | 'feedback' | 'failure_record'>('paper');
  const [expandedSourceId, setExpandedSourceId] = useState<string | null>(null);
  const [retryingSourceId, setRetryingSourceId] = useState<string | null>(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [urlInput, setUrlInput] = useState('');

  const isSucceededStatus = (status?: string | null) => ['succeeded', 'completed'].includes(String(status || '').toLowerCase());
  const isFailedStatus = (status?: string | null) => ['failed', 'cancelled', 'canceled'].includes(String(status || '').toLowerCase());

  const visibleSources = useMemo(() => {
    const items = Array.isArray(sources) ? [...sources] : [];
    items.sort((a: any, b: any) => {
      const ta = new Date(a?.updated_at || a?.created_at || 0).getTime();
      const tb = new Date(b?.updated_at || b?.created_at || 0).getTime();
      return tb - ta;
    });
    return items.slice(0, 3);
  }, [sources]);

  const fileToBase64 = async (file: File): Promise<string> => {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    bytes.forEach((byte) => {
      binary += String.fromCharCode(byte);
    });
    return btoa(binary);
  };

  const runExtractionForSource = async (sourceId: string) => {
    const acceptedJob = await extractSource(sourceId, workspaceId);
    onExtractionCompleted?.({
      sourceId,
      jobId: acceptedJob?.job_id || null,
      candidateBatchId: acceptedJob?.result_ref?.resource_id || null,
      status: String(acceptedJob?.status || 'running').toLowerCase(),
      backendStatus: String(acceptedJob?.status || 'running').toLowerCase(),
      jobCreatedAt: acceptedJob?.created_at || null,
      jobStartedAt: acceptedJob?.started_at || null,
      jobFinishedAt: acceptedJob?.finished_at || null,
      lastSyncedAt: new Date().toISOString(),
      candidateIds: undefined,
      error: null,
      degraded: false,
      degradedReason: null,
      partialFailureCount: 0,
    });
    goto('confirm');
    let finishedJob: any = acceptedJob;
    let pollErrorEnvelope: any = null;
    if (acceptedJob?.job_id) {
      try {
        // PDF/长文本抽取通常超 20s，放宽前端轮询窗口避免“假超时”。
        finishedJob = await pollJob(acceptedJob.job_id, 300000, 1800);
      } catch (error) {
        pollErrorEnvelope = (error as any)?.envelope || { message: getErrorMessage(error) };
        try {
          finishedJob = await getJobStatus(acceptedJob.job_id);
        } catch {
          finishedJob = {
            ...acceptedJob,
            status: 'failed',
            error: pollErrorEnvelope,
          };
        }
      }
    }

    const jobErrorDetails = {
      ...(pollErrorEnvelope?.details || {}),
      ...(finishedJob?.error?.details || {}),
    };
    const candidateBatchId = String(
      finishedJob?.result_ref?.resource_id ||
        acceptedJob?.result_ref?.resource_id ||
        jobErrorDetails.candidate_batch_id ||
        ''
    ).trim();
    let normalizedCandidateBatchId = candidateBatchId;
    let normalizedStatus = String(finishedJob?.status || acceptedJob?.status || '').toLowerCase();
    let normalizedError = finishedJob?.error || pollErrorEnvelope || null;

    // job 超时/运行中时，回收 sources 的最新批次与状态，避免上下文“未知”。
    const normalizedErrorCode = String(normalizedError?.error_code || '').toLowerCase();
    if (
      !normalizedCandidateBatchId ||
      normalizedStatus === 'running' ||
      normalizedStatus === 'pending' ||
      normalizedStatus === 'queued' ||
      normalizedStatus === 'processing' ||
      normalizedErrorCode === 'research.job_timeout'
    ) {
      try {
        const sourcesResp = await listSources(workspaceId);
        const latest = (Array.isArray(sourcesResp?.items) ? sourcesResp.items : []).find(
          (item: any) => String(item?.source_id) === sourceId
        );
        if (latest) {
          normalizedCandidateBatchId = String(latest?.last_candidate_batch_id || normalizedCandidateBatchId || '').trim();
          normalizedStatus = normalizeSourceDerivedStatus(latest) || normalizedStatus;
          if (latest?.last_extract_error) normalizedError = latest.last_extract_error;
        }
      } catch {
        // 保持主流程，不因为状态回收失败而中断。
      }
    }

    let extractionResult: any = null;
    if (normalizedCandidateBatchId) {
      try {
        extractionResult = await getExtractionResult(sourceId, normalizedCandidateBatchId, workspaceId);
      } catch {
        extractionResult = null;
      }
    }

    const candidateIds = Array.isArray(extractionResult?.candidate_ids)
      ? extractionResult.candidate_ids.map((item: unknown) => String(item))
      : undefined;
    const finalStatus = String(extractionResult?.status || normalizedStatus || '').toLowerCase();
    const extractionError = extractionResult?.error || normalizedError || null;
    const degradedReason = extractionResult?.degraded_reason || extractionError?.error_code || null;
    const degraded = Boolean(extractionResult?.degraded || degradedReason);

    onExtractionCompleted?.({
      sourceId,
      jobId: acceptedJob?.job_id || finishedJob?.job_id || null,
      candidateBatchId: normalizedCandidateBatchId || null,
      status: finalStatus || null,
      backendStatus: String(finishedJob?.status || finalStatus || '').toLowerCase() || null,
      jobCreatedAt: finishedJob?.created_at || acceptedJob?.created_at || null,
      jobStartedAt: finishedJob?.started_at || acceptedJob?.started_at || null,
      jobFinishedAt: finishedJob?.finished_at || acceptedJob?.finished_at || null,
      lastSyncedAt: new Date().toISOString(),
      candidateIds,
      error: extractionError,
      degraded,
      degradedReason,
      partialFailureCount: Number(extractionResult?.partial_failure_count || 0),
    });

    return { candidateIds, extractionError, finalStatus };
  };

  const finalizeExtractionFlow = (result: { candidateIds: string[]; extractionError: any; finalStatus: string }, doneMessage: string) => {
    if (isFailedStatus(result.finalStatus)) {
      showToast(`抽取失败：${result.extractionError?.message || '请检查来源内容后重试'}`);
      return false;
    }
    if (!isSucceededStatus(result.finalStatus)) {
      showToast('抽取任务仍在处理中，已进入候选页自动刷新状态');
      goto('confirm');
      return false;
    }
    const candidateCount = (result.candidateIds || []).length;
    if (candidateCount <= 1) {
      showToast(candidateCount === 0 ? '抽取完成：未产出候选' : '抽取完成：候选较少，建议复核并可重试抽取');
    } else {
      showToast(doneMessage);
    }
    goto('confirm');
    return true;
  };

  const runImportAndExtract = async (payload: Record<string, unknown>) => {
    showToast('正在导入并抽取节点...');
    const source = await importSource(payload as any);
    const sourceId = source?.source_id;
    if (!sourceId) {
      throw new Error('导入响应缺少来源编号');
    }
    let result = await runExtractionForSource(String(sourceId));
    if (isSucceededStatus(result.finalStatus) && (result.candidateIds || []).length <= 1) {
      showToast('候选较少，自动补抽一轮...');
      const retryResult = await runExtractionForSource(String(sourceId));
      if ((retryResult.candidateIds || []).length >= (result.candidateIds || []).length) {
        result = retryResult;
      }
    }
    await onImportCompleted?.();
    finalizeExtractionFlow(result, '抽取已完成');
  };

  const handleImport = async () => {
    if (isExtracting) return;
    setIsExtracting(true);
    try {
      const title = titleRef.current?.value?.trim() || '';
      const content = contentRef.current?.value?.trim();
      // If user did not provide new manual content, reuse latest imported source instead of creating a fake one.
      if (!title && !content) {
        const fallbackSource = visibleSources[0];
        const fallbackSourceId = String(fallbackSource?.source_id || '').trim();
        if (!fallbackSourceId) {
          showToast('请先输入文本，或上传/选择一个来源后再抽取');
          return;
        }
        showToast('正在对已导入来源重新抽取...');
        const result = await runExtractionForSource(fallbackSourceId);
        await onImportCompleted?.();
        finalizeExtractionFlow(result, '抽取已完成');
        return;
      }
      await runImportAndExtract({
        workspace_id: workspaceId,
        source_type: selectedSourceType,
        source_input_mode: 'manual_text',
        title: title || '导入来源',
        content: content || title,
      });
    } catch (error) {
      showToast(getErrorMessage(error));
    } finally {
      setIsExtracting(false);
    }
  };

  const handleUrlImport = async () => {
    if (isExtracting) return;
    setIsExtracting(true);
    try {
      const sourceUrl = urlInput.trim();
      if (!sourceUrl) {
        showToast('请输入链接');
        return;
      }
      const title = titleRef.current?.value?.trim() || sourceUrl;
      await runImportAndExtract({
        workspace_id: workspaceId,
        source_type: selectedSourceType,
        source_input_mode: 'url',
        title,
        source_url: sourceUrl,
        source_input: sourceUrl,
      });
      setUrlInput('');
    } catch (error) {
      showToast(getErrorMessage(error));
    } finally {
      setIsExtracting(false);
    }
  };

  const handleSelectLocalFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    if (isExtracting) return;
    setIsExtracting(true);
    try {
      const file = event.target.files?.[0];
      if (!file) return;
      const title = titleRef.current?.value?.trim() || file.name;
      const fileContentBase64 = await fileToBase64(file);
      await runImportAndExtract({
        workspace_id: workspaceId,
        source_type: selectedSourceType,
        source_input_mode: 'local_file',
        title,
        local_file: {
          file_name: file.name,
          file_content_base64: fileContentBase64,
          mime_type: file.type || 'application/octet-stream',
        },
        metadata: {
          uploaded_from: 'web_ui',
          file_size: file.size,
        },
      });
    } catch (error) {
      showToast(getErrorMessage(error));
    } finally {
      setIsExtracting(false);
      if (event.target) {
        event.target.value = '';
      }
    }
  };

  const handleRetryExtract = async (src: any, event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    const sourceId = String(src?.source_id || '').trim();
    if (!sourceId || isExtracting) return;
    try {
      setIsExtracting(true);
      setRetryingSourceId(sourceId);
      showToast('正在重试抽取...');
      const result = await runExtractionForSource(sourceId);
      await onImportCompleted?.();
      finalizeExtractionFlow(result, '重试抽取已完成');
    } catch (error) {
      showToast(getErrorMessage(error));
    } finally {
      setIsExtracting(false);
      setRetryingSourceId(null);
    }
  };

  const handleOpenCandidates = (src: any, event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    const sourceId = String(src?.source_id || '').trim();
    if (!sourceId) return;
    const derivedStatus = normalizeSourceDerivedStatus(src);
    onExtractionCompleted?.({
      sourceId,
      jobId: src?.last_extract_job_id || null,
      candidateBatchId: src?.last_candidate_batch_id || null,
      status: derivedStatus || null,
      candidateIds: undefined,
      error: src?.last_extract_error || null,
      degraded: Boolean(src?.last_extract_error?.degraded || src?.last_extract_error?.error_code),
      degradedReason: src?.last_extract_error?.error_code || null,
      partialFailureCount: 0,
    });
    goto('confirm');
  };

  const handleCopyIds = async (src: any, event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    const details = sourceErrorDetails(src);
    const lines = [
      `source_id=${src?.source_id || ''}`,
      `job_id=${src?.last_extract_job_id || details.job_id || ''}`,
      `candidate_batch_id=${src?.last_candidate_batch_id || details.candidate_batch_id || ''}`,
    ].filter((line) => !line.endsWith('='));
    try {
      await navigator.clipboard.writeText(lines.join('\n'));
      showToast('已复制诊断ID');
    } catch {
      showToast(lines.join(' | '));
    }
  };

  return (
    <div className="import-layout">
      <div className="import-body">
        <div className="import-tabs">
          <div className={`itab ${selectedSourceType === 'paper' ? 'on' : ''}`} onClick={() => setSelectedSourceType('paper')}>学术文献</div>
          <div className={`itab ${selectedSourceType === 'note' ? 'on' : ''}`} onClick={() => setSelectedSourceType('note')}>个人笔记</div>
          <div className={`itab ${selectedSourceType === 'feedback' ? 'on' : ''}`} onClick={() => setSelectedSourceType('feedback')}>导师反馈</div>
          <div className={`itab ${selectedSourceType === 'failure_record' ? 'on' : ''}`} onClick={() => setSelectedSourceType('failure_record')}>失败记录</div>
        </div>

        <div className="source-list">
          <div style={{ fontSize: '11px', fontFamily: 'var(--mono)', letterSpacing: '.08em', color: 'var(--text3)', textTransform: 'uppercase', marginBottom: '8px' }}>已导入材料</div>
          {visibleSources.map((src: any) => {
            const statusMeta = sourceStatusMeta(src);
            const iconClass = src.source_type === 'paper' ? 'src-paper' : src.source_type === 'note' ? 'src-note' : 'src-fail';
            const isExpanded = expandedSourceId === src.source_id;
            const details = sourceErrorDetails(src);
            const errorMessage = src.last_extract_error?.message || '';
            const retrying = retryingSourceId === src.source_id;
            const metadataCheck = inspectSourceMetadataConsistency(src);
            return (
              <div
                className={`src-item ${isExpanded ? 'open' : ''}`}
                key={src.source_id}
                onClick={() => setExpandedSourceId(isExpanded ? null : src.source_id)}
              >
                <div className={`src-icon ${iconClass}`}>{typeLabel(src.source_type).slice(0, 1)}</div>
                <div className="src-info">
                  <div className="src-name">{src.title || src.source_id}</div>
                  <div className="src-meta">{typeLabel(src.source_type)} · {formatDate(src.updated_at || src.created_at) || '未知时间'}</div>
                </div>
                <span className={`src-badge ${statusMeta.className}`}>{statusMeta.label}</span>
                {isExpanded && (
                  <div className="src-detail">
                    <div className="src-detail-row">source_id: {src.source_id}</div>
                    <div className="src-detail-row">job_id: {src.last_extract_job_id || details.job_id || '无'}</div>
                    <div className="src-detail-row">candidate_batch_id: {src.last_candidate_batch_id || details.candidate_batch_id || '无'}</div>
                    <div className="src-detail-row">error: {errorMessage || '无'}</div>
                    <div className="src-detail-row">
                      metadata.publication_year: {metadataCheck.publicationYear ?? '无'}
                      {metadataCheck.yearMismatch ? ` · 建议修正为 ${metadataCheck.suggestedYear}` : ''}
                    </div>
                    {metadataCheck.pollutedKeywords.length > 0 && (
                      <div className="src-detail-row" style={{ color: 'var(--red)' }}>
                        topic_clusters 疑似路径污染: {metadataCheck.pollutedKeywords.slice(0, 5).join(', ')}
                      </div>
                    )}
                    {metadataCheck.missingCore.length > 0 && (
                      <div className="src-detail-row" style={{ color: 'var(--yellow)' }}>
                        topic_clusters 缺少核心主题: {metadataCheck.missingCore.slice(0, 5).join(', ')}
                      </div>
                    )}
                    {metadataCheck.suggestedTopics.length > 0 && (
                      <div className="src-detail-row">
                        建议主题: {metadataCheck.suggestedTopics.join(' · ')}
                      </div>
                    )}
                    <div className="src-actions">
                      <button className="src-action" onClick={(event) => handleRetryExtract(src, event)} disabled={retrying || isExtracting}>
                        {retrying ? '重试中...' : '重试抽取'}
                      </button>
                      <button className="src-action" onClick={(event) => handleOpenCandidates(src, event)}>查看候选</button>
                      <button className="src-action" onClick={(event) => handleCopyIds(src, event)}>复制ID</button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {visibleSources.length === 0 && (
            <div className="src-item">
              <div className="src-icon src-note">i</div>
              <div className="src-info">
                <div className="src-name">暂无已导入材料</div>
                <div className="src-meta">先通过下方文本、链接或文件导入来源</div>
              </div>
            </div>
          )}
        </div>

        <div className="divider"></div>

        <div className="upload-zone" onClick={() => { if (!isExtracting) fileInputRef.current?.click(); }}>
          <div className="upload-icon">+</div>
          <div className="upload-title">点击上传文献</div>
          <div className="upload-sub">支持 PDF、DOCX · 单文件最大 20MB · 仅支持点击上传</div>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          style={{ display: 'none' }}
          onChange={handleSelectLocalFile}
        />

        <div className="or-div"><div className="or-line"></div><span>或粘贴内容</span><div className="or-line"></div></div>

        <div className="form-row">
          <label className="form-label">文献标题 / 来源</label>
          <input className="form-input" placeholder="例如：研究标题或来源" id="src-title" ref={titleRef} />
        </div>
        <div className="form-row">
          <label className="form-label">内容（摘要或全文）</label>
          <textarea className="paste-area" placeholder="粘贴文献摘要、笔记内容或反馈记录..." id="src-content" ref={contentRef}></textarea>
        </div>

        <div className="or-div"><div className="or-line"></div><span>或导入外部链接</span><div className="or-line"></div></div>

        <div className="form-row" style={{ display: 'flex', gap: '8px' }}>
          <input
            className="form-input"
            style={{ flex: 1 }}
            placeholder="输入外部链接（例如：https://example.com/paper）"
            id="src-url"
            value={urlInput}
            onChange={(event) => setUrlInput(event.target.value)}
          />
          <button className="btn" onClick={handleUrlImport} disabled={isExtracting || !urlInput.trim()} title={!urlInput.trim() ? '请先输入外部链接。' : undefined}>抓取内容</button>
        </div>

        <button className="extract-btn" onClick={handleImport} disabled={isExtracting}>{isExtracting ? '抽取中...' : '开始抽取节点'}</button>
      </div>
    </div>
  );
}

export function ConfirmPage({ candidates, extractionContext, fetchData, goto, showToast, workspaceId }: any) {
  const [pollWaitSeconds, setPollWaitSeconds] = useState(0);
  const [pollRefreshCount, setPollRefreshCount] = useState(0);
  const [lastPollAt, setLastPollAt] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [confirmAllDialog, setConfirmAllDialog] = useState<{ count: number } | null>(null);
  const fetchDataRef = useRef(fetchData);

  useEffect(() => {
    fetchDataRef.current = fetchData;
  }, [fetchData]);
  const scopedCandidates = useMemo(() => {
    const items = Array.isArray(candidates) ? candidates : [];
    if (!extractionContext) return items;
    const sourceScopedItems = extractionContext.sourceId
      ? items.filter((candidate: any) => String(candidate.source_id) === String(extractionContext.sourceId))
      : [];

    if (extractionContext.candidateBatchId) {
      const batchMatched = items.filter(
        (candidate: any) =>
          String(candidate.candidate_batch_id || '') === String(extractionContext.candidateBatchId || '')
      );
      if (batchMatched.length > 0) return batchMatched;
      if (sourceScopedItems.length > 0) return sourceScopedItems;
    }

    if (Array.isArray(extractionContext.candidateIds) && extractionContext.candidateIds.length > 0) {
      const idSet = new Set(extractionContext.candidateIds.map((item: unknown) => String(item)));
      return items.filter((candidate: any) => idSet.has(String(candidate.candidate_id)));
    }

    if (extractionContext.sourceId) {
      return items.filter((candidate: any) => String(candidate.source_id) === String(extractionContext.sourceId));
    }

    return items;
  }, [candidates, extractionContext]);

  const extractionStatus = String(extractionContext?.status || '').toLowerCase();
  const extractionErrorCode = String(extractionContext?.error?.error_code || '').toLowerCase();
  const timeoutLike = extractionErrorCode === 'research.job_timeout';
  const terminalFailed = (
    extractionStatus === 'failed' ||
    extractionStatus === 'cancelled' ||
    extractionStatus === 'canceled'
  ) && !timeoutLike;
  const terminalSucceeded = extractionStatus === 'succeeded' || extractionStatus === 'completed';
  const shouldPoll = Boolean(extractionContext?.sourceId) && !terminalFailed && !terminalSucceeded;
  const showCompletedEmptyState =
    !shouldPoll && terminalSucceeded;

  useEffect(() => {
    if (!shouldPoll) {
      setPollWaitSeconds(0);
      setPollRefreshCount(0);
      setLastPollAt(null);
      return;
    }

    const pollOnce = () => {
      setPollRefreshCount((value) => value + 1);
      setLastPollAt(Date.now());
      fetchDataRef.current?.().catch(() => undefined);
    };

    pollOnce();
    const waitTimer = window.setInterval(() => {
      setPollWaitSeconds((value) => value + 1);
    }, 1000);
    const pollTimer = window.setInterval(pollOnce, 2500);

    return () => {
      window.clearInterval(waitTimer);
      window.clearInterval(pollTimer);
    };
  }, [shouldPoll]);

  const pollWaitLabel = `${Math.floor(pollWaitSeconds / 60)}分${String(pollWaitSeconds % 60).padStart(2, '0')}秒`;
  const pollLastAtLabel = lastPollAt ? new Date(lastPollAt).toLocaleTimeString('zh-CN') : '--:--:--';
  const jobStartRaw = extractionContext?.jobStartedAt || extractionContext?.jobCreatedAt;
  const jobStartTs = jobStartRaw ? new Date(jobStartRaw).getTime() : NaN;
  const jobEndRaw = extractionContext?.jobFinishedAt || null;
  const jobEndTs = jobEndRaw ? new Date(jobEndRaw).getTime() : NaN;
  const runtimeSeconds =
    Number.isFinite(jobStartTs)
      ? Math.max(0, Math.floor(((Number.isFinite(jobEndTs) ? jobEndTs : Date.now()) - jobStartTs) / 1000))
      : null;
  const runtimeLabel = formatDurationLabel(runtimeSeconds);
  const backendStatus = String(extractionContext?.backendStatus || extractionContext?.status || '').toLowerCase();
  const extractionUiState = getAsyncJobUiState(extractionContext?.status, extractionContext?.error?.error_code);
  const extractionStatusTone =
    extractionUiState === 'failed'
      ? 'var(--red)'
      : extractionUiState === 'succeeded'
      ? 'var(--green)'
      : 'var(--amber)';
  const extractionStatusHint =
    extractionUiState === 'running'
      ? '系统正在等待后端完成抽取，会自动刷新候选结果。'
      : extractionUiState === 'timeout'
      ? '前端轮询已超时，但任务可能仍在后台继续，请保留当前页面或稍后刷新。'
      : extractionUiState === 'failed'
      ? '本次抽取已失败，请检查来源内容或返回导入页重试。'
      : extractionUiState === 'succeeded'
      ? '抽取已完成，可以继续确认候选并入图。'
      : '等待任务状态同步。';

  const pending = useMemo(() => scopedCandidates.filter((c: any) => c.status === 'pending'), [scopedCandidates]);
  const pendingIds = useMemo(() => pending.map((item: any) => String(item.candidate_id)), [pending]);
  const selectedPendingIds = useMemo(
    () => selectedIds.filter((id) => pendingIds.includes(String(id))),
    [selectedIds, pendingIds]
  );

  useEffect(() => {
    setSelectedIds((prev) => {
      const next = prev.filter((id) => pendingIds.includes(String(id)));
      if (next.length === prev.length && next.every((id, index) => id === prev[index])) {
        return prev;
      }
      return next;
    });
  }, [pendingIds]);
  const parseSummary = useMemo(() => {
    const byType = scopedCandidates.reduce((acc: Record<string, number>, item: any) => {
      const key = String(item?.candidate_type || '').toLowerCase() || 'other';
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});
    const confirmedCount = scopedCandidates.filter((item: any) => item?.status === 'confirmed').length;
    const rejectedCount = scopedCandidates.filter((item: any) => item?.status === 'rejected').length;
    const pendingCount = scopedCandidates.filter((item: any) => item?.status === 'pending').length;
    return {
      total: scopedCandidates.length,
      pending: pendingCount,
      confirmed: confirmedCount,
      rejected: rejectedCount,
      evidence: byType.evidence || 0,
      assumption: byType.assumption || 0,
      failure: byType.failure || 0,
      other: Object.entries(byType)
        .filter(([key]) => !['evidence', 'assumption', 'failure'].includes(key))
        .reduce((sum, [, value]) => sum + Number(value || 0), 0),
    };
  }, [scopedCandidates]);

  const isDuplicateConfirmedConflict = (error: any) => {
    const status = Number(error?.status || 0);
    const errorCode = String(error?.envelope?.error_code || error?.error_code || '').toLowerCase();
    const reason = String(error?.envelope?.details?.reason || error?.details?.reason || '').toLowerCase();
    return status === 409 && errorCode === 'research.conflict' && reason === 'duplicate_confirmed_object';
  };

  const isConfirmInvalidState = (error: any) => {
    const status = Number(error?.status || 0);
    const errorCode = String(error?.envelope?.error_code || error?.error_code || '').toLowerCase();
    return status === 409 && errorCode === 'research.invalid_state';
  };

  const confirmCandidatesWithConflictTolerance = async (candidateIds: string[]) => {
    if (!Array.isArray(candidateIds) || candidateIds.length === 0) {
      return { confirmedIds: [] as string[], skippedConflictIds: [] as string[], alreadyHandledIds: [] as string[] };
    }
    try {
      await confirmCandidates(workspaceId, candidateIds);
      return { confirmedIds: candidateIds, skippedConflictIds: [] as string[], alreadyHandledIds: [] as string[] };
    } catch (error) {
      if (!isDuplicateConfirmedConflict(error) && !isConfirmInvalidState(error)) throw error;
    }

    const confirmedIds: string[] = [];
    const skippedConflictIds: string[] = [];
    const alreadyHandledIds: string[] = [];
    for (const candidateId of candidateIds) {
      try {
        await confirmCandidates(workspaceId, [candidateId]);
        confirmedIds.push(candidateId);
      } catch (error) {
        if (isDuplicateConfirmedConflict(error)) {
          skippedConflictIds.push(candidateId);
          try {
            await rejectCandidates(workspaceId, [candidateId], '重复确认自动跳过');
          } catch {
            // 自动跳过失败时不影响同批其他候选继续处理。
          }
          continue;
        }
        if (isConfirmInvalidState(error)) {
          alreadyHandledIds.push(candidateId);
          continue;
        }
        throw error;
      }
    }
    return { confirmedIds, skippedConflictIds, alreadyHandledIds };
  };

  const handleAction = async (id: string, action: string) => {
    try {
      const targetCandidate = scopedCandidates.find((item: any) => String(item.candidate_id) === String(id));
      if (action === 'acc') {
        const { confirmedIds, skippedConflictIds, alreadyHandledIds } = await confirmCandidatesWithConflictTolerance([id]);
        if (targetCandidate && confirmedIds.length > 0) {
          await hydrateConfirmedCandidatesToGraph(workspaceId, [{ ...targetCandidate, status: 'confirmed' }]);
        }
        await fetchData();
        if (skippedConflictIds.length > 0) {
          showToast('候选与已确认对象重复，已自动跳过并标记为拒绝');
          return;
        }
        if (alreadyHandledIds.length > 0) {
          showToast('候选状态已变化，已自动刷新最新状态');
          return;
        }
      } else {
        await rejectCandidates(workspaceId, [id], '用户拒绝');
        await fetchData();
      }
      showToast(action === 'acc' ? '节点已确认入图' : '节点已拒绝');
    } catch (error) {
      showToast(getErrorMessage(error));
    }
  };

  const handleAll = async (action: string) => {
    try {
      const pendingIds = pending.map((c: any) => c.candidate_id);
      if (pendingIds.length === 0) {
        showToast('当前没有待确认候选');
        return;
      }

      if (action === 'acc') {
        setConfirmAllDialog({ count: pendingIds.length });
      } else {
        await rejectCandidates(workspaceId, pendingIds, '用户全部拒绝');
        await fetchData();
        showToast('全部节点已拒绝');
      }
    } catch (error) {
      showToast(getErrorMessage(error));
    }
  };

  const confirmAllPending = async () => {
    const pendingIds = pending.map((c: any) => c.candidate_id);
    if (pendingIds.length === 0) {
      setConfirmAllDialog(null);
      showToast('当前没有待确认候选');
      return;
    }

    try {
      const { confirmedIds, skippedConflictIds, alreadyHandledIds } = await confirmCandidatesWithConflictTolerance(pendingIds);
      if (confirmedIds.length > 0) {
        const confirmedPendingCandidates = pending
          .filter((item: any) => confirmedIds.includes(String(item.candidate_id)))
          .map((item: any) => ({ ...item, status: 'confirmed' }));
        await hydrateConfirmedCandidatesToGraph(workspaceId, confirmedPendingCandidates);
      }
      await fetchData();
      setConfirmAllDialog(null);
      if (skippedConflictIds.length > 0) {
        showToast(`已确认 ${confirmedIds.length} 条，已处理 ${alreadyHandledIds.length} 条，跳过重复 ${skippedConflictIds.length} 条`);
      } else if (alreadyHandledIds.length > 0) {
        showToast(`已确认 ${confirmedIds.length} 条，已处理 ${alreadyHandledIds.length} 条`);
      } else {
        showToast('全部节点已确认入图');
      }
      if (confirmedIds.length > 0) goto('workbench');
    } catch (error) {
      showToast(getErrorMessage(error));
    }
  };

  const toggleCandidateSelection = (candidateId: string) => {
    setSelectedIds((prev) => {
      if (prev.includes(candidateId)) return prev.filter((id) => id !== candidateId);
      return [...prev, candidateId];
    });
  };

  const clearCandidateSelection = () => {
    setSelectedIds([]);
  };

  const handleSelected = async (action: string) => {
    try {
      if (selectedPendingIds.length === 0) {
        showToast('请先选择待确认候选');
        return;
      }
      if (action === 'acc') {
        const { confirmedIds, skippedConflictIds, alreadyHandledIds } = await confirmCandidatesWithConflictTolerance(selectedPendingIds);
        if (confirmedIds.length > 0) {
          const selectedPendingCandidates = pending
            .filter((item: any) => confirmedIds.includes(String(item.candidate_id)))
            .map((item: any) => ({ ...item, status: 'confirmed' }));
          await hydrateConfirmedCandidatesToGraph(workspaceId, selectedPendingCandidates);
        }
        await fetchData();
        setSelectedIds([]);
        if (skippedConflictIds.length > 0) {
          showToast(`已确认 ${confirmedIds.length} 条选中候选，已处理 ${alreadyHandledIds.length} 条，跳过重复 ${skippedConflictIds.length} 条`);
        } else if (alreadyHandledIds.length > 0) {
          showToast(`已确认 ${confirmedIds.length} 条选中候选，已处理 ${alreadyHandledIds.length} 条`);
        } else {
          showToast(`已确认 ${confirmedIds.length} 条选中候选`);
        }
      } else {
        await rejectCandidates(workspaceId, selectedPendingIds, '用户批量拒绝选中候选');
        setSelectedIds([]);
        await fetchData();
        showToast(`已拒绝 ${selectedPendingIds.length} 条选中候选`);
      }
    } catch (error) {
      showToast(getErrorMessage(error));
    }
  };

  const confirmAllDialogCopy = confirmAllDialog ? getCandidateBulkConfirmDialogCopy(confirmAllDialog.count) : null;

  return (
    <div className="confirm-layout">
      <div className="confirm-bar">
        <button className="btn" onClick={() => goto('import')}>返回导入</button>
        <span className="batch-title">本批次抽取结果</span>
        <span className="batch-count" id="cand-count">{pending.length} 条待确认 / {scopedCandidates.length} 条总计</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '6px' }}>
          <button className="btn" onClick={clearCandidateSelection} disabled={selectedPendingIds.length === 0} title={selectedPendingIds.length === 0 ? '当前没有已选中的待确认候选' : undefined}>清空选择</button>
          <button className="btn" onClick={() => handleSelected('rej')} disabled={selectedPendingIds.length === 0} title={selectedPendingIds.length === 0 ? '请先勾选至少 1 条待确认候选' : undefined}>仅拒绝选中</button>
          <button className="btn" onClick={() => handleSelected('acc')} disabled={selectedPendingIds.length === 0} title={selectedPendingIds.length === 0 ? '请先勾选至少 1 条待确认候选' : undefined}>仅确认选中</button>
          <button className="btn" onClick={() => handleAll('rej')} disabled={pending.length === 0} title={pending.length === 0 ? '当前没有待确认候选可批量拒绝' : undefined}>全部拒绝</button>
          <button className="btn btn-p" onClick={() => handleAll('acc')} disabled={pending.length === 0} title={pending.length === 0 ? '当前没有待确认候选可全部确认' : undefined}>全部确认</button>
        </div>
      </div>
      {confirmAllDialogCopy ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="candidate-bulk-confirm-title"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15, 23, 42, 0.42)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
            zIndex: 1000,
          }}
        >
          <div
            style={{
              width: 'min(440px, 100%)',
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: '12px',
              boxShadow: '0 24px 48px rgba(15, 23, 42, 0.18)',
              padding: '20px',
            }}
          >
            <div id="candidate-bulk-confirm-title" style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text)' }}>
              {confirmAllDialogCopy.title}
            </div>
            <div style={{ marginTop: '8px', fontSize: '13px', lineHeight: 1.7, color: 'var(--text2)' }}>
              {confirmAllDialogCopy.body}
            </div>
            <div style={{ marginTop: '18px', display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button className="btn" onClick={() => setConfirmAllDialog(null)}>
                {confirmAllDialogCopy.cancelLabel}
              </button>
              <button className="btn btn-p" onClick={confirmAllPending}>
                {confirmAllDialogCopy.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      <div className="confirm-body" id="cand-list">
        {extractionContext && (
          <div className="cand-card" style={{ borderStyle: 'dashed' }}>
            <div className="cand-hdr">
              <div className="cand-main">
                <div className="cand-type">本次抽取上下文</div>
                <div className="cand-label">
                  source_id={extractionContext.sourceId || '未知'} · candidate_batch_id=
                  {extractionContext.candidateBatchId || '未知'}
                </div>
                <div className="cand-desc">
                  任务：job_id={extractionContext.jobId || '未知'} · 后端状态={backendStatus || '未知'}
                </div>
                <div className="cand-desc">
                  受理 {formatDateTime(extractionContext.jobCreatedAt)} · 开始 {formatDateTime(extractionContext.jobStartedAt)} · 完成 {formatDateTime(extractionContext.jobFinishedAt)}
                </div>
                <div className="cand-desc">
                  {extractionContext.jobFinishedAt ? '后端总耗时' : '后端已运行'} {runtimeLabel} · 最近同步 {formatDateTime(extractionContext.lastSyncedAt)}
                </div>
                <div
                  className="cand-desc"
                  style={{
                    marginTop: '10px',
                    padding: '10px 12px',
                    borderRadius: '8px',
                    background: 'var(--bg2)',
                    border: `1px solid ${extractionStatusTone}`,
                    color: 'var(--text)',
                  }}
                >
                  <div style={{ fontSize: '12px', color: extractionStatusTone }}>
                    抽取状态：{normalizeExtractionStatus(extractionContext.status, extractionContext.error?.error_code)}
                  </div>
                  <div style={{ marginTop: '4px' }}>{extractionStatusHint}</div>
                </div>
                {extractionContext.degraded && (
                  <div
                    className="cand-desc"
                    style={{
                      marginTop: '8px',
                      padding: '10px 12px',
                      borderRadius: '8px',
                      background: 'var(--amber-bg)',
                      border: '1px solid var(--amber)',
                      color: 'var(--text)',
                    }}
                  >
                    降级提示：{normalizeDegradedReason(extractionContext.degradedReason)}
                  </div>
                )}
                {Number(extractionContext.partialFailureCount || 0) > 0 && (
                  <div className="cand-desc" style={{ marginTop: '8px' }}>
                    本次抽取有 {extractionContext.partialFailureCount} 个分支失败，但系统已保留当前可用候选，请重点复核。
                  </div>
                )}
                {extractionContext.error?.message && (
                  <div className="cand-desc" style={{ color: 'var(--red)' }}>
                    {extractionContext.error.error_code || 'research.extraction_error'}: {extractionContext.error.message}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
        <div className="cand-card" style={{ borderStyle: 'dashed' }}>
          <div className="cand-hdr">
            <div className="cand-main">
              <div className="cand-type">独立解析摘要</div>
              <div className="cand-label">
                总计 {parseSummary.total} · 待确认 {parseSummary.pending} · 已确认 {parseSummary.confirmed} · 已拒绝 {parseSummary.rejected}
              </div>
              <div className="cand-desc">
                类型分布：证据 {parseSummary.evidence} · 前提 {parseSummary.assumption} · 失败 {parseSummary.failure}
                {parseSummary.other > 0 ? ` · 其他 ${parseSummary.other}` : ''}
              </div>
            </div>
          </div>
        </div>

        {scopedCandidates.length === 0 && (
          <div className="cand-card">
            <div className="cand-hdr">
              <div className="cand-main">
                <div className="cand-type">{showCompletedEmptyState ? '当前批次未产出候选' : '候选尚未就绪'}</div>
                <div className="cand-label">
                  {showCompletedEmptyState
                    ? `请检查文档内容可解析性（batch=${extractionContext?.candidateBatchId || '未知'}），或返回导入页重试抽取。`
                    : extractionUiState === 'timeout'
                    ? '前端轮询已超时，系统可能仍在后台同步候选结果；请稍后刷新或保留当前页面继续等待。'
                    : '系统正在同步抽取结果，请稍候自动刷新；如长时间无结果可返回导入页重试。'}
                </div>
                {shouldPoll && (
                  <div className="cand-desc" style={{ marginTop: '8px' }}>
                    已等待 {pollWaitLabel} · 自动刷新 {pollRefreshCount} 次 · 最近刷新 {pollLastAtLabel}
                  </div>
                )}
                {shouldPoll && (
                  <div style={{ marginTop: '10px' }}>
                    <button
                      className="btn"
                      onClick={() => {
                        setPollRefreshCount((value) => value + 1);
                        setLastPollAt(Date.now());
                        fetchDataRef.current?.().catch(() => undefined);
                      }}
                    >
                      立即刷新
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {scopedCandidates.map((c: any) => {
          const normalizedType = String(c.candidate_type || '').toLowerCase();
          const color = normalizedType === 'evidence' ? '#3B6D11' : normalizedType === 'assumption' ? '#BA7517' : normalizedType === 'failure' ? '#A32D2D' : '#888780';
          const typeLbl = candidateTypeLabel(normalizedType);
          const semanticLbl = semanticTypeLabel(String(c.semantic_type || ''));
          const typeText = semanticLbl ? `${typeLbl} · ${semanticLbl}` : typeLbl;

          return (
            <div key={c.candidate_id} className={`cand-card ${c.status === 'confirmed' ? 'acc' : c.status === 'rejected' ? 'rej' : ''}`} id={`cc-${c.candidate_id}`}>
              <div className="cand-hdr">
                <div className="cand-type-dot" style={{ background: color }}></div>
                <div className="cand-main">
                  <div className="cand-type">{typeText}</div>
                  <div className="cand-label">{c.text}</div>
                  <div className="cand-desc">{c.source_span?.desc}</div>
                </div>
              </div>
              <div className="cand-foot">
                <div className="mount-box">
                  <div className="mount-label">建议挂载位置</div>
                  <div className="mount-val">{normalizeSourceMountLabel(c.source_span)}</div>
                </div>
                <div className="cand-actions">
                  {c.status === 'confirmed' ? <span style={{ fontSize: '11px', color: 'var(--green)', fontFamily: 'var(--mono)' }}>已确认</span> :
                   c.status === 'rejected' ? <span style={{ fontSize: '11px', color: 'var(--red)', fontFamily: 'var(--mono)' }}>已拒绝</span> :
                   <>
                     <label style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: 'var(--text2)', marginRight: '6px' }}>
                       <input
                         type="checkbox"
                         checked={selectedIds.includes(String(c.candidate_id))}
                         onChange={() => toggleCandidateSelection(String(c.candidate_id))}
                       />
                       选中
                     </label>
                     <button className="ca-btn ca-rej" onClick={() => handleAction(c.candidate_id, 'rej')}>拒绝</button>
                     <button className="ca-btn ca-acc" onClick={() => handleAction(c.candidate_id, 'acc')}>确认入图</button>
                   </>}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
