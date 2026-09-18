'use strict';

/**
 * Sign-in methods, looked up by the provider id the server reports from
 * `/auth/config`.
 *
 * The backend treats identity as a port with interchangeable
 * implementations; this is the same idea on the panel side. Each method
 * builds whatever UI it needs and hands back an opaque credential — only
 * the server knows how to verify one. SIGN_IN_METHODS below is the only
 * place in the extension that names a provider, so adding one is a new
 * entry here rather than a branch in panel-ui.js.
 *
 * Contract:
 *   id            string
 *   render(root, ctx)   build UI into `root`; call ctx.submit(credential)
 *   forgetSession()     optional; drop any session the provider keeps of
 *                       its own, on sign-out
 *
 * ctx:
 *   config        the /auth/config payload
 *   submit        (credential) => Promise, rejects when the server refuses
 *   setStatus     (message) => void, writes the shared status line
 */

// --- Google -----------------------------------------------------------------

const googleSignInMethod = {
  id: 'google',

  render(root, ctx) {
    const clientId = ctx.config?.google_client_id;
    if (!clientId) {
      root.appendChild(
        createNotice(
          'GOOGLE_OAUTH_CLIENT_ID is not configured on the server.',
          'signin-notice signin-notice-error',
        ),
      );
      return;
    }

    const button = createButton(t('authGoogleBtn'));
    button.addEventListener('click', () => {
      button.disabled = true;
      requestGoogleIdToken(clientId)
        .then((idToken) => ctx.submit(idToken))
        .catch((error) => {
          ctx.setStatus(error?.message || t('statusLoginFailed'));
        })
        .finally(() => {
          button.disabled = false;
        });
    });
    root.appendChild(button);
  },
};

// Implicit flow in the extension's own auth window; the server verifies the
// resulting ID token, so nothing here decides who the user is.
async function requestGoogleIdToken(clientId) {
  const params = new URLSearchParams({
    client_id: clientId,
    response_type: 'id_token',
    redirect_uri: chrome.identity.getRedirectURL(),
    scope: 'openid email profile',
    nonce: crypto.randomUUID(),
    prompt: 'select_account',
  });

  const responseUrl = await chrome.identity.launchWebAuthFlow({
    url: `https://accounts.google.com/o/oauth2/v2/auth?${params}`,
    interactive: true,
  });

  const fragment = new URL(responseUrl).hash.replace(/^#/, '');
  const idToken = new URLSearchParams(fragment).get('id_token');
  if (!idToken) {
    throw new Error(t('statusLoginFailed'));
  }
  return idToken;
}

// --- Mock (development only) -------------------------------------------------

const MOCK_ACCOUNTS_KEY = 'untangle.mock-accounts';

// Obviously fictional, so the mock is never mistaken for real sign-in.
const SEEDED_MOCK_ACCOUNTS = [
  { email: 'taro@example.com', name: '田中 太郎' },
  { email: 'alex@example.com', name: 'Alex Smith' },
];

/**
 * Development sign-in, shaped like the real one: press a button, pick an
 * account, land signed in. Matching the shape matters because it is the
 * flow developers exercise every day.
 *
 * Deliberately not dressed up as Google — no marks, and a badge saying
 * what it is. Its strings stay untranslated: this UI only exists when the
 * server runs AUTH_PROVIDER=mock, so it never reaches a user.
 */
const mockSignInMethod = {
  id: 'mock',

  render(root, ctx) {
    const open = createButton('Sign in with an account');
    open.appendChild(createBadge('mock'));
    open.addEventListener('click', () => {
      root.replaceChildren();
      renderAccountChooser(root, ctx);
    });
    root.appendChild(open);
  },
};

function renderAccountChooser(root, ctx) {
  const panel = document.createElement('div');
  panel.className = 'signin-chooser';

  const heading = document.createElement('strong');
  heading.className = 'signin-chooser-title';
  heading.textContent = 'Choose an account';
  panel.appendChild(heading);

  const list = document.createElement('div');
  list.className = 'signin-account-list';
  for (const account of readMockAccounts()) {
    list.appendChild(createAccountRow(account, ctx, root));
  }
  panel.appendChild(list);

  const another = createButton('Use another account');
  another.classList.add('preload-button-secondary');
  another.addEventListener('click', () => {
    root.replaceChildren();
    renderNewAccountForm(root, ctx);
  });
  panel.appendChild(another);

  panel.appendChild(
    createNotice(
      'Development mock. No Google sign-in happens; the server only accepts this while AUTH_PROVIDER=mock.',
      'signin-notice',
    ),
  );

  root.appendChild(panel);
}

function createAccountRow(account, ctx, root) {
  const row = document.createElement('button');
  row.type = 'button';
  row.className = 'signin-account';

  const avatar = document.createElement('span');
  avatar.className = 'signin-avatar';
  avatar.setAttribute('aria-hidden', 'true');
  avatar.style.backgroundColor = avatarColor(account.email);
  avatar.textContent = (account.name || account.email).charAt(0).toUpperCase();

  const text = document.createElement('span');
  text.className = 'signin-account-text';
  const name = document.createElement('span');
  name.className = 'signin-account-name';
  name.textContent = account.name || account.email;
  const email = document.createElement('span');
  email.className = 'signin-account-email';
  email.textContent = account.email;
  text.append(name, email);

  row.append(avatar, text);
  row.addEventListener('click', () => {
    row.disabled = true;
    ctx
      .submit(`mock:${account.email}:${account.name}`)
      .then(() => rememberMockAccount(account))
      .catch(() => {
        row.disabled = false;
        // The status line already carries the reason; let the user retry
        // or pick a different account.
        root.replaceChildren();
        renderAccountChooser(root, ctx);
      });
  });
  return row;
}

function renderNewAccountForm(root, ctx) {
  const form = document.createElement('form');
  form.className = 'signin-chooser';

  const emailLabel = document.createElement('label');
  emailLabel.className = 'field auth-field';
  const emailCaption = document.createElement('span');
  emailCaption.textContent = 'Email';
  const emailInput = document.createElement('input');
  emailInput.type = 'email';
  emailInput.required = true;
  emailInput.placeholder = 'you@example.com';
  emailLabel.append(emailCaption, emailInput);

  const nameLabel = document.createElement('label');
  nameLabel.className = 'field auth-field';
  const nameCaption = document.createElement('span');
  nameCaption.textContent = 'Display name (optional)';
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameLabel.append(nameCaption, nameInput);

  const submit = createButton('Continue');
  submit.type = 'submit';
  const back = createButton('Back');
  back.classList.add('preload-button-secondary');
  back.addEventListener('click', () => {
    root.replaceChildren();
    renderAccountChooser(root, ctx);
  });

  form.append(emailLabel, nameLabel, submit, back);
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const account = { email: emailInput.value.trim(), name: nameInput.value.trim() };
    if (!account.email) {
      return;
    }
    submit.disabled = true;
    ctx
      .submit(`mock:${account.email}:${account.name}`)
      .then(() => rememberMockAccount(account))
      .catch(() => {
        submit.disabled = false;
      });
  });

  root.appendChild(form);
}

