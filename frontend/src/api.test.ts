import assert from 'node:assert/strict';
import test from 'node:test';

import {
  confirmCandidates,
  controlHypothesisPool,
  extractSource,
  getGraph,
  getGraphDeepChains,
  getGraphPredictedLinks,
  getGraphReport,
  getGraphSupportChains,
  importSource,
  generateLiteratureFrontierHypothesis,
  listWorkspaces,
  patchHypothesisCandidate,
} from './api.ts';

async function withMockFetch(handler: (url: string, init?: RequestInit) => unknown, run: () => Promise<void>) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    const payload = handler(String(url), init);
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }) as typeof fetch;
  try {
    await run();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

test('graph insight api wrappers call the dedicated backend endpoints', async () => {
  const calls: Array<{ url: string; body: any; method: string }> = [];

  await withMockFetch(
    (url, init) => {
      calls.push({
        url,
        method: String(init?.method || 'GET'),
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      if (url.endsWith('/report')) return { summary: {} };
      if (url.endsWith('/support-chains')) return { support_chains: [] };
      if (url.endsWith('/predicted-links')) return { predicted_links: [] };
      return { deep_chains: [] };
    },
    async () => {
      await getGraphSupportChains('ws_demo', 'node_a', 3);
      await getGraphPredictedLinks('ws_demo', 'node_a', 4);
      await getGraphDeepChains('ws_demo', 'node_a', 2);
      await getGraphReport('ws_demo');
    }
  );

  assert.deepEqual(
    calls.map((call) => [call.method, call.url]),
    [
      ['POST', '/api/v1/research/graph/ws_demo/support-chains'],
      ['POST', '/api/v1/research/graph/ws_demo/predicted-links'],
      ['POST', '/api/v1/research/graph/ws_demo/deep-chains'],
      ['GET', '/api/v1/research/graph/ws_demo/report'],
    ]
  );
  assert.equal(calls[0].body.conclusion_node_id, 'node_a');
  assert.equal(calls[1].body.node_id, 'node_a');
  assert.equal(calls[2].body.node_id, 'node_a');
});

test('pdf argument graph flow wrappers call import, extract, confirm, and graph endpoints', async () => {
  const calls: Array<{ url: string; body: any; method: string }> = [];

  await withMockFetch(
    (url, init) => {
      calls.push({
        url,
        method: String(init?.method || 'GET'),
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      if (url.endsWith('/sources/import')) return { source_id: 'src_pdf' };
      if (url.endsWith('/sources/src_pdf/extract')) {
        return {
          job_id: 'job_pdf',
          job_type: 'source_extract',
          status: 'queued',
          workspace_id: 'ws_pdf',
        };
      }
      if (url.endsWith('/candidates/confirm')) return { updated_ids: ['cand_1'], status: 'confirmed' };
      if (url.endsWith('/graph/ws_pdf')) {
        return {
          workspace_id: 'ws_pdf',
          nodes: [{ node_id: 'node_1', short_label: 'Claim', node_type: 'conclusion' }],
          edges: [],
        };
      }
      return {};
    },
    async () => {
      await importSource({
        workspace_id: 'ws_pdf',
        source_type: 'paper',
        source_input_mode: 'local_file',
        title: 'paper.pdf',
        local_file: {
          file_name: 'paper.pdf',
          file_content_base64: 'JVBERi0=',
          mime_type: 'application/pdf',
        },
      });
      await extractSource('src_pdf', 'ws_pdf');
      await confirmCandidates('ws_pdf', ['cand_1']);
      const graph = await getGraph('ws_pdf');
      assert.equal(graph.nodes[0].x, 120);
      assert.equal(graph.nodes[0].y, 80);
    }
  );

  assert.deepEqual(
    calls.map((call) => [call.method, call.url]),
    [
      ['POST', '/api/v1/research/sources/import'],
      ['POST', '/api/v1/research/sources/src_pdf/extract'],
      ['POST', '/api/v1/research/candidates/confirm'],
      ['GET', '/api/v1/research/graph/ws_pdf'],
    ]
  );
  assert.equal(calls[0].body.source_input_mode, 'local_file');
  assert.equal(calls[1].body.async_mode, true);
  assert.deepEqual(calls[2].body.candidate_ids, ['cand_1']);
});

test('workspace list wrapper calls the backend workspace index', async () => {
  const calls: string[] = [];

  await withMockFetch(
    (url) => {
      calls.push(url);
      return {
        items: [
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
        total: 1,
      };
    },
    async () => {
      const result = await listWorkspaces();
      assert.equal(result.items[0].workspace_id, 'ws_pdf_real');
      assert.equal(result.items[0].node_count, 24);
    }
  );

  assert.deepEqual(calls, ['/api/v1/research/workspaces']);
});

test('literature frontier wrapper uses hypothesis generate endpoint with source ids', async () => {
  const calls: Array<{ url: string; body: any; method: string }> = [];

  await withMockFetch(
    (url, init) => {
      calls.push({
        url,
        method: String(init?.method || 'GET'),
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      return {
        job_id: 'job_frontier',
        job_type: 'hypothesis_generate',
        status: 'queued',
        workspace_id: 'ws_frontier',
      };
    },
    async () => {
      const accepted = await generateLiteratureFrontierHypothesis({
        workspace_id: 'ws_frontier',
        source_ids: ['src_1'],
        research_goal: 'Find a stronger causal explanation.',
        frontier_size: 3,
      });
      assert.equal(accepted.job_id, 'job_frontier');
    }
  );

  assert.deepEqual(
    calls.map((call) => [call.method, call.url]),
    [['POST', '/api/v1/research/hypotheses/generate']]
  );
  assert.equal(calls[0].body.mode, 'literature_frontier');
  assert.deepEqual(calls[0].body.source_ids, ['src_1']);
  assert.equal(calls[0].body.async_mode, true);
});

test('hypothesis pool control and candidate patch wrappers call backend endpoints', async () => {
  const calls: Array<{ url: string; body: any; method: string }> = [];

  await withMockFetch(
    (url, init) => {
      calls.push({
        url,
        method: String(init?.method || 'GET'),
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      return { ok: true };
    },
    async () => {
      await controlHypothesisPool('pool_1', {
        workspace_id: 'ws_frontier',
        action: 'pause',
      });
      await patchHypothesisCandidate('candidate_1', {
        workspace_id: 'ws_frontier',
        reasoning_chain: { hypothesis_level_conclusion: 'new conclusion' },
        reset_review_state: true,
      });
    }
  );

  assert.deepEqual(
    calls.map((call) => [call.method, call.url]),
    [
      ['POST', '/api/v1/research/hypotheses/pools/pool_1/control'],
      ['PATCH', '/api/v1/research/hypotheses/candidates/candidate_1'],
    ]
  );
  assert.equal(calls[0].body.action, 'pause');
  assert.equal(calls[1].body.reasoning_chain.hypothesis_level_conclusion, 'new conclusion');
});
