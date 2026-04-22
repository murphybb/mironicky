import assert from 'node:assert/strict';
import test from 'node:test';

import { chooseWorkspaceToRestore } from './workspace-restore-helpers.ts';

const emptySnapshot = {
  sourceCount: 0,
  nodeCount: 0,
  edgeCount: 0,
  routeCount: 0,
  candidateCount: 0,
};

test('restores the newest non-empty workspace when default workspace is empty', () => {
  const restored = chooseWorkspaceToRestore(
    'ws-default-1',
    emptySnapshot,
    [
      {
        workspace_id: 'ws_pdf_real',
        source_count: 1,
        node_count: 24,
        edge_count: 23,
        route_count: 0,
        candidate_count: 0,
        updated_at: '2026-04-22T10:00:00',
      },
    ],
    'ws-default-1'
  );

  assert.equal(restored, 'ws_pdf_real');
});

test('does not override an explicit custom workspace even when it is empty', () => {
  const restored = chooseWorkspaceToRestore(
    'ws_user_named',
    emptySnapshot,
    [
      {
        workspace_id: 'ws_pdf_real',
        source_count: 1,
        node_count: 24,
        edge_count: 23,
        route_count: 0,
        candidate_count: 0,
        updated_at: '2026-04-22T10:00:00',
      },
    ],
    'ws-default-1'
  );

  assert.equal(restored, null);
});

test('does not restore when the current default workspace already has data', () => {
  const restored = chooseWorkspaceToRestore(
    'ws-default-1',
    { ...emptySnapshot, nodeCount: 1 },
    [
      {
        workspace_id: 'ws_pdf_real',
        source_count: 1,
        node_count: 24,
        edge_count: 23,
        route_count: 0,
        candidate_count: 0,
        updated_at: '2026-04-22T10:00:00',
      },
    ],
    'ws-default-1'
  );

  assert.equal(restored, null);
});
