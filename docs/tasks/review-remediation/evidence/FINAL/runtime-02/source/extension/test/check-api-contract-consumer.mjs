import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const extensionDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const generatedSource = readFileSync(join(extensionDir, 'generated', 'api-contract.js'), 'utf8');
const runtimeSource = readFileSync(join(extensionDir, 'api-contract-runtime.js'), 'utf8');

function contextWithGeneratedSource(source = generatedSource) {
  const context = vm.createContext({ Headers, URLSearchParams });
  vm.runInContext(source, context, { filename: 'generated/api-contract.js' });
  return context;
}

function loadRuntime(context) {
  vm.runInContext(runtimeSource, context, { filename: 'api-contract-runtime.js' });
  return context.UntangleApiContractRuntime;
}

const context = contextWithGeneratedSource();
const generated = context.UntangleApiContract;
const runtime = loadRuntime(context);
const generatedFields = Array.from(generated.operationFields);
const actualFields = [
  ...new Set(Object.values(generated.operations).flatMap((operation) => Object.keys(operation))),
].sort();

assert.equal(Object.isFrozen(generated.operationFields), true);
assert.deepEqual(generatedFields, actualFields);
assert.deepEqual(Array.from(runtime.consumedOperationFields), generatedFields);
for (const operation of Object.values(generated.operations)) {
  assert.deepEqual(Object.keys(operation).sort(), generatedFields);
}

const reads = new Set();
const operation = new Proxy(generated.operations.getAuthConfig, {
  get(target, property, receiver) {
    if (typeof property === 'string' && generatedFields.includes(property)) {
      reads.add(property);
    }
    return Reflect.get(target, property, receiver);
  },
});
runtime.methodFor(operation);
runtime.buildPath(operation);
runtime.inspectResponse(operation, {
  status: 200,
  headers: new Headers({ 'Content-Type': 'application/json; charset=utf-8' }),
});
assert.deepEqual([...reads].sort(), generatedFields);

const injectedOperations = Object.fromEntries(
  Object.entries(generated.operations).map(([operationId, record]) => [
    operationId,
    { ...record, futureGeneratedField: true },
  ]),
);
const injectedFields = [
  ...new Set(Object.values(injectedOperations).flatMap((record) => Object.keys(record))),
].sort();
const injectedContext = vm.createContext({
  Headers,
  URLSearchParams,
  UntangleApiContract: Object.freeze({
    operationFields: Object.freeze(injectedFields),
    operations: Object.freeze(injectedOperations),
  }),
});
assert.throws(
  () => loadRuntime(injectedContext),
  /Generated API operation fields do not match consumer fields/,
);
