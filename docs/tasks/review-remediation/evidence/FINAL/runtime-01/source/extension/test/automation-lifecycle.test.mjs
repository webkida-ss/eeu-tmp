import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const extensionDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = join(extensionDir, '..');
const smokeScript = join(extensionDir, 'test', 'smoke.mjs');
const artifactRoot = join(repositoryRoot, 'output', 'playwright');

function artifactRuns() {
  if (!existsSync(artifactRoot)) return new Set();
  return new Set(
    readdirSync(artifactRoot)
      .filter((name) => name.startsWith('smoke-'))
      .map((name) => join(artifactRoot, name)),
  );
}

function profileRuns() {
  return new Set(
    readdirSync(tmpdir())
      .filter((name) => name.startsWith('era-smoke-'))
      .map((name) => join(tmpdir(), name)),
  );
}

function difference(after, before) {
  return [...after].filter((entry) => !before.has(entry));
}

function removeOwnedArtifacts(paths) {
  for (const path of paths) rmSync(path, { recursive: true, force: true });
}

function startSmoke(extraEnv = {}) {
  const child = spawn(process.execPath, [smokeScript], {
    cwd: extensionDir,
    env: { ...process.env, ...extraEnv },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stdout = '';
  let stderr = '';
  child.stdout.on('data', (chunk) => {
    stdout += chunk;
  });
  child.stderr.on('data', (chunk) => {
    stderr += chunk;
  });
  const result = new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', (code, signal) => resolve({ code, signal, stdout, stderr }));
  });
  return { child, result, stdout: () => stdout };
}

async function waitForOutput(run, text, timeoutMs = 20_000) {
  const startedAt = Date.now();
  while (!run.stdout().includes(text)) {
    if (Date.now() - startedAt > timeoutMs) {
      throw new Error(`Timed out waiting for smoke output: ${text}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
}

test(
  'two smoke processes run concurrently without artifact collisions',
  { timeout: 60_000 },
  async () => {
    const artifactsBefore = artifactRuns();
    const profilesBefore = profileRuns();
    const first = startSmoke();
    const second = startSmoke();
    const [firstResult, secondResult] = await Promise.all([first.result, second.result]);

    assert.equal(firstResult.code, 0, firstResult.stderr);
    assert.equal(secondResult.code, 0, secondResult.stderr);
    assert.match(firstResult.stdout, /SMOKE TEST PASSED/);
    assert.match(secondResult.stdout, /SMOKE TEST PASSED/);
    assert.deepEqual(artifactRuns(), artifactsBefore);
    assert.deepEqual(profileRuns(), profilesBefore);
  },
);

test(
  'artifact write failure preserves primary failure and cleanup',
  { timeout: 40_000 },
  async () => {
    const artifactsBefore = artifactRuns();
    const profilesBefore = profileRuns();
    const run = startSmoke({
      SMOKE_TEST_FORCE_FAILURE: '1',
      SMOKE_TEST_FORCE_ARTIFACT_WRITE_FAILURE: '1',
    });
    const result = await run.result;
    const ownedArtifacts = difference(artifactRuns(), artifactsBefore);

    try {
      assert.equal(result.code, 1);
      assert.equal(ownedArtifacts.length, 1);
      const report = JSON.parse(readFileSync(join(ownedArtifacts[0], 'errors.json'), 'utf8'));
      assert.match(report.failure, /forced failure for artifact verification/);
      assert.ok(report.artifactErrors.some((entry) => entry.includes('forced artifact write')));
      assert.match(result.stderr, /Artifact diagnostic: forced artifact write/);
      assert.deepEqual(profileRuns(), profilesBefore);
    } finally {
      removeOwnedArtifacts(ownedArtifacts);
    }
  },
);

test('SIGTERM preserves signal status, artifacts, and cleanup', { timeout: 40_000 }, async () => {
  const artifactsBefore = artifactRuns();
  const profilesBefore = profileRuns();
  const run = startSmoke();
  await waitForOutput(run, 'content script PING');
  run.child.kill('SIGTERM');
  const result = await run.result;
  const ownedArtifacts = difference(artifactRuns(), artifactsBefore);

  try {
    assert.equal(result.code, 143);
    assert.equal(result.signal, null);
    assert.equal(ownedArtifacts.length, 1);
    const files = readdirSync(ownedArtifacts[0]);
    assert.ok(files.some((name) => /^page-\d+\.png$/.test(name)));
    assert.ok(files.includes('trace.zip'));
    const report = JSON.parse(readFileSync(join(ownedArtifacts[0], 'errors.json'), 'utf8'));
    assert.match(report.failure, /Smoke test interrupted by SIGTERM/);
    assert.deepEqual(profileRuns(), profilesBefore);
  } finally {
    removeOwnedArtifacts(ownedArtifacts);
  }
});
