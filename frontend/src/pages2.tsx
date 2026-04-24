import React, { useMemo, useState, useEffect, useRef } from 'react';
import {
  createGraphNode,
  createGraphEdge,
  patchGraphNode,
  deleteGraphNode,
  recomputeRoutes,
  pollJob,
  createFailure,
  createValidation,
  submitValidationResult,
  replayPackage,
  getErrorMessage,
  getGraphSupportChains,
  getGraphPredictedLinks,
  getGraphDeepChains,
  getGraphReport,
  queryGraph,
  type MemoryRecallResponse,
} from './api';
import { normalizeGraphInspectorPayloads } from './graph-inspector-helpers';
import {
  clampZoom,
  computeClusteredLayout,
  getSelectionFocus,
  loadPinnedPositions,
  savePinnedPositions,
} from './workbench-graph-layout';

function isJobTimeoutLike(error: unknown) {
  const code = String((error as any)?.envelope?.error_code || (error as any)?.error_code || '').toLowerCase();
  return code === 'research.job_timeout' || code === 'research.request_timeout';
}

export function WorkbenchPage({ initialNodes, initialEdges, edgeColors, goto, showToast, workspaceId, onRefresh }: any) {
  const normalizeNodeType = (rawType: string) => {
    const key = String(rawType || '').toLowerCase();
    if (key === 'a') return 'assumption';
    if (key === 'e') return 'evidence';
    if (key === 'c') return 'conflict';
    if (key === 'f') return 'failure';
    if (key === 'g') return 'validation';
    return key || rawType;
  };

  const [nodes, setNodes] = useState(initialNodes || []);
  const [edges, setEdges] = useState(initialEdges || []);
  const [selNode, setSelNode] = useState<any>(null);
  const [pendingEdgeSourceId, setPendingEdgeSourceId] = useState<string | null>(null);
  const [isEdgeMode, setIsEdgeMode] = useState(false);
  const [isEditingNode, setIsEditingNode] = useState(false);
  const [isRecomputingRoutes, setIsRecomputingRoutes] = useState(false);
  const [isCreatingNode, setIsCreatingNode] = useState(false);
  const [isAddNodeOpen, setIsAddNodeOpen] = useState(false);
  const [newNodeName, setNewNodeName] = useState('');
  const [newNodeSourceNote, setNewNodeSourceNote] = useState('');
  const [editLabel, setEditLabel] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editTags, setEditTags] = useState('');
  const [viewport, setViewport] = useState({ x: 0, y: 0, scale: 1 });
  const [isDragging, setIsDragging] = useState(false);
  const [startPan, setStartPan] = useState({ x: 0, y: 0 });
  const [pinnedPositions, setPinnedPositions] = useState<Record<string, { x: number; y: number }>>(() =>
    loadPinnedPositions(workspaceId)
  );
  const [draggedNode, setDraggedNode] = useState<any>(null);
  const nodeDragMovedRef = useRef(false);
  const [inspectorState, setInspectorState] = useState<any>({
    status: 'idle',
    error: null,
    data: null,
  });
  const [nodeMemoryRecall, setNodeMemoryRecall] = useState<MemoryRecallResponse | null>(null);
  const [nodeMemoryRecallStatus, setNodeMemoryRecallStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');

  useEffect(() => {
    setPinnedPositions(loadPinnedPositions(workspaceId));
  }, [workspaceId]);

  useEffect(() => {
    if (initialNodes) {
      const normalizedNodes = initialNodes.map((node: any) => ({
        ...node,
        node_type: normalizeNodeType(node?.node_type),
      }));
      const layout = computeClusteredLayout(normalizedNodes, initialEdges || [], pinnedPositions);
      setNodes(
        normalizedNodes.map((node: any) => ({
          ...node,
          x: layout[node.node_id]?.x ?? Number(node.x || 0),
          y: layout[node.node_id]?.y ?? Number(node.y || 0),
        }))
      );
    }
    if (initialEdges) setEdges(initialEdges);
  }, [initialNodes, initialEdges, pinnedPositions]);

  useEffect(() => {
    if (!selNode?.node_id) return;
    const latest = (nodes || []).find((node: any) => node.node_id === selNode.node_id);
    if (latest) {
      setSelNode({ ...latest, node_type: normalizeNodeType(latest?.node_type) });
      return;
    }
    setSelNode(null);
    setIsEditingNode(false);
  }, [nodes, selNode?.node_id]);

  useEffect(() => {
    if (!selNode?.node_id) {
      setInspectorState({ status: 'idle', error: null, data: null });
      return;
    }
    let cancelled = false;
    setInspectorState({ status: 'loading', error: null, data: null });
    Promise.all([
      getGraphSupportChains(workspaceId, selNode.node_id),
      getGraphPredictedLinks(workspaceId, selNode.node_id),
      getGraphDeepChains(workspaceId, selNode.node_id),
      getGraphReport(workspaceId),
    ])
      .then(([supportChains, predictedLinks, deepChains, report]) => {
        if (cancelled) return;
        setInspectorState({
          status: 'ready',
          error: null,
          data: normalizeGraphInspectorPayloads({ supportChains, predictedLinks, deepChains, report }),
        });
      })
      .catch((error) => {
        if (cancelled) return;
        setInspectorState({
          status: 'error',
          error: getErrorMessage(error),
          data: null,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [selNode?.node_id, workspaceId]);

  useEffect(() => {
    if (!selNode?.node_id) {
      setNodeMemoryRecall(null);
      setNodeMemoryRecallStatus('idle');
      return;
    }
    let cancelled = false;
    setNodeMemoryRecallStatus('loading');
    queryGraph(workspaceId, selNode.node_id, 1)
      .then((graph) => {
        if (cancelled) return;
        setNodeMemoryRecall(
          graph?.memory_recall || {
            status: 'skipped',
            requested_method: 'auto',
            applied_method: 'none',
            reason: '节点查询未返回相关记忆',
            query_text: String(selNode?.short_label || selNode?.node_id || ''),
            total: 0,
            items: [],
            trace_refs: {},
          }
        );
        setNodeMemoryRecallStatus('ready');
      })
      .catch((error) => {
        if (cancelled) return;
        setNodeMemoryRecall({
          status: 'failed',
          requested_method: 'auto',
          applied_method: 'none',
          reason: getErrorMessage(error),
          query_text: String(selNode?.short_label || selNode?.node_id || ''),
          total: 0,
          items: [],
          trace_refs: {},
        });
        setNodeMemoryRecallStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [selNode?.node_id, workspaceId]);

  const handleMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('.graph-node')) return;
    setIsDragging(true);
    setStartPan({ x: e.clientX - viewport.x, y: e.clientY - viewport.y });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (draggedNode) {
      const nextX = draggedNode.startX + (e.clientX - draggedNode.startClientX) / viewport.scale;
      const nextY = draggedNode.startY + (e.clientY - draggedNode.startClientY) / viewport.scale;
      nodeDragMovedRef.current =
        nodeDragMovedRef.current ||
        Math.abs(e.clientX - draggedNode.startClientX) > 3 ||
        Math.abs(e.clientY - draggedNode.startClientY) > 3;
      setDraggedNode({ ...draggedNode, currentX: nextX, currentY: nextY });
      setNodes((prev: any[]) =>
        prev.map((node: any) => (node.node_id === draggedNode.nodeId ? { ...node, x: nextX, y: nextY } : node))
      );
      return;
    }
    if (!isDragging) return;
    setViewport((prev) => ({ ...prev, x: e.clientX - startPan.x, y: e.clientY - startPan.y }));
  };

  const handleMouseUp = () => {
    if (draggedNode) {
      const nextPinned = {
        ...pinnedPositions,
        [draggedNode.nodeId]: {
          x: draggedNode.currentX ?? draggedNode.startX,
          y: draggedNode.currentY ?? draggedNode.startY,
        },
      };
      setPinnedPositions(savePinnedPositions(workspaceId, nextPinned));
      setDraggedNode(null);
    }
    setIsDragging(false);
  };

  const handleWheel = (e: React.WheelEvent) => {
    setViewport((prev) => ({ ...prev, scale: clampZoom(prev.scale, e.deltaY) }));
  };

  const handleNodeMouseDown = (e: React.MouseEvent, node: any) => {
    if (e.button !== 0 || isEdgeMode) return;
    e.stopPropagation();
    nodeDragMovedRef.current = false;
    setDraggedNode({
      nodeId: node.node_id,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startX: Number(node.x || 0),
      startY: Number(node.y || 0),
      currentX: Number(node.x || 0),
      currentY: Number(node.y || 0),
    });
  };

  const addNode = () => {
    setNewNodeName('');
    setNewNodeSourceNote('');
    setIsAddNodeOpen(true);
  };

  const handleCreateNode = async () => {
    const nodeName = newNodeName.trim();
    const sourceNote = newNodeSourceNote.trim();
    if (!nodeName) {
      showToast('节点名称不能为空');
      return;
    }
    if (!sourceNote) {
      showToast('来源说明不能为空');
      return;
    }
    const claimId = getNodeClaimId(selNode);
    if (!claimId) {
      showMissingClaimToast();
      return;
    }
    setIsCreatingNode(true);
    try {
      const created = await createGraphNode({
        workspace_id: workspaceId,
        node_type: 'assumption',
        object_ref_type: 'hypothesis',
        object_ref_id: `ui-node-${Date.now()}`,
        short_label: nodeName,
        full_description: sourceNote,
        short_tags: ['未验证'],
        visibility: 'workspace',
        source_refs: [
          {
            source_type: 'manual_note',
            note: sourceNote,
            created_from: 'workbench_add_node',
            inherited_from_node_id: selNode.node_id,
            claim_id: claimId,
            created_at: new Date().toISOString(),
          },
        ],
        claim_id: claimId,
      });
      await onRefresh?.();
      setIsAddNodeOpen(false);
      setSelNode(created);
      setPendingEdgeSourceId(null);
      setEditLabel(String(created?.short_label || ''));
      setEditDescription(String(created?.full_description || ''));
      setEditTags(Array.isArray(created?.short_tags) ? created.short_tags.join(', ') : '');
      setIsEditingNode(true);
      showToast('已创建节点并写入来源说明');
    } catch (error) {
      showToast(getErrorMessage(error));
    } finally {
      setIsCreatingNode(false);
    }
  };

  const ensureSelectedNode = () => {
    if (!selNode?.node_id) {
      showToast('请先选择节点');
      return false;
    }
    return true;
  };

  const getNodeClaimId = (node: any) => {
    const claimId = String(node?.claim_id || '').trim();
    return claimId || null;
  };

  const findNodeById = (nodeId: string | null) =>
    (nodes || []).find((node: any) => String(node?.node_id || '') === String(nodeId || ''));

  const showMissingClaimToast = () => {
    showToast('无法入图：请选择已有 claim-backed 节点以继承 claim_id');
  };

  const handleAddEdge = async () => {
    if (isEdgeMode) {
      setIsEdgeMode(false);
      setPendingEdgeSourceId(null);
      showToast('已退出连接模式');
      return;
    }
    if (nodes.length < 2) {
      showToast('至少需要 2 个节点才能建立连接');
      return;
    }
    setIsEdgeMode(true);
    setIsEditingNode(false);
    if (selNode?.node_id) {
      setPendingEdgeSourceId(selNode.node_id);
      showToast('已选择源节点，请点击目标节点完成连接');
      return;
    }
    setPendingEdgeSourceId(null);
    showToast('连接模式已开启，请先点击源节点');
  };

  const handleNodeClick = async (node: any) => {
    if (nodeDragMovedRef.current) {
      nodeDragMovedRef.current = false;
      return;
    }
    if (!isEdgeMode) {
      setSelNode(node);
      setIsEditingNode(false);
      return;
    }

    if (!pendingEdgeSourceId) {
      setPendingEdgeSourceId(node.node_id);
      setSelNode(node);
      setIsEditingNode(false);
      showToast('源节点已选，请点击目标节点');
      return;
    }

    if (pendingEdgeSourceId === node.node_id) {
      showToast('请点击不同节点作为目标');
      return;
    }

    try {
      const sourceNode = findNodeById(pendingEdgeSourceId);
      const claimId = getNodeClaimId(sourceNode) || getNodeClaimId(node);
      if (!claimId) {
        setIsEdgeMode(false);
        setPendingEdgeSourceId(null);
        showMissingClaimToast();
        return;
      }
      const createdEdge = await createGraphEdge({
        workspace_id: workspaceId,
        source_node_id: pendingEdgeSourceId,
        target_node_id: node.node_id,
        edge_type: 'supports',
        object_ref_type: 'manual',
        object_ref_id: `ui-edge-${Date.now()}`,
        strength: 0.7,
        claim_id: claimId,
      });
      setEdges((prev: any[]) => {
        if (prev.some((item: any) => String(item?.edge_id) === String(createdEdge?.edge_id))) {
          return prev;
        }
        return [...prev, createdEdge];
      });
      setIsEdgeMode(false);
      setPendingEdgeSourceId(null);
      await onRefresh?.();
      setSelNode(node);
      showToast('已添加连接');
    } catch (error) {
      setIsEdgeMode(false);
      setPendingEdgeSourceId(null);
      showToast(`连接失败：${getErrorMessage(error)}`);
    }
  };

  const handleEditNode = () => {
    if (!ensureSelectedNode()) return;
    setPendingEdgeSourceId(null);
    setEditLabel(String(selNode.short_label || ''));
    setEditDescription(String(selNode.full_description || ''));
    setEditTags(Array.isArray(selNode.short_tags) ? selNode.short_tags.join(', ') : '');
    setIsEditingNode(true);
  };

  const handleSaveNodeEdit = async () => {
    if (!ensureSelectedNode()) return;
    const shortLabel = editLabel.trim();
    if (!shortLabel) {
      showToast('节点名称不能为空');
      return;
    }
    try {
      const parsedTags = editTags
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean);
      const patched = await patchGraphNode(selNode.node_id, {
        workspace_id: workspaceId,
        short_label: shortLabel,
        full_description: editDescription.trim(),
        short_tags: parsedTags,
      });
      setSelNode(patched);
      setIsEditingNode(false);
      await onRefresh?.();
      showToast('节点已更新');
    } catch (error) {
      showToast(getErrorMessage(error));
    }
  };

  const handleCancelEditNode = () => {
    setIsEditingNode(false);
  };

  const handleAddEvidence = async () => {
    if (!ensureSelectedNode()) return;
    const claimId = getNodeClaimId(selNode);
    if (!claimId) {
      showMissingClaimToast();
      return;
    }
    try {
      const evidence = await createGraphNode({
        workspace_id: workspaceId,
        node_type: 'evidence',
        object_ref_type: 'evidence',
        object_ref_id: `ui-evidence-${Date.now()}`,
        short_label: `${selNode.short_label} 补充证据`,
        full_description: `${selNode.short_label} 补充证据`,
        short_tags: ['补充'],
        visibility: 'workspace',
        source_refs: [
          {
            source_type: 'manual_note',
            created_from: 'workbench_add_evidence',
            inherited_from_node_id: selNode.node_id,
            claim_id: claimId,
          },
        ],
        claim_id: claimId,
      });
      await createGraphEdge({
        workspace_id: workspaceId,
        source_node_id: evidence.node_id,
        target_node_id: selNode.node_id,
        edge_type: 'supports',
        object_ref_type: 'manual',
        object_ref_id: `ui-edge-${Date.now()}`,
        strength: 0.6,
        claim_id: claimId,
      });
      await onRefresh?.();
      showToast('已补充证据');
    } catch (error) {
      showToast(getErrorMessage(error));
    }
  };

  const handleAttachFailure = async () => {
    if (!ensureSelectedNode()) return;
    try {
      const failure = await createFailure({
        workspace_id: workspaceId,
        attached_targets: [{ target_type: 'node', target_id: selNode.node_id }],
        observed_outcome: `${selNode.short_label} 验证失败`,
        expected_difference: '预期结果与实际结果不一致',
        failure_reason: '前端工作台录入失败记录',
        severity: 'high',
        reporter: 'frontend_user',
      });
      const accepted = await recomputeRoutes(workspaceId, 'validation_failed', failure.failure_id);
      if (accepted?.job_id) {
        try {
          await pollJob(accepted.job_id, 45000, 1200);
        } catch (error) {
          if (!isJobTimeoutLike(error)) throw error;
        }
      }
      await onRefresh?.();
      showToast(
        accepted?.job_id
          ? `失败记录已挂载，并已提交重算（job ${accepted.job_id}）`
          : '失败记录已挂载并触发重算'
      );
    } catch (error) {
      showToast(getErrorMessage(error));
    }
  };

  const handleDeleteNode = async () => {
    if (!ensureSelectedNode()) return;
    try {
      await deleteGraphNode(selNode.node_id, workspaceId, 'ui_delete');
      setSelNode(null);
      setIsEdgeMode(false);
      setPendingEdgeSourceId(null);
      setIsEditingNode(false);
      await onRefresh?.();
      showToast('已删除节点');
    } catch (error) {
      showToast(getErrorMessage(error));
    }
  };

  const handleRecomputeRoutes = async () => {
    if (isRecomputingRoutes) return;
    if (!(nodes.length > 1 && edges.length > 0)) {
      showToast(`当前图谱为 ${nodes.length} 个节点 / ${edges.length} 条连接，至少需要 2 个节点且 1 条连接`);
      return;
    }
    setIsRecomputingRoutes(true);
    try {
      const accepted = await recomputeRoutes(workspaceId, 'ui_manual_recompute');
      if (accepted?.job_id) {
        await pollJob(accepted.job_id, 120000, 1200);
      }
      await onRefresh?.();
      showToast('重算完成');
    } catch (error) {
      showToast(getErrorMessage(error));
    } finally {
      setIsRecomputingRoutes(false);
    }
  };

  const handleAutoLayout = () => {
    if (!nodes.length) {
      showToast('当前没有可布局节点');
      return;
    }

    const layout = computeClusteredLayout(nodes, edges, {});
    const next = nodes.map((node: any) => ({
      ...node,
      x: layout[node.node_id]?.x ?? node.x,
      y: layout[node.node_id]?.y ?? node.y,
    }));

    setPinnedPositions(savePinnedPositions(workspaceId, {}));
    setNodes(next);
    if (selNode?.node_id) {
      const mapped = next.find((node: any) => node.node_id === selNode.node_id);
      if (mapped) setSelNode(mapped);
    }
    showToast(`已自动排版 ${next.length} 个节点`);
  };

  const getTypeLbl = (type: string) => {
    const key = String(type || '').toLowerCase();
    const map: any = {
      c: '结论',
      e: '证据',
      a: '推理前提',
      conflict: '冲突信号',
      f: '失败记录',
      g: '证据缺口',
      conclusion: '结论',
      evidence: '证据',
      assumption: '推理前提',
      failure: '失败记录',
      validation: '证据缺口',
      gap: '证据缺口',
    };
    return map[key] || type;
  };
  const memoryTypeLabel = (type?: string) => {
    const key = String(type || '').toLowerCase();
    if (key === 'episodic_memory') return '事件记忆';
    if (key === 'profile') return '画像记忆';
    if (key === 'foresight') return '前瞻记忆';
    if (key === 'event_log') return '事件日志';
    return type || '未分类记忆';
  };
  const inspectorData = inspectorState.data;
  const renderInsightItems = (items: any[], emptyText: string) => {
    if (!items.length) return <div className="insight-empty">{emptyText}</div>;
    return items.slice(0, 4).map((item: any, index: number) => {
      const title =
        item.title ||
        item.path_id ||
        item.chain_id ||
        item.sourceNodeId ||
        item.source_node_id ||
        `结果 ${index + 1}`;
      const detail =
        item.predictedEdgeType
          ? `${item.predictedEdgeType} · 置信度 ${Math.round(Number(item.confidence || 0) * 100)}%`
          : item.edge_type_sequence
          ? `链路：${item.edge_type_sequence.join(' → ')}`
          : item.short_label || item.targetNodeId || item.target_node_id || '';
      return (
        <div className="insight-row" key={`${title}-${index}`}>
          <div className="insight-row-title">{String(title)}</div>
          {detail && <div className="insight-row-detail">{String(detail)}</div>}
        </div>
      );
    });
  };
  const renderMemoryRecallItems = (memoryRecall?: MemoryRecallResponse | null) => {
    if (!memoryRecall) {
      return <div className="insight-empty">当前节点尚未返回相关记忆。</div>;
    }
    if (memoryRecall.status === 'loading') {
      return <div className="insight-empty">正在检索相关记忆...</div>;
    }
    if (memoryRecall.status === 'failed') {
      return <div className="insight-error">检索失败：{memoryRecall.reason || '未返回失败原因'}</div>;
    }
    if (memoryRecall.status === 'skipped') {
      return <div className="insight-empty">当前未触发相关检索：{memoryRecall.reason || '未满足检索条件'}</div>;
    }
    if (!memoryRecall.items?.length) {
      return <div className="insight-empty">已执行检索，但没有召回到可展示的历史记忆。</div>;
    }
    return (
      <>
        <div className="insight-row-detail">
          共召回 {memoryRecall.total} 条 · 请求方式 {memoryRecall.requested_method} · 实际方式 {memoryRecall.applied_method}
        </div>
        {memoryRecall.items.slice(0, 4).map((item, index) => (
          <div className="insight-row" key={`${item.memory_id || item.memory_type}-${index}`}>
            <div className="insight-row-title">{memoryTypeLabel(item.memory_type)}</div>
            <div className="insight-row-detail">
              {item.snippet || item.title || '未返回摘要'}{item.score ? ` · 相关度 ${Math.round(Number(item.score || 0) * 100)}%` : ''}
            </div>
          </div>
        ))}
      </>
    );
  };
  const hasActionableGraph = nodes.length > 1 && edges.length > 0;
  const canEnterEdgeMode = nodes.length >= 2;
  const canAutoLayout = nodes.length > 0;
  const selectionFocus = useMemo(
    () => getSelectionFocus(selNode?.node_id, edges),
    [selNode?.node_id, edges]
  );
  const pendingEdgeSourceNode = pendingEdgeSourceId
    ? nodes.find((node: any) => node.node_id === pendingEdgeSourceId)
    : null;
  const edgeModeHint = !isEdgeMode
    ? ''
    : pendingEdgeSourceNode
      ? `已选源节点：${String(pendingEdgeSourceNode.short_label || pendingEdgeSourceNode.node_id)}`
      : '连接模式开启，请先点击源节点';

  return (
    <div className="wb-layout">
      <div className="wb-version-bar">
        <div className="ver-dot cur">节点 {nodes.length}</div>
        <div className="ver-dot cur">连接 {edges.length}</div>
        <div className="ver-dot cur">{isEdgeMode ? '连接模式：开启' : '连接模式：关闭'}</div>
      </div>
      <div className="wb-main">
        <div
          className="canvas-area"
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onWheel={handleWheel}
          style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
        >
          <div className="zoom-hud">{Math.round(viewport.scale * 100)}%</div>
          <div className="canvas-bg" style={{ backgroundPosition: `${viewport.x}px ${viewport.y}px` }}></div>
          <div style={{ transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.scale})`, transformOrigin: '0 0', width: '100%', height: '100%', position: 'absolute', inset: 0, pointerEvents: 'none' }}>
            <svg className="edges" style={{ pointerEvents: 'none' }}>
              {edges.map((e: any, i: number) => {
                const s = nodes.find((n: any) => n.node_id === e.source_node_id);
                const t = nodes.find((n: any) => n.node_id === e.target_node_id);
                if (!s || !t) return null;
                const edgeKey = `${String(e.source_node_id || '')}->${String(e.target_node_id || '')}#${i}`;
                const hasSelection = Boolean(selNode?.node_id);
                const isFocusedEdge = selectionFocus.connectedEdgeKeys.has(edgeKey);
                const x1 = s.x + 90;
                const y1 = s.y + 60;
                const x2 = t.x + 90;
                const y2 = t.y;
                const my = (y1 + y2) / 2;
                return (
                  <path
                    key={edgeKey}
                    className={`edge-path ${isFocusedEdge ? 'edge-active' : ''} ${hasSelection && !isFocusedEdge ? 'edge-muted' : ''}`}
                    d={`M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`}
                    fill="none"
                    stroke={isFocusedEdge ? 'var(--accent-strong)' : edgeColors[e.edge_type]}
                    strokeWidth={isFocusedEdge ? '4' : '2'}
                    strokeDasharray={e.edge_type === 'gaps' ? '4 4' : 'none'}
                  />
                );
              })}
            </svg>
            <div className="wb-canvas" style={{ pointerEvents: 'auto' }}>
              {nodes.map((n: any) => {
                const isSelected = selNode?.node_id === n.node_id || pendingEdgeSourceId === n.node_id;
                const hasSelection = Boolean(selNode?.node_id);
                const isRelated = selectionFocus.connectedNodeIds.has(n.node_id);
                return (
                  <div
                    key={n.node_id}
                    className={`graph-node gn-${n.node_type} ${isSelected ? 'sel' : ''} ${isRelated ? 'related' : ''} ${hasSelection && !isSelected && !isRelated ? 'muted' : ''}`}
                    style={{ left: n.x, top: n.y }}
                    onMouseDown={(event) => handleNodeMouseDown(event, n)}
                    onClick={() => handleNodeClick(n)}
                  >
                    <div className="gn-inner">
                      <div className="gn-type">{getTypeLbl(n.node_type)}</div>
                      <div className="gn-label">{n.short_label}</div>
                      <div className="gn-tags">{n.short_tags?.map((t: string) => <div key={t} className="gn-tag">{t}</div>)}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
        <div className="wb-inspector">
          {selNode ? (
            <>
              <div className="insp-hdr">
                <div className="insp-title">属性面板</div>
                <div className="insp-node-name">{selNode.short_label?.replace('\n', ' ')}</div>
              </div>
              <div className="insp-body">
                <div className="insp-section">
                  <div className="insp-sec-lbl">节点类型</div>
                  <div className="insp-text">{getTypeLbl(selNode.node_type)}</div>
                </div>
                {isEditingNode ? (
                  <>
                    <div className="insp-section">
                      <div className="insp-sec-lbl">节点名称</div>
                      <input className="form-input" value={editLabel} onChange={(e) => setEditLabel(e.target.value)} />
                    </div>
                    <div className="insp-section">
                      <div className="insp-sec-lbl">节点描述</div>
                      <textarea
                        className="paste-area"
                        style={{ minHeight: '88px' }}
                        value={editDescription}
                        onChange={(e) => setEditDescription(e.target.value)}
                      ></textarea>
                    </div>
                    <div className="insp-section">
                      <div className="insp-sec-lbl">标签（逗号分隔）</div>
                      <input className="form-input" value={editTags} onChange={(e) => setEditTags(e.target.value)} />
                    </div>
                  </>
                ) : (
                  <>
                    <div className="insp-section">
                      <div className="insp-sec-lbl">节点描述</div>
                      <div className="insp-text">{selNode.full_description || '暂无描述'}</div>
                    </div>
                    <div className="insp-section">
                      <div className="insp-sec-lbl">标签</div>
                      <div className="gn-tags">{selNode.short_tags?.map((t: string) => <div key={t} className="gn-tag">{t}</div>)}</div>
                    </div>
                    <div className="insp-section">
                      <div className="insp-sec-lbl">图谱洞察</div>
                      {inspectorState.status === 'loading' && <div className="insight-empty">正在读取支撑链、潜在连边和图谱报告...</div>}
                      {inspectorState.status === 'error' && <div className="insight-error">读取失败：{inspectorState.error}</div>}
                      {inspectorState.status === 'ready' && inspectorData && (
                        <div className="insight-stack">
                          <div className="insight-card">
                            <div className="insight-title">支撑链</div>
                            {renderInsightItems(inspectorData.supportChains, '暂无直接支撑链')}
                          </div>
                          <div className="insight-card">
                            <div className="insight-title">潜在连边</div>
                            {renderInsightItems(inspectorData.predictedLinks, '暂无高置信潜在连边')}
                          </div>
                          <div className="insight-card">
                            <div className="insight-title">深层链条</div>
                            {renderInsightItems(inspectorData.deepChains, '暂无深层链条')}
                          </div>
                          <div className="insight-card">
                            <div className="insight-title">图谱报告</div>
                            <div className="insight-row-detail">
                              节点 {String(inspectorData.report.summary.node_count ?? 0)} · 连接 {String(inspectorData.report.summary.edge_count ?? 0)} ·
                              悬空 {inspectorData.report.dangling_nodes.length}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                    <div className="insp-section">
                      <div className="insp-sec-lbl">相关记忆</div>
                      {nodeMemoryRecallStatus === 'loading' ? (
                        <div className="insight-empty">正在检索相关记忆...</div>
                      ) : (
                        renderMemoryRecallItems(nodeMemoryRecall)
                      )}
                    </div>
                  </>
                )}
              </div>
              <div className="insp-actions">
                {isEditingNode ? (
                  <>
                    <button className="ia-btn" onClick={handleSaveNodeEdit}>保存节点</button>
                    <button className="ia-btn" onClick={handleCancelEditNode}>取消编辑</button>
                  </>
                ) : (
                  <button className="ia-btn" onClick={handleEditNode}>编辑节点</button>
                )}
                {!isEditingNode && (
                  <>
                    <button className="ia-btn" onClick={handleAddEvidence}>补充证据</button>
                    <button className="ia-btn" onClick={handleAttachFailure}>挂载失败</button>
                    <button className="ia-btn" style={{ color: 'var(--red)' }} onClick={handleDeleteNode}>删除节点</button>
                  </>
                )}
              </div>
            </>
          ) : (
            <div className="empty">
              <div className="empty-desc">选择一个节点查看详情</div>
            </div>
          )}
        </div>
      </div>
      {isAddNodeOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(17, 24, 39, 0.24)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 30,
            padding: '24px',
          }}
          onClick={() => {
            if (!isCreatingNode) setIsAddNodeOpen(false);
          }}
        >
          <div
            style={{
              width: 'min(480px, 100%)',
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: '12px',
              padding: '18px',
              boxShadow: '0 20px 40px rgba(15, 23, 42, 0.16)',
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <div style={{ fontFamily: 'var(--serif)', fontSize: '18px', marginBottom: '6px' }}>新增节点</div>
            <div style={{ fontSize: '12px', color: 'var(--text2)', marginBottom: '16px' }}>
              仅录入当前节点名称和来源说明，其他字段沿用现有工作台默认值。
            </div>
            <div style={{ display: 'grid', gap: '12px' }}>
              <div>
                <div style={{ fontSize: '12px', color: 'var(--text2)', marginBottom: '6px' }}>节点名称</div>
                <input
                  className="form-input"
                  value={newNodeName}
                  onChange={(event) => setNewNodeName(event.target.value)}
                  placeholder="例如：舆情传播节奏异常"
                />
              </div>
              <div>
                <div style={{ fontSize: '12px', color: 'var(--text2)', marginBottom: '6px' }}>来源说明</div>
                <textarea
                  className="paste-area"
                  style={{ minHeight: '100px' }}
                  value={newNodeSourceNote}
                  onChange={(event) => setNewNodeSourceNote(event.target.value)}
                  placeholder="填写该节点来自哪段文档、什么观察或什么人工判断。"
                />
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '16px' }}>
              <button className="btn" onClick={() => setIsAddNodeOpen(false)} disabled={isCreatingNode}>
                取消
              </button>
              <button
                className="btn btn-p"
                onClick={handleCreateNode}
                disabled={isCreatingNode}
                title={isCreatingNode ? '节点正在创建中' : undefined}
              >
                {isCreatingNode ? '创建中...' : '确认创建'}
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="wb-toolbar">
        <button className="wt-btn" onClick={addNode}>+ 节点</button>
        <button
          className={`wt-btn ${isEdgeMode ? 'active' : ''}`}
          onClick={handleAddEdge}
          disabled={!canEnterEdgeMode}
          title={
            !canEnterEdgeMode
              ? '至少需要 2 个节点才能建立连接'
              : isEdgeMode
              ? '点击画布中的两个不同节点，完成连接；再次点击可退出连接模式'
              : '进入连接模式后，先点源节点，再点目标节点'
          }
        >
          {isEdgeMode ? '取消连接' : '+ 连接'}
        </button>
        {isEdgeMode && <span style={{ fontSize: '11px', color: 'var(--text2)' }}>{edgeModeHint}</span>}
        <div className="wt-sep"></div>
        <button
          className="wt-btn"
          onClick={handleRecomputeRoutes}
          disabled={!hasActionableGraph || isRecomputingRoutes}
          title={!hasActionableGraph ? '至少需要 2 个节点且存在 1 条连接，才能重算路线' : undefined}
        >
          {isRecomputingRoutes ? '重算中...' : '重新计算路线'}
        </button>
        {!hasActionableGraph && <span style={{ fontSize: '11px', color: 'var(--text2)' }}>当前 {nodes.length} 节点 / {edges.length} 连接，先建立最少成链条件</span>}
        <button
          className="wt-btn ml-auto"
          onClick={handleAutoLayout}
          disabled={!canAutoLayout}
          title={!canAutoLayout ? '当前没有可布局节点' : undefined}
        >
          自动布局
        </button>
      </div>
    </div>
  );
}

export function FailuresPage({ failures, selFail, setSelFail, goto, showToast, workspaceId, onValidationSubmitted }: any) {
  const f = selFail !== null ? failures[selFail] : null;
  const [submittingValidation, setSubmittingValidation] = useState(false);
  const selectedImpactSummary = f?.impact_summary || {};
  const selectedRoutes = Array.isArray(selectedImpactSummary?.routes) ? selectedImpactSummary.routes : [];
  const selectedAttachCount = Array.isArray(selectedImpactSummary?.attach)
    ? selectedImpactSummary.attach.length
    : Array.isArray(f?.attached_targets)
    ? f.attached_targets.length
    : 0;
  const selectedImpactCount = Array.isArray(selectedImpactSummary?.impact) ? selectedImpactSummary.impact.length : 0;
  const selectedDerivedValidationId = String(
    f?.provenance?.derived_from_validation_id || f?.provenance?.validation_id || ''
  ).trim();

  const handleSubmitValidation = async () => {
    if (!f?.failure_id) {
      showToast('请先选择失败记录');
      return;
    }

    const attached = Array.isArray(f.attached_targets) ? f.attached_targets : [];
    const targetRef = attached[0] || { target_type: 'failure', target_id: f.failure_id };

    setSubmittingValidation(true);
    try {
      const validation = await createValidation({
        workspace_id: workspaceId,
        target_object: `${targetRef.target_type}:${targetRef.target_id}`,
        method: 'failure_review',
        success_signal: '验证通过后路线置信度提升',
        weakening_signal: '复现失败或影响扩大',
      });

    const validationId = validation?.validation_id || validation?.id;
    if (!validationId) {
      throw new Error('验证编号缺失');
    }

      await submitValidationResult(validationId, {
        workspace_id: workspaceId,
        outcome: 'failed',
        note: 'ui_submit_failed_validation',
        target_type: targetRef.target_type,
        target_id: targetRef.target_id,
        reporter: 'frontend_user',
      });

      await onValidationSubmitted?.();
      showToast('验证结果已提交');
    } catch (error) {
      showToast(getErrorMessage(error));
    } finally {
      setSubmittingValidation(false);
    }
  };

  return (
    <div className="fail-layout">
      <div className="fail-list-panel">
        <div className="panel-hdr">
          <div className="panel-lbl">失败记录</div>
        </div>
        <div className="rlist">
          {failures.length === 0 && (
            <div className="empty" style={{ padding: '12px' }}>
              <div className="empty-desc">当前还没有失败记录。先到图谱工作台选中节点并点击“挂载失败”。</div>
              <div style={{ marginTop: '10px' }}>
                <button className="btn" onClick={() => goto('workbench')}>前往图谱工作台</button>
              </div>
            </div>
          )}
          {failures.map((fail: any, i: number) => (
            <div key={fail.failure_id} className={`fail-item ${selFail === i ? 'sel' : ''}`} onClick={() => setSelFail(i)}>
              <div className="fi-top">
                <div className="fi-title">{fail.observed_outcome}</div>
                <div className="fi-date">{fail.expected_difference}</div>
              </div>
              <div className="fi-desc">{fail.failure_reason}</div>
              <div className="fi-foot">
                <div className="fi-attach">
                  {(Array.isArray(fail?.impact_summary?.attach) ? fail.impact_summary.attach.length : Array.isArray(fail?.attached_targets) ? fail.attached_targets.length : 0)} 个挂载对象
                </div>
                <div className="fi-impact">
                  {Array.isArray(fail?.impact_summary?.impact) ? fail.impact_summary.impact.length : 0} 处影响
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="fail-detail-panel">
        {f ? (
          <>
            <div className="hero-title">{f.observed_outcome}</div>
            <div className="text-muted mb-16">{f.expected_difference}</div>
            <div className="text-sm mb-16">{f.failure_reason}</div>
            <div className="ver-diff">
              <div className="vd-hdr">
                <div className="vd-title">影响分析</div>
              </div>
              <div className="diff-grid">
                <div className="diff-cell"><div className="dc-num inv">{selectedImpactSummary?.diff?.inv || 0}</div><div className="dc-lbl">失效节点</div></div>
                <div className="diff-cell"><div className="dc-num weak">{selectedImpactSummary?.diff?.weak || 0}</div><div className="dc-lbl">削弱连接</div></div>
              </div>
              <div className="text-sm mb-16">
                已挂载 {selectedAttachCount} 个对象 · 记录到 {selectedImpactCount} 处影响
                {f?.impact_updated_at ? ` · 影响同步 ${new Date(f.impact_updated_at).toLocaleString('zh-CN')}` : ' · 影响同步时间待后端返回'}
              </div>
              {selectedDerivedValidationId && (
                <div className="text-sm mb-16">
                  该失败记录来自验证结果派生：validation_id={selectedDerivedValidationId}
                </div>
              )}
              <div className="mb-8 text-xs">受影响路线</div>
              {selectedRoutes.map((r: any, i: number) => (
                <div key={i} className="impact-route">
                  <div className="ir-name">{r.name || r.id || `路线 ${i + 1}`}</div>
                  <div className={`ir-change ${r.to < r.from ? 'ir-down' : ''}`}>{r.from} → {r.to}</div>
                </div>
              ))}
              {selectedRoutes.length === 0 && (
                <div className="text-sm mb-16" style={{ color: 'var(--text2)' }}>
                  当前没有可展示的路线变化；如刚提交挂载或验证，请等待后端完成影响计算后再刷新。
                </div>
              )}
              <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
                <button
                  className="btn btn-p"
                  onClick={handleSubmitValidation}
                  disabled={submittingValidation}
                  title={
                    submittingValidation
                      ? '验证结果正在提交中'
                      : '当前会按 failed 提交验证结果；后端可能派生一条新的失败记录'
                  }
                >
                  {submittingValidation ? '提交中...' : '提交验证结果'}
                </button>
                <button className="btn" onClick={() => goto('routes')}>返回路线</button>
              </div>
            </div>
          </>
        ) : (
          <div className="empty">
            <div className="empty-desc">
              {failures.length > 0 ? '请选择左侧失败记录查看详情并提交验证结果。' : '还没有可提交的失败记录。'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function PackagesPage({ packages, selPkg, setSelPkg, goto, showToast, workspaceId }: any) {
  const p = selPkg !== null ? packages[selPkg] : null;
  const handleReplay = async () => {
    if (!p?.package_id) return;
    try {
      await replayPackage(p.package_id, workspaceId);
      showToast('正在回放...');
    } catch (error) {
      showToast(getErrorMessage(error));
    }
  };
  return (
    <div className="pkg-layout">
      <div className="pkg-list">
        <div className="panel-hdr"><div className="panel-lbl">知识包</div></div>
        <div className="rlist">
          {packages.length > 0 ? (
            packages.map((pkg: any, i: number) => {
              const published = ['pub', 'published'].includes(String(pkg.status || '').toLowerCase());
              return (
                <div key={pkg.package_id} className={`pkg-item ${selPkg === i ? 'sel' : ''}`} onClick={() => setSelPkg(i)}>
                  <div className="pi-top">
                    <div className="pi-title">{pkg.title}</div>
                    <div className={`pi-status ${published ? 'pi-pub' : 'pi-draft'}`}>{published ? '已发布' : '草稿'}</div>
                  </div>
                  <div className="pi-desc">{pkg.summary}</div>
                  <div className="pi-meta">{pkg.traceability_refs?.date} · {pkg.traceability_refs?.nodes || 0} 个节点</div>
                </div>
              );
            })
          ) : (
            <div className="empty">
              <div className="empty-desc">
                当前还没有知识包。请先完成“导入资料 → 候选确认入图 → 生成路线”，再回到这里发布知识包。
              </div>
              <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
                <button className="btn" onClick={() => goto('import')}>前往导入资料</button>
                <button className="btn btn-p" onClick={() => goto('routes')}>前往研究路线</button>
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="pkg-detail">
        {p ? (
          <>
            <div className="hero-title">{p.title}</div>
            <div className="text-muted mb-16">{p.summary}</div>
            <div className="pkg-section">
              <div className="pkg-sec-lbl">包含内容</div>
              <div className="included-node"><div className="in-dot" style={{ background: 'var(--blue)' }}></div><div className="in-label">结论节点</div></div>
              <div className="included-node"><div className="in-dot" style={{ background: 'var(--green)' }}></div><div className="in-label">证据节点 ({(p.traceability_refs?.nodes || 1) - 1})</div></div>
              {(p.traceability_refs?.gaps || 0) > 0 && <div className="gap-node"><div className="gap-icon">!</div><div className="gap-label">{p.traceability_refs.gaps} 个未解决缺口</div></div>}
            </div>
            <div className="replay-box">
              <div className="replay-title">推理回放</div>
              <div className="replay-meta">逐步回放该知识包的推理过程</div>
              <button className="replay-btn" onClick={handleReplay}>开始回放</button>
            </div>
          </>
        ) : (
          <div className="empty">
            <div className="empty-desc">{packages.length > 0 ? '选择一个知识包查看详情' : '暂无知识包可查看详情'}</div>
            {packages.length === 0 && (
              <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
                <button className="btn" onClick={() => goto('import')}>前往导入资料</button>
                <button className="btn btn-p" onClick={() => goto('routes')}>前往研究路线</button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function TeamPage({ goto, packages = [] }: any) {
  const publishedPackages = useMemo(
    () => (Array.isArray(packages) ? packages.filter((pkg: any) => ['pub', 'published'].includes(String(pkg.status || '').toLowerCase())) : []),
    [packages]
  );

  return (
    <div className="team-layout">
      <div className="team-header">
        <div className="team-title">团队空间</div>
        <div className="team-sub">这里展示已经发布的知识包和可共享推理链，未发布内容不会出现在团队空间。</div>
      </div>
      <div className="team-body">
        <div className="pub-grid">
          {publishedPackages.slice(0, 4).map((pkg: any) => (
            <div className="pub-card" key={pkg.package_id} onClick={() => goto('packages')}>
              <div className="pub-badge">已发布</div>
              <div className="pub-title">{pkg.title}</div>
              <div className="pub-desc">{pkg.summary}</div>
              <div className="pub-meta">{pkg.traceability_refs?.date || '未知日期'}</div>
              <div className="pub-foot">
                  <div className="gap-warn">! {pkg.traceability_refs?.gaps || 0} 个缺口</div>
                <button className="open-btn" onClick={(event) => { event.stopPropagation(); goto('packages'); }}>打开</button>
              </div>
            </div>
          ))}
          {publishedPackages.length === 0 && (
            <div className="pub-card" onClick={() => goto('packages')}>
              <div className="pub-badge">提示</div>
              <div className="pub-title">暂无已发布知识包</div>
              <div className="pub-desc">请先在“知识包”页完成发布；准备路径为：导入资料 → 候选确认入图 → 生成路线 → 发布知识包。</div>
                <div className="pub-meta">由你创建</div>
              <div className="pub-foot">
                  <div className="gap-warn">等待发布</div>
                <button className="open-btn" onClick={(event) => { event.stopPropagation(); goto('packages'); }}>前往</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
