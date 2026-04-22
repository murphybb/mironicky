import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getGraphDeepChains,
  getGraphPredictedLinks,
  getGraphReport,
  getGraphSupportChains,
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
