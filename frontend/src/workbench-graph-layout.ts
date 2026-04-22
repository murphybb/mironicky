export interface LayoutNode {
  node_id: string;
  node_type?: string;
}

export interface LayoutEdge {
  source_node_id: string;
  target_node_id: string;
  edge_type?: string;
}

export interface Position {
  x: number;
  y: number;
}

type PositionMap = Record<string, Position>;
type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 2;
const PIN_KEY_PREFIX = 'mironicky.workbench.pinned.';

const CLUSTER_CENTERS: Record<string, Position> = {
  conclusion: { x: 520, y: 180 },
  evidence: { x: 220, y: 310 },
  assumption: { x: 520, y: 460 },
  conflict: { x: 820, y: 310 },
  failure: { x: 820, y: 150 },
  validation: { x: 820, y: 500 },
  gap: { x: 820, y: 500 },
};

export function distance(left: Position, right: Position): number {
  return Math.hypot(left.x - right.x, left.y - right.y);
}

export function clampZoom(currentScale: number, deltaY: number): number {
  const next = currentScale * (deltaY > 0 ? 0.88 : 1.12);
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Number(next.toFixed(3))));
}

function normalizeType(rawType: unknown): string {
  const key = String(rawType || '').toLowerCase();
  if (key === 'c') return 'conclusion';
  if (key === 'e') return 'evidence';
  if (key === 'a') return 'assumption';
  if (key === 'f') return 'failure';
  if (key === 'g') return 'gap';
  return key || 'evidence';
}

function seedByType(nodes: LayoutNode[], pinned: PositionMap): PositionMap {
  const typeCounts: Record<string, number> = {};
  const positions: PositionMap = {};
  nodes.forEach((node, index) => {
    if (pinned[node.node_id]) {
      positions[node.node_id] = { ...pinned[node.node_id] };
      return;
    }
    const type = normalizeType(node.node_type);
    const center = CLUSTER_CENTERS[type] || { x: 500, y: 320 };
    const count = typeCounts[type] || 0;
    typeCounts[type] = count + 1;
    const ring = Math.floor(count / 6) + 1;
    const angle = (count % 6) * (Math.PI / 3) + index * 0.11;
    positions[node.node_id] = {
      x: center.x + Math.cos(angle) * ring * 86,
      y: center.y + Math.sin(angle) * ring * 70,
    };
  });
  return positions;
}

export function computeClusteredLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  pinned: PositionMap
): PositionMap {
  const positions = seedByType(nodes, pinned);
  const nodeIds = new Set(nodes.map((node) => node.node_id));
  const pinnedIds = new Set(Object.keys(pinned || {}));

  for (let i = 0; i < 80; i += 1) {
    for (let a = 0; a < nodes.length; a += 1) {
      for (let b = a + 1; b < nodes.length; b += 1) {
        const left = positions[nodes[a].node_id];
        const right = positions[nodes[b].node_id];
        const dx = right.x - left.x || 1;
        const dy = right.y - left.y || 1;
        const dist = Math.max(1, Math.hypot(dx, dy));
        const push = Math.max(0, 160 - dist) * 0.02;
        if (!pinnedIds.has(nodes[a].node_id)) {
          left.x -= (dx / dist) * push;
          left.y -= (dy / dist) * push;
        }
        if (!pinnedIds.has(nodes[b].node_id)) {
          right.x += (dx / dist) * push;
          right.y += (dy / dist) * push;
        }
      }
    }

    for (const edge of edges) {
      if (!nodeIds.has(edge.source_node_id) || !nodeIds.has(edge.target_node_id)) continue;
      const source = positions[edge.source_node_id];
      const target = positions[edge.target_node_id];
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const dist = Math.max(1, Math.hypot(dx, dy));
      const pull = (dist - 230) * 0.025;
      if (!pinnedIds.has(edge.source_node_id)) {
        source.x += (dx / dist) * pull;
        source.y += (dy / dist) * pull;
      }
      if (!pinnedIds.has(edge.target_node_id)) {
        target.x -= (dx / dist) * pull;
        target.y -= (dy / dist) * pull;
      }
    }
  }

  for (const [nodeId, pinnedPosition] of Object.entries(pinned || {})) {
    if (positions[nodeId]) positions[nodeId] = { ...pinnedPosition };
  }
  return positions;
}

export function loadPinnedPositions(
  workspaceId: string,
  storage: StorageLike | undefined = globalThis.localStorage
): PositionMap {
  if (!storage) return {};
  try {
    const raw = storage.getItem(`${PIN_KEY_PREFIX}${workspaceId}`);
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== 'object') return {};
    const result: PositionMap = {};
    for (const [nodeId, value] of Object.entries(parsed as Record<string, any>)) {
      const x = Number(value?.x);
      const y = Number(value?.y);
      if (Number.isFinite(x) && Number.isFinite(y)) result[nodeId] = { x, y };
    }
    return result;
  } catch {
    return {};
  }
}

export function savePinnedPositions(
  workspaceId: string,
  positions: PositionMap,
  storage: StorageLike | undefined = globalThis.localStorage
): PositionMap {
  if (storage) {
    storage.setItem(`${PIN_KEY_PREFIX}${workspaceId}`, JSON.stringify(positions));
  }
  return positions;
}
