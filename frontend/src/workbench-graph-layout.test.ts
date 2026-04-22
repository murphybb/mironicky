import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clampZoom,
  computeClusteredLayout,
  distance,
  getSelectionFocus,
  loadPinnedPositions,
  savePinnedPositions,
} from './workbench-graph-layout.ts';

function overlaps(
  left: { x: number; y: number },
  right: { x: number; y: number },
  width = 250,
  height = 118
) {
  return !(
    left.x + width <= right.x ||
    right.x + width <= left.x ||
    left.y + height <= right.y ||
    right.y + height <= left.y
  );
}

test('clustered layout keeps connected nodes closer than disconnected nodes', () => {
  const layout = computeClusteredLayout(
    [
      { node_id: 'n1', node_type: 'conclusion' },
      { node_id: 'n2', node_type: 'evidence' },
      { node_id: 'n3', node_type: 'gap' },
    ],
    [{ source_node_id: 'n1', target_node_id: 'n2', edge_type: 'supports' }],
    {}
  );

  assert.ok(distance(layout.n1, layout.n2) < distance(layout.n1, layout.n3));
});

test('clustered layout prevents card overlap for dense imported graphs', () => {
  const nodes = Array.from({ length: 24 }, (_, index) => ({
    node_id: `n${index + 1}`,
    node_type: index % 3 === 0 ? 'conclusion' : index % 3 === 1 ? 'evidence' : 'assumption',
  }));
  const edges = Array.from({ length: 23 }, (_, index) => ({
    source_node_id: `n${index + 1}`,
    target_node_id: `n${index + 2}`,
    edge_type: 'supports',
  }));

  const layout = computeClusteredLayout(nodes, edges, {});

  for (let i = 0; i < nodes.length; i += 1) {
    for (let j = i + 1; j < nodes.length; j += 1) {
      assert.equal(
        overlaps(layout[nodes[i].node_id], layout[nodes[j].node_id]),
        false,
        `${nodes[i].node_id} overlaps ${nodes[j].node_id}`
      );
    }
  }
});

test('selection focus identifies directly connected nodes and edges', () => {
  const focus = getSelectionFocus('n2', [
    { source_node_id: 'n1', target_node_id: 'n2', edge_type: 'supports' },
    { source_node_id: 'n2', target_node_id: 'n3', edge_type: 'requires' },
    { source_node_id: 'n4', target_node_id: 'n5', edge_type: 'supports' },
  ]);

  assert.deepEqual([...focus.connectedNodeIds].sort(), ['n1', 'n3']);
  assert.deepEqual([...focus.connectedEdgeKeys].sort(), ['n1->n2#0', 'n2->n3#1']);
});

test('zoom is clamped to readable bounds', () => {
  assert.equal(clampZoom(0.25, 200), 0.35);
  assert.equal(clampZoom(2.5, -200), 2);
});

test('pinned positions survive save and load', () => {
  const storage = new Map<string, string>();
  const fakeStorage = {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  };

  savePinnedPositions('ws_demo', { n1: { x: 12, y: 34 } }, fakeStorage);
  assert.deepEqual(loadPinnedPositions('ws_demo', fakeStorage), { n1: { x: 12, y: 34 } });
});
