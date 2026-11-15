#!/usr/bin/env node
/**
 * Create a hashed agent API key. Prints the plaintext once — store it in the agent config.
 *
 * Usage (from server/):
 *   node scripts/create-api-key.js 'laptop' [optional-plaintext]
 *
 * If plaintext is omitted, a random key is generated.
 */

import { randomBytes } from 'crypto';
import { createApiKey } from '../libraries/api-keys.js';
import { closePool } from '../libraries/db.js';

const [name, provided] = process.argv.slice(2);

if (!name) {
  console.error("Usage: node scripts/create-api-key.js 'name' [plaintext]");
  process.exit(1);
}

const plaintext = provided || randomBytes(32).toString('base64url');
const { apiKeyId } = await createApiKey({ name, plaintext });

console.log(`Created api_keys row id=${apiKeyId} name=${name}`);
console.log('Store this key now (not shown again):');
console.log(plaintext);

await closePool();
