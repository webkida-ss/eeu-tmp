// Tests for extension/signin-methods.js: the sign-in provider contract.
//
// The point of the module is that panel-ui.js never learns which provider
// is configured, so these check the registry's shape as much as the two
// implementations behind it.
//
// Run with: node --test extension/test/signin-methods.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { webcrypto } from 'node:crypto';
import { JSDOM } from 'jsdom';
import vm from 'node:vm';

const extensionDir = join(dirname(fileURLToPath(import.meta.url)), '..');

function loadSignInMethods({ launchWebAuthFlow } = {}) {
  // A real origin: jsdom refuses localStorage on opaque ones, and the
  // chooser remembers accounts there.
  const dom = new JSDOM('<!doctype html><body><div id="root"></div></body>', {
    url: 'https://extension-id.chromiumapp.org/',
  });
  const sandbox = {
    console,
    document: dom.window.document,
    localStorage: dom.window.localStorage,
    URL: dom.window.URL,
    URLSearchParams: dom.window.URLSearchParams,
    crypto: webcrypto,
    // The panel supplies these globals; only the keys used here matter.
    t: (key) => key,
    chrome: {
      identity: {
        getRedirectURL: () => 'https://extension-id.chromiumapp.org/',
        launchWebAuthFlow,
      },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(readFileSync(join(extensionDir, 'signin-methods.js'), 'utf8'), sandbox, {
    filename: 'signin-methods.js',
  });
  return { sandbox, dom, root: dom.window.document.getElementById('root') };
}

function context(overrides = {}) {
  const calls = [];
  return {
    calls,
    ctx: {
      config: { provider: 'mock', google_client_id: null },
      submit: (credential) => {
        calls.push(credential);
        return Promise.resolve();
      },
      setStatus: () => {},
      ...overrides,
    },
  };
}

test('the registry answers for every provider it implements', () => {
  const { sandbox } = loadSignInMethods();

  assert.equal(sandbox.signInMethodFor('google').id, 'google');
  assert.equal(sandbox.signInMethodFor('mock').id, 'mock');
});

test('an unimplemented provider resolves to null rather than a fallback', () => {
  // Falling back to the mock would be the dangerous failure: the panel
  // must say it cannot sign in, not offer a weaker flow.
  const { sandbox } = loadSignInMethods();

  assert.equal(sandbox.signInMethodFor('apple'), null);
  assert.equal(sandbox.signInMethodFor(undefined), null);
  assert.equal(sandbox.signInMethodFor(''), null);
});

test('google renders its own button and submits the id token it obtains', async () => {
  let requestedUrl = '';
  const { sandbox, root } = loadSignInMethods({
    launchWebAuthFlow: async ({ url }) => {
      requestedUrl = url;
      return 'https://extension-id.chromiumapp.org/#id_token=header.payload.signature';
    },
  });
  const { ctx, calls } = context();
  ctx.config = { provider: 'google', google_client_id: 'client-id.apps.googleusercontent.com' };

  sandbox.signInMethodFor('google').render(root, ctx);
  root.querySelector('button').click();
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.match(requestedUrl, /response_type=id_token/);
  assert.match(requestedUrl, /prompt=select_account/);
  assert.deepEqual(calls, ['header.payload.signature']);
});

test('google without a client id reports it instead of offering a button', () => {
  const { sandbox, root } = loadSignInMethods();
  const { ctx } = context();
  ctx.config = { provider: 'google', google_client_id: null };

  sandbox.signInMethodFor('google').render(root, ctx);

  assert.equal(root.querySelector('button'), null);
  assert.match(root.textContent, /GOOGLE_OAUTH_CLIENT_ID/);
});

test('the mock opens an account chooser rather than asking for an email', () => {
  const { sandbox, root } = loadSignInMethods();
  const { ctx } = context();

  sandbox.signInMethodFor('mock').render(root, ctx);
  assert.equal(root.querySelectorAll('.signin-account').length, 0);

  root.querySelector('button').click();

  const accounts = [...root.querySelectorAll('.signin-account-email')].map((n) => n.textContent);
  assert.deepEqual(accounts, ['taro@example.com', 'alex@example.com']);
});

test('choosing an account submits a credential the mock provider accepts', async () => {
  const { sandbox, root } = loadSignInMethods();
  const { ctx, calls } = context();

  sandbox.signInMethodFor('mock').render(root, ctx);
  root.querySelector('button').click();
  root.querySelector('.signin-account').click();
  await new Promise((resolve) => setTimeout(resolve, 0));

  // The `mock:` prefix is what stops a real token being mistaken for one.
  assert.deepEqual(calls, ['mock:taro@example.com:田中 太郎']);
});

test('an account that signed in is offered first next time', async () => {
  const { sandbox, root } = loadSignInMethods();
  const { ctx } = context();

  sandbox.signInMethodFor('mock').render(root, ctx);
  root.querySelector('button').click();
  // Pick the second seeded account, so "most recent" differs from "seeded".
  root.querySelectorAll('.signin-account')[1].click();
  await new Promise((resolve) => setTimeout(resolve, 0));

  root.replaceChildren();
  sandbox.signInMethodFor('mock').render(root, ctx);
  root.querySelector('button').click();

  const first = root.querySelector('.signin-account-email').textContent;
  assert.equal(first, 'alex@example.com');
});

test('a rejected sign-in returns the chooser so another account can be tried', async () => {
  const { sandbox, root } = loadSignInMethods();
  const { ctx } = context({ submit: () => Promise.reject(new Error('nope')) });

  sandbox.signInMethodFor('mock').render(root, ctx);
  root.querySelector('button').click();
  root.querySelector('.signin-account').click();
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.ok(root.querySelectorAll('.signin-account').length > 0);
  assert.equal(root.querySelector('.signin-account').disabled, false);
});

test('the mock says what it is', () => {
  // It must never read as real Google sign-in.
  const { sandbox, root } = loadSignInMethods();
  const { ctx } = context();

  sandbox.signInMethodFor('mock').render(root, ctx);
  assert.match(root.textContent, /mock/i);

  root.querySelector('button').click();
  assert.match(root.textContent, /AUTH_PROVIDER=mock/);
});
