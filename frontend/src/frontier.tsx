import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  CandidateRecord,
  SourceRecord,
  controlHypothesisPool,
  finalizeHypothesisPool,
  generateLiteratureFrontierHypothesis,
  getErrorMessage,
  getHypothesisPool,
  getHypothesisPoolTrajectory,
  listHypothesisPoolCandidates,
  listHypothesisPoolRounds,
  listHypothesisPoolTranscripts,
  patchHypothesisCandidate,
  pollJob,
  runHypothesisPoolRound,
} from './api';

const TERMINAL_POOL_STATUSES = new Set([
  'finalized',
  'failed',
  'cancelled',
  'stopped',
]);

const NON_RUNNABLE_POOL_STATUSES = new Set([
  'paused',
  'stopping',
  'stopped',
  'finalizing',
  'finalized',
  'failed',
  'cancelled',
]);

const INTERRUPT_SAFE_STATUSES = new Set([
  'paused',
  'stopping',
  'stopped',
  'finalizing',
  'finalized',
]);

function normalizeText(value: unknown, fallback = '--') {
  const text = String(value ?? '').trim();
  return text || fallback;
}

function toArray(value: unknown): any[] {
  return Array.isArray(value) ? value : [];
}

function reasoningStepTexts(reasoningChain: any): string[] {
  const explicitChain = reasoningChain?.reasoning_chain || {};
  const explicitSteps = [
    ...toArray(explicitChain?.evidence).map((item) => `证据：${normalizeText(item, '')}`),
    normalizeText(explicitChain?.assumption, '').trim()
      ? `前提/假设：${normalizeText(explicitChain?.assumption, '')}`
      : '',
    ...toArray(explicitChain?.intermediate_reasoning).map((item) => `中间推理：${normalizeText(item, '')}`),
    normalizeText(explicitChain?.conclusion, '').trim()
      ? `结论：${normalizeText(explicitChain?.conclusion, '')}`
      : '',
    normalizeText(explicitChain?.validation_need, '').trim()
      ? `所需验证：${normalizeText(explicitChain?.validation_need, '')}`
      : '',
  ].filter(Boolean);
  if (explicitSteps.length > 0) return explicitSteps;
  const steps = toArray(reasoningChain?.reasoning_steps)
    .map((step) => normalizeText(step?.text, '').trim())
    .filter(Boolean);
  if (steps.length > 0) return steps;
  return toArray(reasoningChain?.mechanism_chain)
    .map((step) => normalizeText(step, '').trim())
    .filter(Boolean);
}

function reasoningNodes(reasoningChain: any): any[] {
  const explicitNodes = toArray(reasoningChain?.reasoning_nodes).filter(
    (node) => normalizeText(node?.node_id, '').trim() && normalizeText(node?.node_type, '').trim()
  );
  if (explicitNodes.length > 0) return explicitNodes;
  const explicitChain = reasoningChain?.reasoning_chain || {};
  return [
    ...toArray(explicitChain?.evidence).map((content, index) => ({
      node_id: `evidence:${index + 1}`,
      node_type: 'evidence',
      content,
      source_refs: reasoningChain?.source_refs || [],
    })),
    normalizeText(explicitChain?.assumption, '').trim()
      ? {
          node_id: 'assumption:1',
          node_type: 'assumption',
          content: explicitChain?.assumption,
          source_refs: [],
        }
      : null,
    ...toArray(explicitChain?.intermediate_reasoning).map((content, index) => ({
      node_id: `intermediate_reasoning:${index + 1}`,
      node_type: 'intermediate_reasoning',
      content,
      source_refs: [],
    })),
    normalizeText(explicitChain?.conclusion, '').trim()
      ? {
          node_id: 'conclusion:1',
          node_type: 'conclusion',
          content: explicitChain?.conclusion,
          source_refs: [],
        }
      : null,
    normalizeText(explicitChain?.validation_need, '').trim()
      ? {
          node_id: 'validation_need:1',
          node_type: 'validation_need',
          content: explicitChain?.validation_need,
          source_refs: [],
        }
      : null,
  ].filter(Boolean);
}

function toPercent(value: unknown) {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) return '0%';
  return `${Math.round(Math.max(0, Math.min(1, numeric)) * 100)}%`;
}

function toDateTime(value?: string | null) {
  if (!value) return '--';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return String(value);
  return dt.toLocaleString('zh-CN', { hour12: false });
}

function dedupeSourceIds(sourceIds: string[]) {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const sourceId of sourceIds) {
    const normalized = String(sourceId || '').trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    output.push(normalized);
  }
  return output;
}

function pickFrontierCandidates(candidates: any[], frontierSize: number) {
  const active = candidates
    .filter((item) => ['alive', 'finalized'].includes(String(item?.status || '').toLowerCase()))
    .sort((left, right) => Number(right?.elo_rating || 0) - Number(left?.elo_rating || 0));
  return active.slice(0, Math.max(3, Math.min(5, frontierSize || 3)));
}

function objectOrNull(value: unknown): Record<string, any> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, any>)
    : null;
}

function getSupervisorArtifact(pool: any) {
  const subgraph = objectOrNull(pool?.reasoning_subgraph);
  if (!subgraph) return null;
  const latestRoundSupervisor = objectOrNull(subgraph.latest_round_supervisor);
  const supervisorPlan = objectOrNull(subgraph.supervisor_plan);
  const artifact = latestRoundSupervisor || supervisorPlan;
  if (!artifact) return null;
  return {
    artifact,
    source: latestRoundSupervisor ? 'latest_round_supervisor' : 'supervisor_plan',
    latestDecision: subgraph.latest_supervisor_decision,
  };
}

