#!/usr/bin/env node
/**
 * Create (or update) an admin user.
 *
 * Usage (from server/):
 *   node scripts/create-admin.js email@example.com 'password' [First] [Last]
 */

import { hashPassword } from '../libraries/auth.js';
import { query, closePool } from '../libraries/db.js';

const [email, password, firstName = 'Admin', lastName = 'User'] = process.argv.slice(2);

if (!email || !password) {
  console.error('Usage: node scripts/create-admin.js email password [first] [last]');
  process.exit(1);
}

const hash = await hashPassword(password);
await query(
  `INSERT INTO users (email, password_hash, first_name, last_name, user_level, user_status)
   VALUES (?, ?, ?, ?, 'ADMIN', 'ACTIVE')
   ON DUPLICATE KEY UPDATE
     password_hash = VALUES(password_hash),
     first_name = VALUES(first_name),
     last_name = VALUES(last_name),
     user_level = 'ADMIN',
     user_status = 'ACTIVE'`,
  [email, hash, firstName, lastName]
);
console.log(`Admin user ready: ${email}`);
await closePool();
