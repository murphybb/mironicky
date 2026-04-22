import assert from 'node:assert/strict';
import test from 'node:test';

import { normalizeGraphInspectorPayloads } from './graph-inspector-helpers.ts';

test('normalize graph insights keeps support chains, predicted links, deep chains, and report sections', () => {
  const normalized = normalizeGraphInspectorPayloads({
    supportChains: { support_chains: [{ title: '证据链', path: [] }] },
    predictedLinks: { predicted_links: [{ predicted_edge_type: 'supports', confidence: 0.91 }] },
    deepChains: { deep_chains: [{ title: '深层链', chain_id: 'chain_1' }] },
    report: { summary: { duplicate_nodes: 2 }, unvalidated_assumptions: [] },
  });

  assert.equal(normalized.supportChains[0].title, '证据链');
  assert.equal(normalized.predictedLinks[0].predictedEdgeType, 'supports');
  assert.equal(normalized.deepChains[0].title, '深层链');
  assert.equal(normalized.report.summary.duplicate_nodes, 2);
});

test('normalize graph insights provides empty sections when backend omits data', () => {
  const normalized = normalizeGraphInspectorPayloads({});

  assert.deepEqual(normalized.supportChains, []);
  assert.deepEqual(normalized.predictedLinks, []);
  assert.deepEqual(normalized.deepChains, []);
  assert.deepEqual(normalized.report.summary, {});
});
