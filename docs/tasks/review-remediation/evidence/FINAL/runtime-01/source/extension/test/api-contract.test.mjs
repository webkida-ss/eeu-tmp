import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import vm from 'node:vm';

const extensionDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = join(extensionDir, '..');
const runtimeSource = readFileSync(join(extensionDir, 'api-contract-runtime.js'), 'utf8');
const expectedOperationIds = [
  'analyzeText',
  'closeAuthSession',
  'createAuthSession',
  'createBillingCheckout',
  'createChatReply',
  'createPagePreload',
  'getAuthConfig',
  'getBillingSummary',
  'getPagePreload',
  'getVocabularyBook',
  'openBillingPortal',
];

function loadContractRuntime() {
  const sandbox = { Headers, URLSearchParams };
  vm.createContext(sandbox);
  for (const file of ['generated/api-contract.js', 'api-contract-runtime.js']) {
    const sourcePath = join(extensionDir, file);
    vm.runInContext(readFileSync(sourcePath, 'utf8'), sandbox, {
      filename: sourcePath,
    });
  }
  return sandbox;
}

function response(status, contentType, body = {}) {
  const headers = new Headers();
  if (contentType) headers.set('CoNtEnT-TyPe', contentType);
  return {
    status,
    headers,
    jsonCalls: 0,
    textCalls: 0,
    async json() {
      this.jsonCalls += 1;
      return body;
    },
    async text() {
      this.textCalls += 1;
      return String(body);
    },
    async arrayBuffer() {
      throw new Error('unexpected binary parse');
    },
  };
}

const sandbox = loadContractRuntime();
const operations = sandbox.UntangleApiContract.operations;
const runtime = sandbox.UntangleApiContractRuntime;
const generatedCases = JSON.parse(
  readFileSync(join(repositoryRoot, 'backend', 'generated', 'openapi-contract-cases.json'), 'utf8'),
).cases;

function assertDeepFrozen(value, seen = new Set()) {
  if (!value || typeof value !== 'object' || seen.has(value)) return;
  seen.add(value);
  assert.equal(Object.isFrozen(value), true);
  if (!Array.isArray(value)) assert.equal(Object.getPrototypeOf(value), null);
  for (const child of Object.values(value)) assertDeepFrozen(child, seen);
}

test('classic generated namespace exposes only immutable consumed operations', () => {
  assert.deepEqual(Object.keys(operations), expectedOperationIds);
  assert.equal(Object.isFrozen(sandbox.UntangleApiContract), true);
  assert.equal(Object.isFrozen(sandbox.UntangleApiContract.operationFields), true);
  assert.equal(Object.isFrozen(operations), true);
  assert.deepEqual(Array.from(sandbox.UntangleApiContract.operationFields), [
    'method',
    'path',
    'queryParameters',
    'responses',
    'successStatuses',
  ]);
  assert.equal(Object.getPrototypeOf(operations), null);
  assertDeepFrozen(sandbox.UntangleApiContract);
  for (const operation of Object.values(operations)) {
    assert.equal(Object.isFrozen(operation), true);
    assert.equal(Object.getPrototypeOf(operation), null);
    assert.equal(Object.getPrototypeOf(operation.responses), null);
    assert.equal(Object.isFrozen(operation.responses), true);
    assert.equal(Object.isFrozen(operation.queryParameters), true);
    assert.equal(Object.isFrozen(operation.successStatuses), true);
  }
  const descriptor = Object.getOwnPropertyDescriptor(sandbox, 'UntangleApiContract');
  assert.equal(descriptor.writable, false);
  assert.equal(descriptor.configurable, false);
  assert.equal('processBillingWebhook' in operations, false);
});

