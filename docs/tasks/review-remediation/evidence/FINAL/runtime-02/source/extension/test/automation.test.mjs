import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const extensionDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = join(extensionDir, '..');

test('managed Task and CI contracts prevent undeclared quality commands', () => {
  const taskfile = readFileSync(join(repositoryRoot, 'Taskfile.yaml'), 'utf8');
  const workflow = readFileSync(
    join(repositoryRoot, '.github', 'workflows', 'reading-assistant-ci.yml'),
    'utf8',
  );

  assert.match(taskfile, /setup:backend:/);
  assert.match(taskfile, /setup:extension:/);
  assert.match(taskfile, /npm ci --ignore-scripts --prefix extension/);
  assert.match(taskfile, /extension\/node_modules\/\.bin\/playwright/);
  assert.doesNotMatch(taskfile, /\bnpx\b|npm exec/);
  assert.match(taskfile, /Playwright is not installed/);

  assert.equal(workflow.match(/run: \.\/scripts\/bootstrap\.sh$/gm)?.length, 5);
  for (const task of [
    'setup:agents',
    'agents:check',
    'test:agents',
    'secrets:check',
    'deps:agents:audit',
    'setup:backend',
    'setup:extension',
    'deps:backend:check',
    'format:backend:check',
    'lint:backend',
    'api:check',
    'build:lambda',
    'test:backend:integration',
    'test:backend:coverage',
    'deps:extension:audit',
    'format:extension:check',
    'lint:extension',
    'test:extension:coverage',
    'test:extension:automation:static',
    'infra:lock:check',
    'infra:validate',
  ]) {
    assert.ok(
      workflow.includes(`./scripts/bootstrap.sh --exec task ${task}`),
      `Missing canonical CI task: ${task}`,
    );
  }

  assert.doesNotMatch(workflow, /npm (?:ci|run|audit)|python -m pytest|\.venv\/bin\/python/);
  assert.doesNotMatch(
    workflow,
    /schema_tasks\.py|build_lambda\.sh|terraform (?:fmt|init|validate)/,
  );
});