type FrontierPageProps = {
  workspaceId: string;
  sources: SourceRecord[];
  candidates: CandidateRecord[];
  showToast: (msg: string) => void;
  goto: (page: string) => void;
  onRefresh: () => Promise<void>;
};

export function FrontierPage({
  workspaceId,
  sources,
  candidates,
  showToast,
  goto,
  onRefresh,
}: FrontierPageProps) {
  const [researchGoal, setResearchGoal] = useState('');
  const [frontierSize, setFrontierSize] = useState(3);
  const [maxRounds, setMaxRounds] = useState(2);
  const [allowRetrieval, setAllowRetrieval] = useState(true);
  const [poolId, setPoolId] = useState('');
  const [pool, setPool] = useState<any>(null);
  const [poolCandidates, setPoolCandidates] = useState<any[]>([]);
  const [poolRounds, setPoolRounds] = useState<any[]>([]);
  const [poolTranscripts, setPoolTranscripts] = useState<any[]>([]);
  const [poolTrajectory, setPoolTrajectory] = useState<any>(null);
  const [isCreatingPool, setIsCreatingPool] = useState(false);
  const [isAutoRunning, setIsAutoRunning] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activityLog, setActivityLog] = useState<string[]>([]);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const hasUserTouchedSourcesRef = useRef(false);
  const autoLoopActiveRef = useRef(false);
  const autoLoopRunningRef = useRef(false);
  const currentPoolIdRef = useRef('');
  const [editingCandidateId, setEditingCandidateId] = useState('');
  const [draftConclusion, setDraftConclusion] = useState('');
  const [draftReasoningSteps, setDraftReasoningSteps] = useState('');
  const [draftValidationSteps, setDraftValidationSteps] = useState('');
  const [userHypothesisDraft, setUserHypothesisDraft] = useState('');
  const [previousConclusions, setPreviousConclusions] = useState<Record<string, string>>({});

  const sourceMap = useMemo(() => {
    const map: Record<string, SourceRecord> = {};
    for (const source of sources || []) {
      const sourceId = String(source?.source_id || '').trim();
      if (!sourceId) continue;
      map[sourceId] = source;
    }
    return map;
  }, [sources]);

  const confirmedSourceIds = useMemo(() => {
    const ids = new Set<string>();
    for (const candidate of candidates || []) {
      if (String(candidate?.status || '').toLowerCase() !== 'confirmed') continue;
      const sourceId = String(candidate?.source_id || '').trim();
      if (!sourceId) continue;
      ids.add(sourceId);
    }
    return Array.from(ids);
  }, [candidates]);

  const eligibleSources = useMemo(() => {
    return confirmedSourceIds
      .map((sourceId) => sourceMap[sourceId])
      .filter((item): item is SourceRecord => Boolean(item))
      .sort((left, right) => String(left.title || '').localeCompare(String(right.title || ''), 'zh-Hans-CN'));
  }, [confirmedSourceIds, sourceMap]);

  useEffect(() => {
    if (hasUserTouchedSourcesRef.current) return;
    setSelectedSourceIds((prev) => {
      if (prev.length > 0) return prev;
      return dedupeSourceIds(confirmedSourceIds);
    });
  }, [confirmedSourceIds]);

  const appendLog = (text: string) => {
    const stamp = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    setActivityLog((prev) => [`[${stamp}] ${text}`, ...prev].slice(0, 30));
  };

  const refreshPoolState = async (targetPoolId?: string) => {
    const effectivePoolId = String(targetPoolId || poolId || '').trim();
    if (!effectivePoolId) return null;
    setIsRefreshing(true);
    try {
      const [nextPool, nextCandidates, nextRounds, nextTranscripts, nextTrajectory] = await Promise.all([
        getHypothesisPool(effectivePoolId),
        listHypothesisPoolCandidates(effectivePoolId),
        listHypothesisPoolRounds(effectivePoolId),
        listHypothesisPoolTranscripts(effectivePoolId),
        getHypothesisPoolTrajectory(effectivePoolId),
      ]);
      setPool(nextPool);
      setPoolCandidates(toArray(nextCandidates?.items));
      setPoolRounds(
        toArray(nextRounds?.items).sort(
          (left, right) => Number(right?.round_number || 0) - Number(left?.round_number || 0)
        )
      );
      setPoolTranscripts(toArray(nextTranscripts?.items).slice().reverse());
      setPoolTrajectory(nextTrajectory);
      return nextPool;
    } finally {
      setIsRefreshing(false);
    }
  };

  const runAutonomousLoop = async (targetPoolId: string) => {
    if (!targetPoolId || autoLoopRunningRef.current) return;
    autoLoopRunningRef.current = true;
    setIsAutoRunning(true);
    try {
      while (autoLoopActiveRef.current && currentPoolIdRef.current === targetPoolId) {
        const latestPool = await refreshPoolState(targetPoolId);
        if (!latestPool) break;
        const status = String(latestPool?.status || '').toLowerCase();
        const currentRound = Number(latestPool?.current_round_number || 0);
        const maxRoundLimit = Number(latestPool?.max_rounds || maxRounds || 2);

        if (TERMINAL_POOL_STATUSES.has(status)) {
          appendLog(`自治停止：池状态=${status}`);
          break;
        }

        if (status === 'paused') {
          appendLog('自治暂停：池状态为 paused');
          break;
        }

        if (!NON_RUNNABLE_POOL_STATUSES.has(status) && currentRound < maxRoundLimit) {
          appendLog(`执行轮次 ${currentRound + 1}/${maxRoundLimit}`);
          const accepted = await runHypothesisPoolRound(targetPoolId, {
            workspace_id: workspaceId,
            async_mode: true,
          });
          if (accepted?.job_id) {
            try {
              await pollJob(String(accepted.job_id), 120000, 1200);
            } catch (error) {
              const latestPoolAfterInterrupt = await refreshPoolState(targetPoolId);
              const latestStatusAfterInterrupt = String(
                latestPoolAfterInterrupt?.status || ''
              ).toLowerCase();
              if (
                !autoLoopActiveRef.current ||
                INTERRUPT_SAFE_STATUSES.has(latestStatusAfterInterrupt)
              ) {
                appendLog(
                  `鑷不涓柇鏀跺彛锛氭睜鐘舵€?${
                    latestStatusAfterInterrupt || 'unknown'
                  }`
                );
                break;
              }
              throw error;
            }
          }
          continue;
        }

        const shouldFinalize =
          status === 'stopping' ||
          status === 'stopped' ||
          status === 'finalizing' ||
          currentRound >= maxRoundLimit;
        if (shouldFinalize) {
          appendLog('执行最终收口（finalize）');
          const accepted = await finalizeHypothesisPool(targetPoolId, {
            workspace_id: workspaceId,
            async_mode: true,
          });
          if (accepted?.job_id) {
            await pollJob(String(accepted.job_id), 120000, 1200);
          }
          const finalizedPool = await refreshPoolState(targetPoolId);
          const finalizedStatus = String(finalizedPool?.status || '').toLowerCase();
          appendLog(`收口完成：池状态=${finalizedStatus || 'unknown'}`);
          break;
        }

        appendLog(`自治等待：池状态=${status || 'unknown'}`);
        await new Promise((resolve) => setTimeout(resolve, 800));
      }
    } catch (error) {
      const latestPoolAfterError = await refreshPoolState(targetPoolId);
      const latestStatusAfterError = String(latestPoolAfterError?.status || '').toLowerCase();
      if (
        !autoLoopActiveRef.current ||
        INTERRUPT_SAFE_STATUSES.has(latestStatusAfterError)
      ) {
        appendLog(`自治中断收口：池状态=${latestStatusAfterError || 'unknown'}`);
        return;
      }
      showToast(getErrorMessage(error));
      appendLog(`自治失败：${getErrorMessage(error)}`);
    } finally {
      autoLoopRunningRef.current = false;
      setIsAutoRunning(false);
      await onRefresh();
    }
  };

  const handleToggleSource = (sourceId: string) => {
    hasUserTouchedSourcesRef.current = true;
    setSelectedSourceIds((prev) => {
      if (prev.includes(sourceId)) return prev.filter((item) => item !== sourceId);
      return dedupeSourceIds([...prev, sourceId]);
    });
  };

  const handleStartAutonomousRun = async () => {
    const normalizedGoal = String(researchGoal || '').trim();
    const normalizedSourceIds = dedupeSourceIds(selectedSourceIds);
    if (!normalizedGoal) {
      showToast('请先填写 research goal');
      return;
    }
    if (normalizedSourceIds.length === 0) {
      showToast('请至少选择 1 篇已确认文献');
      return;
    }
    setIsCreatingPool(true);
    try {
      appendLog(`启动 literature_frontier：sources=${normalizedSourceIds.length}`);
      const accepted = await generateLiteratureFrontierHypothesis({
        workspace_id: workspaceId,
        research_goal: normalizedGoal,
        source_ids: normalizedSourceIds,
        frontier_size: Math.max(3, Math.min(5, frontierSize)),
        max_rounds: Math.max(1, maxRounds),
        active_retrieval: {
          enabled: Boolean(allowRetrieval),
          max_papers_per_burst: 3,
          max_bursts: 2,
        },
      });
      const completed = accepted?.job_id
        ? await pollJob(String(accepted.job_id), 150000, 1200)
        : accepted;
      const createdPoolId = String(completed?.result_ref?.resource_id || '').trim();
      if (!createdPoolId) {
        throw new Error('未收到 hypothesis pool 编号');
      }
      setPoolId(createdPoolId);
      currentPoolIdRef.current = createdPoolId;
      autoLoopActiveRef.current = true;
      await refreshPoolState(createdPoolId);
      appendLog(`池创建成功：pool_id=${createdPoolId}`);
      showToast('frontier 池创建成功，开始自治执行');
      void runAutonomousLoop(createdPoolId);
    } catch (error) {
      /* obsolete guard removed
      legacy no-op block
        details removed
          `鎺у埗鍔ㄤ綔(${action})鍦ㄦ敹鍙ｇ姸鎬佷笅宸插拷鐣ワ細${
            UNKNOWN
          }`
        );
        return;
      }
      */
      showToast(getErrorMessage(error));
      appendLog(`启动失败：${getErrorMessage(error)}`);
    } finally {
      setIsCreatingPool(false);
    }
  };

  const runControl = async (
    action:
      | 'pause'
      | 'resume'
      | 'stop'
      | 'force_finalize'
      | 'disable_retrieval'
      | 'add_sources'
      | 'edit_reasoning_node'
      | 'delete_reasoning_node'
      | 'add_reasoning_node'
      | 'edit_candidate'
      | 'add_user_hypothesis',
    sourceIds?: string[]
  ) => {
    const targetPoolId = String(poolId || '').trim();
    if (!targetPoolId) {
      showToast('请先启动 frontier 池');
      return;
    }
    try {
    const latestPoolBeforeControl = await refreshPoolState(targetPoolId);
    const latestStatusBeforeControl = String(latestPoolBeforeControl?.status || '').toLowerCase();
    if (
      TERMINAL_POOL_STATUSES.has(latestStatusBeforeControl) &&
      action !== 'resume' &&
      action !== 'add_sources'
    ) {
      appendLog(
        `鎺у埗鍔ㄤ綔(${action})鍦ㄦ敹鍙ｇ姸鎬佷笅宸插拷鐣ワ細${latestStatusBeforeControl || 'unknown'}`
      );
      return;
    }
      let updatedPool: any;
      try {
        updatedPool = await controlHypothesisPool(targetPoolId, {
          workspace_id: workspaceId,
          action,
          ...(sourceIds ? { source_ids: sourceIds } : {}),
        });
      } catch (controlError) {
        const latestPoolAfterControlError = await refreshPoolState(targetPoolId);
        const latestStatusAfterControlError = String(
          latestPoolAfterControlError?.status || ''
        ).toLowerCase();
        if (
          TERMINAL_POOL_STATUSES.has(latestStatusAfterControlError) &&
          action !== 'resume' &&
          action !== 'add_sources'
        ) {
          appendLog(
            `鎺у埗鍔ㄤ綔(${action})鍦ㄦ敹鍙ｇ姸鎬佷笅宸插拷鐣ワ細${
              latestStatusAfterControlError || 'unknown'
            }`
          );
          return;
        }
        throw controlError;
      }
      setPool(updatedPool);
      appendLog(`控制动作：${action}`);
      if (action === 'pause' || action === 'stop' || action === 'force_finalize') {
        autoLoopActiveRef.current = false;
      }
      if (action === 'resume') {
        autoLoopActiveRef.current = true;
        void runAutonomousLoop(targetPoolId);
      }
      if (action === 'force_finalize') {
        const accepted = await finalizeHypothesisPool(targetPoolId, {
          workspace_id: workspaceId,
          async_mode: true,
        });
        if (accepted?.job_id) {
          await pollJob(String(accepted.job_id), 120000, 1200);
        }
      }
      await refreshPoolState(targetPoolId);
      await onRefresh();
      showToast(`已执行 ${action}`);
    } catch (error) {
      showToast(getErrorMessage(error));
      appendLog(`控制失败(${action})：${getErrorMessage(error)}`);
    }
  };

  const beginEdit = (candidate: any) => {
    const candidateId = String(candidate?.candidate_id || '').trim();
    if (!candidateId) return;
    const reasoningChain = candidate?.reasoning_chain || {};
    setEditingCandidateId(candidateId);
    setDraftConclusion(
      normalizeText(
        reasoningChain?.hypothesis_level_conclusion,
        candidate?.summary || candidate?.statement || ''
      )
    );
    setDraftReasoningSteps(reasoningStepTexts(reasoningChain).join('\n'));
    setDraftValidationSteps(
      toArray(reasoningChain?.required_validation)
        .map((item) => normalizeText(item, '').trim())
        .filter(Boolean)
        .join('\n')
    );
  };

  const cancelEdit = () => {
    setEditingCandidateId('');
    setDraftConclusion('');
    setDraftReasoningSteps('');
    setDraftValidationSteps('');
  };

  const saveAndContinue = async (candidate: any) => {
    const candidateId = String(candidate?.candidate_id || '').trim();
    const targetPoolId = String(poolId || '').trim();
    if (!candidateId || !targetPoolId) return;
    const previousConclusion = normalizeText(
      candidate?.reasoning_chain?.hypothesis_level_conclusion,
      ''
    );
    try {
      appendLog(`编辑候选并重跑：candidate=${candidateId}`);
      const patchedReasoningSteps = draftReasoningSteps
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .map((text, index) => ({
          step_id: `edited_step_${index + 1}`,
          kind: 'reasoning',
          text,
          source_node_ids: [],
        }));
      const patchedValidation = draftValidationSteps
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean);
      await patchHypothesisCandidate(candidateId, {
        workspace_id: workspaceId,
        reasoning_chain: {
          ...(candidate?.reasoning_chain || {}),
          hypothesis_statement: normalizeText(
            candidate?.reasoning_chain?.hypothesis_statement,
            candidate?.statement || ''
          ),
          hypothesis_level_conclusion: draftConclusion.trim(),
          reasoning_steps: patchedReasoningSteps,
          required_validation: patchedValidation,
        },
        reset_review_state: true,
      });
      setPreviousConclusions((prev) => ({
        ...prev,
        [candidateId]: previousConclusion,
      }));
      const accepted = await runHypothesisPoolRound(targetPoolId, {
        workspace_id: workspaceId,
        async_mode: true,
        max_matches: 6,
      });
      if (accepted?.job_id) {
        await pollJob(String(accepted.job_id), 120000, 1200);
      }
      await refreshPoolState(targetPoolId);
      await onRefresh();
      cancelEdit();
      appendLog(`候选重跑完成：candidate=${candidateId}`);
      showToast('已保存编辑并完成一轮继续推理');
    } catch (error) {
      showToast(getErrorMessage(error));
      appendLog(`编辑候选失败：${getErrorMessage(error)}`);
    }
  };

  const applyReasoningNodeControl = async (
    candidate: any,
    action: 'edit_reasoning_node' | 'delete_reasoning_node' | 'add_reasoning_node',
    node?: any
  ) => {
    const targetPoolId = String(poolId || '').trim();
    const candidateId = String(candidate?.candidate_id || '').trim();
    if (!targetPoolId || !candidateId) return;
    const nodeType =
      action === 'add_reasoning_node'
        ? String(window.prompt('节点类型：evidence / assumption / intermediate_reasoning / conclusion / validation_need', 'intermediate_reasoning') || '').trim()
        : String(node?.node_type || '').trim();
    if (!nodeType) return;
    const currentContent = String(node?.content || '');
    const nextContent =
      action === 'delete_reasoning_node'
        ? currentContent
        : String(window.prompt('节点内容', currentContent) || '').trim();
    if (action !== 'delete_reasoning_node' && !nextContent) return;
    if (
      action === 'delete_reasoning_node' &&
      !window.confirm('删除这个推理节点？后续审查和排名会失效并要求重检。')
    ) {
      return;
    }
    try {
      await controlHypothesisPool(targetPoolId, {
        workspace_id: workspaceId,
        action,
        candidate_id: candidateId,
        node: {
          node_id: String(node?.node_id || ''),
          node_type: nodeType as any,
          content: nextContent,
          source_refs: toArray(node?.source_refs),
        },
        control_reason: 'frontier_reasoning_graph_edit',
      });
      appendLog(`推理图节点已更新：${action} · candidate=${candidateId}`);
      showToast('已更新推理图，候选需要重新 Reflection/Ranking');
      await refreshPoolState(targetPoolId);
    } catch (error) {
      showToast(getErrorMessage(error));
      appendLog(`推理图节点更新失败：${getErrorMessage(error)}`);
    }
  };

  const addUserHypothesis = async () => {
    const targetPoolId = String(poolId || '').trim();
    const statement = userHypothesisDraft.trim();
    if (!targetPoolId || !statement) return;
    try {
      await controlHypothesisPool(targetPoolId, {
        workspace_id: workspaceId,
        action: 'add_user_hypothesis',
        user_hypothesis: {
          statement,
          title: '用户新增假设',
          hypothesis_level_conclusion: statement,
          reasoning_chain: {
            evidence: [],
            assumption: '用户新增假设，需要 Reflection agent 审查其证据与前提。',
            intermediate_reasoning: [],
            conclusion: statement,
            validation_need: '由后续 Reflection/Ranking 重新确定验证路径。',
          },
        },
        control_reason: 'frontier_user_added_hypothesis',
      });
      setUserHypothesisDraft('');
      appendLog('已加入用户假设，等待下一轮 Reflection/Ranking');
      showToast('用户假设已加入前沿池');
      await refreshPoolState(targetPoolId);
    } catch (error) {
      showToast(getErrorMessage(error));
      appendLog(`新增用户假设失败：${getErrorMessage(error)}`);
    }
  };

  const latestRound = poolRounds[0] || null;
  const supervisorArtifact = useMemo(() => getSupervisorArtifact(pool), [pool]);
  const reviewSummary = useMemo(() => {
    const summary = { survive: 0, revise: 0, drop: 0, unknown: 0 };
    for (const candidate of poolCandidates) {
      const verdict = String(candidate?.reasoning_chain?.review_status || '').toLowerCase();
      if (verdict === 'survive') summary.survive += 1;
      else if (verdict === 'revise') summary.revise += 1;
      else if (verdict === 'drop') summary.drop += 1;
      else summary.unknown += 1;
    }
    return summary;
  }, [poolCandidates]);

  const frontierCards = useMemo(() => {
    const effectiveSize = Number(pool?.top_k || frontierSize || 3);
    return pickFrontierCandidates(poolCandidates, effectiveSize);
  }, [poolCandidates, pool?.top_k, frontierSize]);

  const canStart = !isCreatingPool && !isAutoRunning;

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '20px', display: 'grid', gap: '14px' }}>
      <div className="hero-box" style={{ marginBottom: 0 }}>
        <div className="hero-title">文献闭环 Hypothesis Frontier</div>
        <div className="text-muted mb-16">
          仅基于已确认文献候选启动 `literature_frontier`，输出候选假设 + 推理链 + 所需验证。
        </div>
        <div style={{ display: 'grid', gap: '10px' }}>
          <div>
            <div className="form-label">Research Goal</div>
            <textarea
              className="paste-area"
              style={{ minHeight: '90px' }}
              value={researchGoal}
              onChange={(event) => setResearchGoal(event.target.value)}
              placeholder="输入本轮研究目标，例如：围绕武汉大学品牌声誉文献，提出 3-5 条可验证的差异化候选假设。"
            />
          </div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              <input
                type="checkbox"
                checked={allowRetrieval}
                onChange={(event) => setAllowRetrieval(event.target.checked)}
              />
              允许主动补检索
            </label>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              Frontier Size
              <input
                className="form-input"
                style={{ width: '72px' }}
                value={String(frontierSize)}
                onChange={(event) => setFrontierSize(Number(event.target.value || 3))}
              />
            </label>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              Max Rounds
              <input
                className="form-input"
                style={{ width: '72px' }}
                value={String(maxRounds)}
                onChange={(event) => setMaxRounds(Number(event.target.value || 2))}
              />
            </label>
            <button className="btn btn-p" onClick={handleStartAutonomousRun} disabled={!canStart}>
              {isCreatingPool ? '创建中...' : isAutoRunning ? '自治执行中...' : '启动自治执行'}
            </button>
            <button className="btn" onClick={() => goto('confirm')}>返回候选确认</button>
          </div>
          {poolId && (
            <div className="ev-card" style={{ marginBottom: 0 }}>
              <div className="ev-title">用户新增假设</div>
              <div className="ev-body">
                新增后不会直接进入最终前沿；它会被标记为 pending，并强制进入下一轮 Reflection/Ranking。
              </div>
              <textarea
                className="paste-area"
                style={{ minHeight: '72px', marginTop: '8px' }}
                value={userHypothesisDraft}
                onChange={(event) => setUserHypothesisDraft(event.target.value)}
                placeholder="写入你想加入推理图的新假设..."
              />
              <button
                className="btn"
                style={{ marginTop: '8px' }}
                onClick={() => void addUserHypothesis()}
                disabled={!userHypothesisDraft.trim()}
              >
                加入用户假设
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="section" style={{ marginBottom: 0 }}>
        <div className="sec-title">文献选择（仅已确认来源）</div>
        {eligibleSources.length === 0 ? (
          <div className="ev-card">
            <div className="ev-body">
              还没有可用文献来源。请先在“导入材料 → 候选确认”里确认候选。
            </div>
          </div>
        ) : (
          <div style={{ display: 'grid', gap: '8px' }}>
            {eligibleSources.map((source) => {
              const sourceId = String(source.source_id || '');
              const checked = selectedSourceIds.includes(sourceId);
              return (
                <label
                  key={sourceId}
                  className="ev-card"
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: 0 }}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => handleToggleSource(sourceId)}
                  />
                  <div style={{ flex: 1 }}>
                    <div className="ev-title">{normalizeText(source.title, sourceId)}</div>
                    <div className="ev-body">
                      source_id={sourceId} · type={normalizeText(source.source_type, 'paper')} · updated={toDateTime(source.updated_at)}
                    </div>
                  </div>
                </label>
              );
            })}
          </div>
        )}
      </div>

      <div className="section" style={{ marginBottom: 0 }}>
        <div className="sec-title">运行控制</div>
        <div className="ev-card" style={{ marginBottom: '8px' }}>
          <div className="ev-body">
            pool_id={normalizeText(poolId)} · status={normalizeText(pool?.status)} · round={Number(pool?.current_round_number || 0)}/{Number(pool?.max_rounds || maxRounds)}
            {isRefreshing ? ' · refreshing...' : ''}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '10px' }}>
            <button className="btn" onClick={() => runControl('pause')} disabled={!poolId || isCreatingPool}>暂停</button>
            <button className="btn" onClick={() => runControl('resume')} disabled={!poolId}>继续</button>
            <button className="btn" onClick={() => runControl('stop')} disabled={!poolId}>停止</button>
            <button className="btn btn-p" onClick={() => runControl('force_finalize')} disabled={!poolId}>最终产出</button>
            <button className="btn" onClick={() => runControl('disable_retrieval')} disabled={!poolId}>禁用补检索</button>
            <button
              className="btn"
              onClick={() => runControl('add_sources', dedupeSourceIds(selectedSourceIds))}
              disabled={!poolId || selectedSourceIds.length === 0}
            >
              追加来源
            </button>
            <button className="btn" onClick={() => void refreshPoolState()} disabled={!poolId}>
              刷新状态
            </button>
          </div>
        </div>
        {supervisorArtifact && (() => {
          const artifact = supervisorArtifact.artifact;
          const retrievalIntent = objectOrNull(artifact.retrieval_intent) || {};
          const decision = normalizeText(artifact.decision ?? supervisorArtifact.latestDecision);
          const isSupervisorRetrievalPause =
            decision.toLowerCase() === 'retrieve' &&
            retrievalIntent.needed === true &&
            String(pool?.status || '').toLowerCase() === 'paused';
          return (
            <div className="ev-card" style={{ marginBottom: '8px' }}>
              <div className="ev-title">Supervisor Decision</div>
              <div className="ev-body">
                source={supervisorArtifact.source} · latest_supervisor_decision={decision}
              </div>
              {isSupervisorRetrievalPause && (
                <div className="ev-body" style={{ marginTop: '6px' }}>
                  Supervisor 决策要求补证据，pool 已暂停等待 evidence gap 处理；这里展示的是 retrieval_intent，不表示主动检索已执行。
                </div>
              )}
              <div className="ev-body" style={{ marginTop: '6px' }}>
                <strong>decision_rationale：</strong> {normalizeText(artifact.decision_rationale)}
              </div>
              <div className="ev-body" style={{ marginTop: '6px' }}>
                <strong>strategy：</strong> {normalizeText(artifact.strategy)}
              </div>
              <div className="ev-body" style={{ marginTop: '6px' }}>
                <strong>user_control_state：</strong> {normalizeText(artifact.user_control_state)}
              </div>
              <div className="ev-body" style={{ marginTop: '6px' }}>
                <strong>retrieval_intent：</strong> needed={String(retrievalIntent.needed === true)} · evidence_gap=
                {normalizeText(retrievalIntent.evidence_gap)} · scope={normalizeText(retrievalIntent.scope)}
              </div>
              <div className="ev-body" style={{ marginTop: '6px' }}>
                <strong>stop_reason：</strong> {normalizeText(artifact.stop_reason)}
              </div>
            </div>
          );
        })()}
        <div className="ev-card" style={{ marginBottom: 0 }}>
          <div className="ev-title">当前 Review Gate</div>
          <div className="ev-body">
            survive={reviewSummary.survive} · revise={reviewSummary.revise} · drop={reviewSummary.drop} · unknown={reviewSummary.unknown}
          </div>
          {latestRound && (
            <div className="ev-body" style={{ marginTop: '8px' }}>
              最新轮次 round={Number(latestRound.round_number || 0)} · status={normalizeText(latestRound.status)} · generation={Number(latestRound.generation_count || 0)} · review={Number(latestRound.review_count || 0)} · ranking={Number(latestRound.match_count || 0)} · evolution={Number(latestRound.evolution_count || 0)}
            </div>
          )}
        </div>
      </div>

      <div className="section" style={{ marginBottom: 0 }}>
        <div className="sec-title">候选 Frontier（3-5）</div>
        {frontierCards.length === 0 ? (
          <div className="ev-card">
            <div className="ev-body">当前还没有可展示的 frontier 候选，先启动自治执行。</div>
          </div>
        ) : (
          <div style={{ display: 'grid', gap: '10px' }}>
            {frontierCards.map((candidate) => {
              const reasoningChain = candidate?.reasoning_chain || {};
              const sourceRefs = toArray(reasoningChain?.source_refs);
              const requiredValidation = [
                ...toArray(reasoningChain?.required_validation),
                normalizeText(reasoningChain?.reasoning_chain?.validation_need, '').trim(),
              ].filter(Boolean);
              const mechanismChain = reasoningStepTexts(reasoningChain);
              const editableNodes = reasoningNodes(reasoningChain);
              const confidenceBundle = reasoningChain?.confidence_bundle || {};
              const reviewHistory = toArray(reasoningChain?.review_history);
              const interventionHistory = toArray(reasoningChain?.user_interventions);
              const reviewStatus = normalizeText(reasoningChain?.review_status, 'unknown');
              const retrievalOrigin = normalizeText(
                reasoningChain?.retrieval_origin ?? candidate?.retrieval_origin,
                'uploaded'
              );
              const diversitySignature = reasoningChain?.diversity_signature || {};
              const candidateId = String(candidate?.candidate_id || '').trim();
              const isEditing = editingCandidateId === candidateId;
              const previousConclusion = previousConclusions[candidateId] || '';
              const currentConclusion = normalizeText(
                reasoningChain?.hypothesis_level_conclusion,
                candidate?.summary || candidate?.statement || '--'
              );
              return (
                <div key={String(candidate?.candidate_id || Math.random())} className="ev-card" style={{ marginBottom: 0 }}>
                  <div className="ev-top">
                    <div className="ev-title">{normalizeText(candidate?.title, '未命名候选')}</div>
                    <div className="ev-src">
                      elo={Number(candidate?.elo_rating || 0).toFixed(1)} · {String(candidate?.origin_type || '')}
                    </div>
                  </div>
                  <div className="ev-body">
                    <strong>假设结论：</strong>{' '}
                    {currentConclusion}
                  </div>
                  {previousConclusion && previousConclusion !== currentConclusion && (
                    <div className="ev-body" style={{ marginTop: '6px' }}>
                      <strong>上一次结论：</strong> {previousConclusion}
                    </div>
                  )}
                  <div className="ev-body" style={{ marginTop: '6px' }}>
                    <strong>推理链：</strong>
                    {mechanismChain.length > 0 ? (
                      <ul style={{ margin: '6px 0 0 18px' }}>
                        {mechanismChain.map((step, index) => (
                          <li key={`${candidate?.candidate_id}-mechanism-${index}`}>{normalizeText(step, '--')}</li>
                        ))}
                      </ul>
                    ) : (
                      <span> --</span>
                    )}
                  </div>
                  <div className="ev-body" style={{ marginTop: '6px' }}>
                    <strong>可编辑推理图节点：</strong>{' '}
                    {editableNodes.length === 0 ? (
                      <span>--</span>
                    ) : (
                      <div style={{ display: 'grid', gap: '6px', marginTop: '6px' }}>
                        {editableNodes.map((node) => (
                          <div
                            key={`${candidateId}-${normalizeText(node?.node_id)}`}
                            style={{
                              border: '1px solid rgba(148, 163, 184, 0.28)',
                              borderRadius: '8px',
                              padding: '8px',
                            }}
                          >
                            <div>
                              <strong>{normalizeText(node?.node_type)}</strong> · {normalizeText(node?.node_id)}
                            </div>
                            <div style={{ marginTop: '4px' }}>{normalizeText(node?.content)}</div>
                            <div style={{ display: 'flex', gap: '6px', marginTop: '6px', flexWrap: 'wrap' }}>
                              <button
                                className="btn"
                                onClick={() => void applyReasoningNodeControl(candidate, 'edit_reasoning_node', node)}
                              >
                                改节点
                              </button>
                              <button
                                className="btn"
                                onClick={() => void applyReasoningNodeControl(candidate, 'delete_reasoning_node', node)}
                              >
                                删节点
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    <button
                      className="btn"
                      style={{ marginTop: '8px' }}
                      onClick={() => void applyReasoningNodeControl(candidate, 'add_reasoning_node')}
                    >
                      加节点
                    </button>
                    {(reasoningChain?.requires_recheck || reasoningChain?.requires_rerank) && (
                      <div className="text-muted" style={{ marginTop: '6px' }}>
                        invalidation: requires_recheck={String(Boolean(reasoningChain?.requires_recheck))} ·
                        requires_rerank={String(Boolean(reasoningChain?.requires_rerank))} · reason=
                        {normalizeText(reasoningChain?.recheck_reason)}
                      </div>
                    )}
                  </div>
                  <div className="ev-body" style={{ marginTop: '6px' }}>
                    <strong>所需验证：</strong>
                    {requiredValidation.length > 0 ? (
                      <ul style={{ margin: '6px 0 0 18px' }}>
                        {requiredValidation.map((item, index) => (
                          <li key={`${candidate?.candidate_id}-validation-${index}`}>{normalizeText(item, '--')}</li>
                        ))}
                      </ul>
                    ) : (
                      <span> --</span>
                    )}
                  </div>
                  <div className="ev-body" style={{ marginTop: '6px' }}>
                    <strong>证据来源：</strong> {sourceRefs.length} 条 · retrieval_origin={retrievalOrigin}
                    {sourceRefs.length > 0 && (
                      <ul style={{ margin: '6px 0 0 18px' }}>
                        {sourceRefs.slice(0, 4).map((ref, index) => (
                          <li key={`${candidate?.candidate_id}-source-${index}`}>
                            source_id={normalizeText(ref?.source_id)} · span=
                            {normalizeText(ref?.source_span?.desc || ref?.source_span?.text || JSON.stringify(ref?.source_span || {}))}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="ev-body" style={{ marginTop: '6px' }}>
                    <strong>反思状态：</strong> {reviewStatus} · history={reviewHistory.length} · revise_count=
                    {Number(reasoningChain?.revise_count || 0)} · {String(candidate?.origin_type || '').startsWith('evolution') ? '来自 Evolution' : '来自 Generation'}
                  </div>
                  <div className="ev-body" style={{ marginTop: '6px' }}>
                    <strong>用户干预轨迹：</strong> {interventionHistory.length} 条
                    {interventionHistory.length > 0 && (
                      <ul style={{ margin: '6px 0 0 18px' }}>
                        {interventionHistory.slice(-3).map((item, index) => (
                          <li key={`${candidateId}-intervention-${index}`}>
                            action={normalizeText(item?.action)} · request={normalizeText(item?.request_id)} · at=
                            {normalizeText(item?.created_at)}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="ev-body" style={{ marginTop: '6px' }}>
                    <strong>审计 transcript：</strong> generation={normalizeText(reasoningChain?.generation_transcript_id)} · latest_review=
                    {normalizeText(reviewHistory[reviewHistory.length - 1]?.transcript_id)}
                  </div>
                  <div className="ev-body" style={{ marginTop: '6px' }}>
                    <strong>置信度：</strong> {normalizeText(confidenceBundle?.confidence_level, 'unknown')} · evidence=
                    {toPercent(confidenceBundle?.evidence_strength)} · provenance={toPercent(confidenceBundle?.provenance_coverage)} · validation=
                    {toPercent(confidenceBundle?.validation_strength)}
                  </div>
                  <div className="ev-body" style={{ marginTop: '6px' }}>
                    <strong>多样性签名：</strong> mechanism={normalizeText(diversitySignature?.mechanism_signature)} · validation_path=
                    {normalizeText(diversitySignature?.validation_path)}
                  </div>
                  <div style={{ display: 'flex', gap: '8px', marginTop: '10px', flexWrap: 'wrap' }}>
                    <button className="btn" onClick={() => beginEdit(candidate)}>
                      编辑链路
                    </button>
                    {isEditing && (
                      <>
                        <button className="btn btn-p" onClick={() => void saveAndContinue(candidate)}>
                          保存并继续
                        </button>
                        <button className="btn" onClick={cancelEdit}>
                          取消
                        </button>
                      </>
                    )}
                  </div>
                  {isEditing && (
                    <div style={{ display: 'grid', gap: '8px', marginTop: '10px' }}>
                      <label style={{ display: 'grid', gap: '4px' }}>
                        <span className="text-muted">结论（hypothesis_level_conclusion）</span>
                        <textarea
                          className="paste-area"
                          style={{ minHeight: '72px' }}
                          value={draftConclusion}
                          onChange={(event) => setDraftConclusion(event.target.value)}
                        />
                      </label>
                      <label style={{ display: 'grid', gap: '4px' }}>
                        <span className="text-muted">推理步骤（每行一条）</span>
                        <textarea
                          className="paste-area"
                          style={{ minHeight: '96px' }}
                          value={draftReasoningSteps}
                          onChange={(event) => setDraftReasoningSteps(event.target.value)}
                        />
                      </label>
                      <label style={{ display: 'grid', gap: '4px' }}>
                        <span className="text-muted">所需验证（每行一条）</span>
                        <textarea
                          className="paste-area"
                          style={{ minHeight: '72px' }}
                          value={draftValidationSteps}
                          onChange={(event) => setDraftValidationSteps(event.target.value)}
                        />
                      </label>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="section" style={{ marginBottom: 0 }}>
        <div className="sec-title">轮次与执行日志</div>
        <div className="ev-card" style={{ marginBottom: '8px' }}>
          <div className="ev-title">Rounds</div>
          {poolRounds.length === 0 ? (
            <div className="ev-body">尚未产生轮次。</div>
          ) : (
            <div style={{ display: 'grid', gap: '6px' }}>
              {poolRounds.map((round) => (
                <div key={String(round?.round_id || Math.random())} className="ev-body">
                  round={Number(round?.round_number || 0)} · status={normalizeText(round?.status)} · generation={Number(round?.generation_count || 0)} · review={Number(round?.review_count || 0)} · ranking={Number(round?.match_count || 0)} · evolution={Number(round?.evolution_count || 0)}
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="ev-card" style={{ marginBottom: 0 }}>
          <div className="ev-title">Activity</div>
          {poolTrajectory && (
            <div className="ev-body" style={{ marginBottom: '8px' }}>
              <strong>Trajectory：</strong> events=
              {toArray(poolTrajectory?.chronological_events).length} · candidate_lineage=
              {toArray(poolTrajectory?.candidate_lineage).length} · retrieval=
              {normalizeText(poolTrajectory?.service_traces?.retrieval?.status, 'none')} · proximity_edges=
              {toArray(poolTrajectory?.service_traces?.proximity?.edges).length}
            </div>
          )}
          {poolTranscripts.length > 0 && (
            <div className="ev-body" style={{ marginBottom: '8px' }}>
              <strong>Agent transcripts：</strong>{' '}
              {poolTranscripts.slice(0, 8).map((item, index) => (
                <span
                  key={String(
                    item?.transcript_id ||
                      `${item?.agent_name || 'agent'}-${item?.created_at || 'unknown'}-${index}`
                  )}
                  style={{ marginRight: '8px' }}
                >
                  {normalizeText(item?.agent_name)}:{normalizeText(item?.status)}
                </span>
              ))}
            </div>
          )}
          {activityLog.length === 0 ? (
            <div className="ev-body">暂无执行日志。</div>
          ) : (
            <div style={{ display: 'grid', gap: '4px' }}>
              {activityLog.map((line, index) => (
                <div key={`${line}-${index}`} className="ev-body">{line}</div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