test('runtime rejects a newly generated operation field until consumed or removed', () => {
  const injectedOperations = Object.fromEntries(
    Object.entries(operations).map(([operationId, operation]) => [
      operationId,
      { ...operation, futureGeneratedField: true },
    ]),
  );
  const operationFields = [
    ...new Set(Object.values(injectedOperations).flatMap((operation) => Object.keys(operation))),
  ].sort();
  const injectedSandbox = {
    Headers,
    URLSearchParams,
    UntangleApiContract: Object.freeze({
      operationFields: Object.freeze(operationFields),
      operations: Object.freeze(injectedOperations),
    }),
  };
  vm.createContext(injectedSandbox);
  assert.throws(
    () =>
      vm.runInContext(runtimeSource, injectedSandbox, {
        filename: join(extensionDir, 'api-contract-runtime.js'),
      }),
    /Generated API operation fields do not match consumer fields/,
  );
});

test('every consumed path and method agrees with generated contract examples', () => {
  for (const operationId of expectedOperationIds) {
    const cases = generatedCases.filter((entry) => entry.operationId === operationId);
    assert.ok(cases.length > 0, `${operationId} has no generated examples`);
    for (const contractCase of cases) {
      assert.equal(operations[operationId].method, contractCase.method);
      assert.equal(contractCase.path.split('?', 1)[0], operations[operationId].path);
    }
  }
});

test('declared successes, including 202, parse from the generated success set', async () => {
  for (const [operationId, operation] of Object.entries(operations)) {
    for (const status of operation.successStatuses) {
      const mediaType = operation.responses[status][0];
      const fixture =
        generatedCases.find(
          (entry) =>
            entry.operationId === operationId &&
            String(entry.expectedStatus) === status &&
            entry.responseExample !== undefined,
        )?.responseExample ?? {};
      const actual = response(Number(status), `${mediaType}; Charset=UTF-8`, fixture);
      const parsed = await runtime.consumeResponse(
        operation,
        actual,
        async () => 'not used',
        'fallback',
      );
      assert.deepEqual(parsed, fixture);
    }
  }
  assert.deepEqual(Array.from(operations.createPagePreload.successStatuses), ['202']);
});

test('declared non-success uses normal localized error parsing', async () => {
  const operation = operations.createPagePreload;
  const actual = response(409, 'Application/JSON; charset=utf-8', { detail: 'duplicate' });
  let reads = 0;
  await assert.rejects(
    runtime.consumeResponse(
      operation,
      actual,
      async (received, fallback) => {
        reads += 1;
        assert.equal(received, actual);
        assert.equal(fallback, 'localized fallback');
        return 'localized conflict';
      },
      'localized fallback',
    ),
    /localized conflict/,
  );
  assert.equal(reads, 1);
});

test('undeclared success and error statuses fail closed without reading bodies', () => {
  for (const status of [299, 599]) {
    const actual = response(status, 'application/json', { secret: 'must-not-leak' });
    assert.throws(
      () => runtime.inspectResponse(operations.analyzeText, actual),
      (error) => {
        assert.equal(error.name, 'ApiContractViolationError');
        assert.equal(error.reason, `undeclared-status-${status}`);
        assert.doesNotMatch(error.message, /must-not-leak/);
        assert.equal(error.retryable, false);
        return true;
      },
    );
    assert.equal(actual.jsonCalls, 0);
  }
});

test('Content-Type is required, case-insensitive, and ignores parameters', () => {
  assert.equal(
    runtime.inspectResponse(
      operations.getAuthConfig,
      response(200, 'Application/JSON; CHARSET="utf-8"'),
    ).mediaType,
    'application/json',
  );
  assert.throws(
    () => runtime.inspectResponse(operations.getAuthConfig, response(200)),
    (error) => error.reason === 'missing-content-type-status-200',
  );
  assert.throws(
    () =>
      runtime.inspectResponse(operations.getAuthConfig, response(200, 'text/plain; charset=utf-8')),
    (error) => error.reason === 'undeclared-media-status-200',
  );
});

