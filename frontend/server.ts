import express from 'express';
import { createServer as createViteServer } from 'vite';
import path from 'path';

const DEFAULT_PORT = 4174;
const DEFAULT_API_BASE = 'http://127.0.0.1:1995';
const HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailers',
  'transfer-encoding',
  'upgrade',
]);

function getApiBase() {
  return (process.env.RESEARCH_API_BASE || DEFAULT_API_BASE).replace(/\/+$/, '');
}

function copyRequestHeaders(req: express.Request) {
  const headers: Record<string, string> = {};
  Object.entries(req.headers).forEach(([key, value]) => {
    const lower = key.toLowerCase();
    if (!value || HOP_BY_HOP_HEADERS.has(lower) || lower === 'host' || lower === 'content-length') return;
    if (Array.isArray(value)) {
      headers[key] = value.join(', ');
      return;
    }
    headers[key] = value;
  });
  return headers;
}

async function proxyRequest(req: express.Request, res: express.Response) {
  const apiBase = getApiBase();
  const targetUrl = `${apiBase}${req.originalUrl}`;
  const method = req.method.toUpperCase();
  const headers = copyRequestHeaders(req);
  const init: RequestInit = {
    method,
    headers,
  };

  if (!['GET', 'HEAD'].includes(method)) {
    if (Buffer.isBuffer(req.body)) {
      init.body = req.body;
    } else if (typeof req.body === 'string') {
      init.body = req.body;
    } else if (req.body && Object.keys(req.body).length > 0) {
      init.body = JSON.stringify(req.body);
      headers['content-type'] = headers['content-type'] || 'application/json';
    }
  }

  const upstream = await fetch(targetUrl, init);
  res.status(upstream.status);

  upstream.headers.forEach((value, key) => {
    if (HOP_BY_HOP_HEADERS.has(key.toLowerCase())) return;
    res.setHeader(key, value);
  });

  const body = Buffer.from(await upstream.arrayBuffer());
  res.send(body);
}

async function startServer() {
  const app = express();
  const port = Number(process.env.PORT || DEFAULT_PORT);
  const isProd = process.env.NODE_ENV === 'production' || process.argv.includes('--prod');

  app.use(express.json({ limit: '50mb' }));
  app.use(express.urlencoded({ extended: true, limit: '50mb' }));

  app.get('/health', async (_req, res) => {
    const apiBase = getApiBase();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);

    try {
      const healthResponse = await fetch(`${apiBase}/health`, { signal: controller.signal });
      const healthPayload = await healthResponse
        .json()
        .catch(async () => ({ raw: await healthResponse.text().catch(() => '') }));

      let reachableViaOpenapi = false;
      if (!healthResponse.ok && healthResponse.status === 404) {
        try {
          const openapiResponse = await fetch(`${apiBase}/openapi.json`, { signal: controller.signal });
          reachableViaOpenapi = openapiResponse.ok;
        } catch {
          reachableViaOpenapi = false;
        }
      }

      clearTimeout(timer);
      const backendHealthy = healthResponse.ok || reachableViaOpenapi;
      res.status(backendHealthy ? 200 : 503).json({
        status: backendHealthy ? 'ok' : 'degraded',
        frontend: { status: 'ok' },
        backend: {
          status_code: healthResponse.status,
          api_base: apiBase,
          payload: healthPayload,
          health_endpoint_missing: !healthResponse.ok && healthResponse.status === 404,
          fallback_openapi_ok: reachableViaOpenapi,
        },
      });
    } catch (error) {
      clearTimeout(timer);
      const message = error instanceof Error ? error.message : 'health probe failed';
      res.status(503).json({
        status: 'degraded',
        frontend: { status: 'ok' },
        backend: {
          status_code: 0,
          api_base: apiBase,
          error: message,
        },
      });
    }
  });

  app.get('/docs', (_req, res) => {
    res.redirect(`${getApiBase()}/docs`);
  });

  app.use('/api/v1/research', async (req, res) => {
    try {
      await proxyRequest(req, res);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'proxy request failed';
      res.status(502).json({
        error_code: 'research.proxy_error',
        message,
        details: { path: req.originalUrl },
      });
    }
  });

  if (!isProd) {
    const vite = await createViteServer({
      server: { middlewareMode: true, hmr: false },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (_req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(port, '0.0.0.0', () => {
    console.log(`Frontend server listening on http://127.0.0.1:${port}`);
    console.log(`Proxying research API to ${getApiBase()}`);
    console.log(`Server mode: ${isProd ? 'production' : 'development'}`);
  });
}

startServer();