function readMockAccounts() {
  return dedupeByEmail([...readRememberedAccounts(), ...SEEDED_MOCK_ACCOUNTS]);
}

function rememberMockAccount(account) {
  // Most recently used first, the order a chooser is expected to have.
  const next = dedupeByEmail([account, ...readRememberedAccounts()]).slice(0, 8);
  try {
    localStorage.setItem(MOCK_ACCOUNTS_KEY, JSON.stringify(next));
  } catch {
    // Remembering is a convenience; failing to is not worth surfacing.
  }
}

function readRememberedAccounts() {
  try {
    const parsed = JSON.parse(localStorage.getItem(MOCK_ACCOUNTS_KEY) || '[]');
    return Array.isArray(parsed)
      ? parsed.filter((item) => item && typeof item.email === 'string')
      : [];
  } catch {
    return [];
  }
}

function dedupeByEmail(accounts) {
  const seen = new Set();
  return accounts.filter((account) => {
    const key = String(account.email).toLowerCase();
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

/** A stable colour per account, so the same face appears each time. */
function avatarColor(email) {
  const palette = ['#5436da', '#10a37f', '#d97706', '#db2777', '#0284c7'];
  let hash = 0;
  for (const character of String(email)) {
    hash = (hash * 31 + character.charCodeAt(0)) % 997;
  }
  return palette[hash % palette.length];
}

// --- shared helpers ----------------------------------------------------------

function createButton(label) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'preload-button';
  button.textContent = label;
  return button;
}

function createBadge(label) {
  const badge = document.createElement('span');
  badge.className = 'signin-badge';
  badge.textContent = label;
  return badge;
}

function createNotice(text, className) {
  const notice = document.createElement('small');
  notice.className = className;
  notice.textContent = text;
  return notice;
}

// --- registry ----------------------------------------------------------------

const SIGN_IN_METHODS = {
  google: googleSignInMethod,
  mock: mockSignInMethod,
};

/** Null when the server names a provider this build does not implement. */
function signInMethodFor(provider) {
  return (provider && SIGN_IN_METHODS[provider]) || null;
}