test('Content-Type parser rejects coalesced, malformed, duplicate, and control values', () => {
  const valid = [
    'application/json',
    ' Application/JSON ; charset=utf-8 ',
    'application/json; charset="utf-8"; profile="a,b"',
    'application/json; charset=utf-8; charset=utf-8',
  ];
  for (const contentType of valid) {
    assert.equal(runtime.parseContentType(contentType), 'application/json', contentType);
  }

  const invalid = [
    'application/json, text/plain',
    'application/json; charset=utf-8, application/json',
    'application',
    '/json',
    'application/json/',
    'application/json; charset',
    'application/json; charset=',
    'application/json; charset="unterminated',
    'application/json; charset="utf-8" trailing',
    'application/json; charset=utf-8; charset=latin1',
    'application/json; note="😀"',
    'application/json\r\nX-Secret: value',
    'application/json;\tcharset=utf-8',
  ];
  for (const contentType of invalid) {
    assert.equal(runtime.parseContentType(contentType), null, contentType);
    assert.throws(
      () =>
        runtime.inspectResponse(operations.getAuthConfig, {
          status: 200,
          headers: { 'Content-Type': contentType },
        }),
      (error) => error.reason === 'malformed-content-type-status-200',
      contentType,
    );
  }
  const duplicatedHeaders = new Headers();
  duplicatedHeaders.append('Content-Type', 'application/json');
  duplicatedHeaders.append('Content-Type', 'text/plain');
  assert.throws(
    () =>
      runtime.inspectResponse(operations.getAuthConfig, {
        status: 200,
        headers: duplicatedHeaders,
      }),
    (error) => error.reason === 'malformed-content-type-status-200',
  );
});

test('generated successStatuses alone control success behavior', async () => {
  const base = operations.getAuthConfig;
  const successAsError = {
    ...base,
    successStatuses: [],
  };
  await assert.rejects(
    runtime.consumeResponse(
      successAsError,
      response(200, 'application/json'),
      async () => 'generated set rejected status',
      'fallback',
    ),
    /generated set rejected status/,
  );

  const errorAsSuccess = {
    ...operations.createPagePreload,
    successStatuses: ['202', '409'],
  };
  assert.deepEqual(
    await runtime.consumeResponse(
      errorAsSuccess,
      response(409, 'application/json', { accepted: true }),
      async () => 'not used',
      'fallback',
    ),
    { accepted: true },
  );
});

test('query construction starts from generated path and encodes values safely', () => {
  assert.equal(
    runtime.buildPath(operations.getPagePreload, {
      page_url: 'https://example.com/a path/?x=1&y=two',
    }),
    '/pages/preload?page_url=https%3A%2F%2Fexample.com%2Fa+path%2F%3Fx%3D1%26y%3Dtwo',
  );
  assert.throws(
    () => runtime.buildPath(operations.getPagePreload),
    (error) => error.reason === 'missing-required-query-parameter',
  );
  assert.throws(
    () =>
      runtime.buildPath(operations.getPagePreload, {
        page_url: 'https://example.test',
        unexpected: 'value',
      }),
    (error) => error.reason === 'unknown-query-parameter',
  );
  assert.equal(runtime.buildPath(operations.getAuthConfig), '/auth/config');
});

test('no-content declarations return without parsing a body', async () => {
  const operation = {
    path: '/fixture',
    method: 'DELETE',
    queryParameters: [],
    responses: { 204: [] },
    successStatuses: ['204'],
  };
  const actual = response(204);
  assert.equal(
    await runtime.consumeResponse(operation, actual, async () => 'not used', 'fallback'),
    undefined,
  );
  assert.equal(actual.jsonCalls, 0);
  assert.equal(actual.textCalls, 0);
});

