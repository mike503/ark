import { randomBytes } from 'crypto';
import { getOption, setOption } from './options.js';
import { writeLog } from './common.js';

const OPTION_NAME = 'session_secret';

/**
 * Load session signing secret from options (generic key/value store).
 * If missing, generate one and persist it so restarts keep the same secret.
 */
export async function resolveSessionSecret() {
  const existing = await getOption(OPTION_NAME);
  if (existing) {
    return existing;
  }

  const generated = randomBytes(48).toString('base64url');
  await setOption(OPTION_NAME, generated);

  // Another process may have won a first-boot race — prefer whatever is stored.
  const stored = await getOption(OPTION_NAME, generated);
  writeLog('INFO', 'Generated and stored options.session_secret');
  return stored;
}
