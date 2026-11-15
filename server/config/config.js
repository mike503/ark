import dotenv from 'dotenv';
import { dirname, join, resolve } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SERVER_ROOT = join(__dirname, '..');
const REPO_ROOT = join(SERVER_ROOT, '..');

// Load repo-root .env first (compose / local), then server/.env overrides.
dotenv.config({ path: join(REPO_ROOT, '.env') });
dotenv.config({ path: join(SERVER_ROOT, '.env') });

export const dbConfig = {
  host: process.env.DATABASE_HOSTNAME || 'localhost',
  port: parseInt(process.env.DATABASE_PORT || '3306', 10),
  user: process.env.DATABASE_USER,
  password: process.env.DATABASE_PASSWORD,
  database: process.env.DATABASE_NAME,
  debug: process.env.DATABASE_DEBUG === '1' || process.env.DATABASE_DEBUG === 'true',
};

export function validateDbConfig() {
  const required = ['user', 'password', 'database'];
  const missing = required.filter((key) => !dbConfig[key]);

  if (missing.length > 0) {
    throw new Error(
      `Missing required database environment variables: ${missing.map((k) => `DATABASE_${k.toUpperCase()}`).join(', ')}`
    );
  }
}

/** Filesystem root for blobs and related on-disk archive data. */
export function resolveDataDir() {
  const raw = process.env.ARK_DATA_DIR || '/data';
  return resolve(raw);
}
