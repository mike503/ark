import { mkdir } from 'fs/promises';
import { join } from 'path';
import { resolveDataDir } from '../config/config.js';

export function getDataDir() {
  return resolveDataDir();
}

export function blobsDir() {
  return join(getDataDir(), 'blobs');
}

/** Ensure ARK_DATA_DIR and blobs/ exist (container or host bind-mount). */
export async function ensureDataDirs() {
  const root = getDataDir();
  await mkdir(join(root, 'blobs'), { recursive: true });
  return root;
}