test('prototype pollution cannot add operations, statuses, or query values', () => {
  vm.runInContext(
    `
    Object.prototype.pollutedOperation = { method: "GET" };
    Object.prototype["299"] = ["application/json"];
    Object.prototype.page_url = "https://attacker.invalid/private";
  `,
    sandbox,
  );
  try {
    assert.equal(operations.pollutedOperation, undefined);
    assert.throws(
      () => runtime.inspectResponse(operations.getAuthConfig, response(299, 'application/json')),
      (error) => error.reason === 'undeclared-status-299',
    );
    const inheritedQuery = vm.runInContext('({})', sandbox);
    assert.throws(
      () => runtime.buildPath(operations.getPagePreload, inheritedQuery),
      (error) => error.reason === 'missing-required-query-parameter',
    );
  } finally {
    vm.runInContext(
      `
      delete Object.prototype.pollutedOperation;
      delete Object.prototype["299"];
      delete Object.prototype.page_url;
    `,
      sandbox,
    );
  }
});

test('post-load intrinsic tampering cannot bypass contract trust decisions', () => {
  const tamperedSandbox = loadContractRuntime();
  const tamperedRuntime = tamperedSandbox.UntangleApiContractRuntime;
  const tamperedOperations = tamperedSandbox.UntangleApiContract.operations;
  vm.runInContext(
    `
    Array.from = () => ["x"];
    Array.isArray = () => true;
    Array.prototype.every = () => true;
    Array.prototype.find = () => ["evil", {}];
    Array.prototype.includes = () => true;
    Array.prototype.join = () => "poison";
    Array.prototype.map = () => ["application/json"];
    Array.prototype.some = () => false;
    Array.prototype.sort = () => [];
    String.prototype.codePointAt = () => 0;
    String.prototype.endsWith = () => true;
    String.prototype.slice = () => "application/json";
    String.prototype.split = () => ["application/json"];
    String.prototype.startsWith = () => true;
    String.prototype.toLowerCase = () => "application/json";
    String.prototype.trim = () => "application/json";
    String = () => "poison";
    RegExp.prototype.test = () => true;
    Object.create = () => ({ inherited: true });
    Object.entries = () => [["evilOperation", {}]];
    Object.freeze = (value) => value;
    Object.keys = () => ["299"];
    Object.prototype.hasOwnProperty = () => true;
    Function.prototype.call = () => { throw new Error("tampered call"); };
    Function.prototype.bind = () => { throw new Error("tampered bind"); };
    Headers = function PoisonedHeaders() {};
    URLSearchParams = function PoisonedSearchParams() {};
    Number = () => 200;
    Number.isInteger = () => true;
    Reflect = { get: () => "poison", ownKeys: () => ["299"] };
  `,
    tamperedSandbox,
  );

  assert.equal(
    tamperedRuntime.inspectResponse(
      tamperedOperations.getAuthConfig,
      response(200, 'Application/JSON; charset=utf-8'),
    ).success,
    true,
  );
  assert.throws(
    () =>
      tamperedRuntime.inspectResponse(
        tamperedOperations.getAuthConfig,
        response(299, 'application/json'),
      ),
    (error) => error.reason === 'undeclared-status-299',
  );
  assert.throws(
    () =>
      tamperedRuntime.inspectResponse(
        tamperedOperations.getAuthConfig,
        response(200, 'text/plain'),
      ),
    (error) => error.reason === 'undeclared-media-status-200',
  );
  assert.throws(
    () =>
      tamperedRuntime.buildPath(tamperedOperations.getPagePreload, {
        page_url: 'https://example.test',
        attacker: 'value',
      }),
    (error) => error.reason === 'unknown-query-parameter',
  );
  assert.equal(tamperedRuntime.parseContentType('application/json, text/plain'), null);
});

test('background call sites contain no duplicated consumed paths or HTTP methods', () => {
  const source = readFileSync(join(extensionDir, 'background.js'), 'utf8');
  for (const [operationId, operation] of Object.entries(operations)) {
    assert.match(source, new RegExp(`API_OPERATIONS\\.${operationId}\\b`));
    assert.equal(source.includes(`'${operation.path}'`), false);
    assert.equal(source.includes(`"${operation.path}"`), false);
    assert.equal(source.includes(`\`${operation.path}`), false);
  }
  assert.doesNotMatch(
    source,
    /\bmethod\s*:\s*['"](?:GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD|TRACE)['"]/,
  );
});
