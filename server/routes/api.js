import express from 'express';
import { requireApiKey } from '../libraries/api-keys.js';
import { getDataDir } from '../libraries/data-dir.js';

const router = express.Router();

router.get('/api/health', (req, res) => {
  res.json({
    status: 'ok',
    app: process.env.APP_NAME || 'ark',
    timestamp: new Date().toISOString(),
    dataDir: getDataDir(),
  });
});

/**
 * Agent-facing stub. Real batch sync lands with schema + sync protocol.
 * Auth: Bearer API key (env bootstrap or hashed api_keys row).
 */
router.get('/api/agent/whoami', requireApiKey, (req, res) => {
  res.json({
    ok: true,
    apiKey: {
      source: req.apiKey.source,
      name: req.apiKey.name,
      id: req.apiKey.id || null,
    },
  });
});

export default router;
