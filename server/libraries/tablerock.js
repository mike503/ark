/**
 * App bootstrap for Tablerock — configure shared packages once at import time.
 */
import { dbConfig, validateDbConfig } from '../config/config.js';
import { writeLog } from '@tablerock/standard/common';
import { configureDb, query } from '@tablerock/standard/db';
import { configureOptions } from '@tablerock/standard/options';
import { configureAuth } from '@tablerock/standard/auth';
import { configureMiddleware } from '@tablerock/standard/middleware';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');

validateDbConfig();
configureDb({ ...dbConfig, writeLog });
configureOptions({ query });
configureAuth({
  query,
  writeLog,
  includeTimezone: false,
  getAutheliaSecret: async () => process.env.AUTHELIA_HEADER || null,
});
configureMiddleware({
  viewsRoot: join(ROOT, 'views'),
  writeLog,
  appName: process.env.APP_NAME || 'ark',
});

export { writeLog, query, ROOT };
