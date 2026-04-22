import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clampZoom,
  computeClusteredLayout,
  distance,
  loadPinnedPositions,
  savePinnedPositions,
} from './workbench-graph-layout.ts';

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
