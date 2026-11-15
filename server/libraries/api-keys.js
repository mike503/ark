import bcrypt from 'bcrypt';
import { query } from './db.js';
import { writeLog } from './common.js';

/**
 * Agent auth: Authorization Bearer against hashed api_keys rows,
 * with optional ARK_API_KEY env bootstrap for early smoke tests.
 */
export async function requireApiKey(req, res, next) {
  try {
    const header = String(req.headers.authorization || '');
    const match = header.match(/^Bearer\s+(.+)$/i);
    const key = (match?.[1] || '').trim();
    if (!key) {
      return res.status(401).json({ error: 'Authentication required' });
    }

    const envKey = (process.env.ARK_API_KEY || '').trim();
    if (envKey && key === envKey) {
      req.apiKey = { source: 'env', name: 'env' };
      return next();
    }

    const rows = await query(
      `SELECT api_key_id, name, key_hash
         FROM api_keys
        WHERE enabled = 1`
    );

    for (const row of rows) {
      if (await bcrypt.compare(key, row.key_hash)) {
        req.apiKey = { source: 'db', id: row.api_key_id, name: row.name };
        void query(
          'UPDATE api_keys SET last_used_at = UTC_TIMESTAMP() WHERE api_key_id = ?',
          [row.api_key_id]
        ).catch((err) => writeLog('WARN', 'api_keys last_used update failed:', err.message));
        return next();
      }
    }

    return res.status(401).json({ error: 'Authentication required' });
  } catch (err) {
    writeLog('ERROR', 'API key auth failed:', err);
    return res.status(503).json({ error: 'Auth unavailable' });
  }
}

export async function createApiKey({ name, plaintext }) {
  const keyHash = await bcrypt.hash(plaintext, 12);
  const result = await query(
    `INSERT INTO api_keys (name, key_hash, enabled)
     VALUES (?, ?, 1)`,
    [name, keyHash]
  );
  return { apiKeyId: result.insertId, name };
}
