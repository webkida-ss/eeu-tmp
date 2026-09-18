import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const extensionDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = resolve(extensionDir, '..');
const python = join(
  resolve(repositoryRoot, process.env.BACKEND_VENV || 'backend/.venv'),
  'bin/python',
);
const temporaryDirectory = mkdtempSync(join(tmpdir(), 'untangle-package-smoke-'));
const archive = join(temporaryDirectory, 'untangle.zip');
const extracted = join(temporaryDirectory, 'extension');

function run(command, args, extraEnv = {}) {
  const result = spawnSync(command, args, {
    cwd: repositoryRoot,
    env: { ...process.env, ...extraEnv },
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${command} failed (${result.signal || result.status})`);
  }
}

try {
  run(python, [
    join(extensionDir, 'scripts/build_release.py'),
    '--api-base-url',
    'https://api.example.invalid',
    '--output',
    archive,
  ]);
  run(python, ['-m', 'zipfile', '-e', archive, extracted]);
  run(process.execPath, [join(extensionDir, 'test/smoke.mjs')], {
    SMOKE_EXTENSION_DIR: extracted,
    SMOKE_STARTUP_ONLY: '1',
  });
  console.log('PACKAGED EXTENSION STARTUP PASSED');
} finally {
  rmSync(temporaryDirectory, { recursive: true, force: true });
}
