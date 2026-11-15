/**
 * Idempotent schema ensure on every boot.
 * Baseline comes from db/schema.sql (CREATE TABLE IF NOT EXISTS).
 * Additive column/index changes land as ensure* helpers below — no numbered migration files.
 */
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { query } from './db.js';
import { writeLog } from './common.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SCHEMA_PATH = join(__dirname, '..', 'db', 'schema.sql');

async function tableExists(table) {
  const result = await query(
    `SELECT 1 AS ok
       FROM INFORMATION_SCHEMA.TABLES
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?
      LIMIT 1`,
    [table]
  );
  return result.rows.length > 0;
}

async function columnExists(table, column) {
  const result = await query(
    `SELECT 1 AS ok
       FROM INFORMATION_SCHEMA.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND COLUMN_NAME = ?
      LIMIT 1`,
    [table, column]
  );
  return result.rows.length > 0;
}

/** Split schema.sql into executable statements (strips `--` line comments). */
function splitSqlStatements(sql) {
  const withoutBlockComments = sql.replace(/\/\*[\s\S]*?\*\//g, '');
  const lines = withoutBlockComments.split('\n').map((line) => {
    const idx = line.indexOf('--');
    return idx === -1 ? line : line.slice(0, idx);
  });
  return lines
    .join('\n')
    .split(';')
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

async function applyBaselineSchema() {
  const raw = await readFile(SCHEMA_PATH, 'utf8');
  const statements = splitSqlStatements(raw);
  for (const sql of statements) {
    await query(sql);
  }
  writeLog('INFO', `migrate: applied baseline schema (${statements.length} statements)`);
}

/**
 * Example pattern for future additive changes:
 *   if (!(await columnExists('api_keys', 'notes'))) {
 *     await query(`ALTER TABLE api_keys ADD COLUMN notes varchar(255) NULL`);
 *     writeLog('INFO', 'migrate: added api_keys.notes');
 *   }
 */
async function applyAdditiveMigrations() {
  // Intentionally empty until domain tables need ALTERs.
  // Keep helpers exported for tests / future use.
  void tableExists;
  void columnExists;
}

export async function runMigrations() {
  await applyBaselineSchema();
  await applyAdditiveMigrations();
}

export { tableExists, columnExists };
