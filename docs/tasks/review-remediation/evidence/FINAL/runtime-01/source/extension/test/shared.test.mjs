// Tests for the pure functions in extension/shared.js and settings.js.
// Run with: node --test extension/test/shared.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { webcrypto } from 'node:crypto';
import vm from 'node:vm';

const extensionDir = join(dirname(fileURLToPath(import.meta.url)), '..');

function loadScripts(...files) {
  const sandbox = {
    console,
    Node: { ELEMENT_NODE: 1 },
    URL,
    URLSearchParams,
    crypto: webcrypto,
  };
  vm.createContext(sandbox);
  for (const file of files) {
    const sourcePath = join(extensionDir, file);
    vm.runInContext(readFileSync(sourcePath, 'utf8'), sandbox, {
      filename: sourcePath,
    });
  }
  return sandbox;
}

const S = loadScripts('settings.js', 'i18n.js', 'shared.js');
const settings = loadScripts('settings.js', 'i18n.js');

test('settings can be reinjected without losing safe localized error handling', async () => {
  const reloaded = loadScripts('settings.js', 'i18n.js', 'settings.js');
  assert.equal(vm.runInContext('Object.isFrozen(API_ERROR_CODE_KEYS)', reloaded), true);
  assert.equal(vm.runInContext('Object.getPrototypeOf(API_ERROR_CODE_KEYS)', reloaded), null);
  assert.equal(
    await reloaded.readApiErrorMessage(
      { json: async () => ({ code: 'article_quota_exceeded' }) },
      'fallback',
    ),
    reloaded.t('quotaArticleExceeded'),
  );
  assert.equal(
    await reloaded.readApiErrorMessage({ json: async () => ({ code: '__proto__' }) }, 'fallback'),
    'fallback',
  );
});

// Results cross the vm-context boundary, so rebuild them as plain host
// objects before deep-equality assertions.
function span(result) {
  return result ? { index: result.index, length: result.length } : null;
}

// Top-level const/let bindings live in the context's lexical scope, not on
// the sandbox object; evaluate an expression inside the context to reach them.
function vmEval(sandbox, expression) {
  return vm.runInContext(expression, sandbox);
}

const NBSP = ' ';
const ZWSP = '\u200b';
const ZWJ = '\u200d';
const BOM = '\ufeff';

test('operation helper generates UUID v7 and preserves retry identity', () => {
  const operationId = S.generateUuidV7();
  assert.match(
    operationId,
    /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );

  const first = S.withOperationId({ text: 'hello' });
  const retry = S.withOperationId({ text: 'hello' }, first.operation_id);
  assert.equal(retry.operation_id, first.operation_id);
  assert.equal(retry.text, 'hello');
});

test('preload job updates use shared extension storage and normalize the page URL', async () => {
  const shared = loadScripts('settings.js', 'i18n.js', 'shared.js');
  const writes = [];
  shared.chrome = {
    storage: {
      local: {
        async set(value) {
          writes.push(value);
        },
      },
    },
  };

  await shared.updatePreloadJob('https://article.example/reading/#section', {
    state: 'loading',
    message: 'Preparing article',
  });

  assert.equal(writes.length, 1);
  assert.equal(writes[0].preloadJob.pageUrl, 'https://article.example/reading');
  assert.equal(writes[0].preloadJob.state, 'loading');
  assert.equal(writes[0].preloadJob.message, 'Preparing article');
  assert.equal(typeof writes[0].preloadJob.updatedAt, 'number');
});

test('logical request retries reuse one operation identity', async () => {
  const attempts = [];
  const result = await S.runIdempotentRequest({ text: 'hello' }, async (payload) => {
    attempts.push(payload.operation_id);
    if (attempts.length === 1) {
      const error = new Error('network interrupted');
      error.name = 'ApiNetworkError';
      throw error;
    }
    return 'ok';
  });

  assert.equal(result, 'ok');
  assert.equal(attempts.length, 2);
  assert.equal(attempts[0], attempts[1]);
});

test('retryable HTTP 5xx cancels its real response stream and preserves identity', async () => {
  const attempts = [];
  let cancelled = false;
  const retryResponse = new Response(
    new ReadableStream({
      pull(controller) {
        controller.enqueue(new TextEncoder().encode('private server response'));
      },
      cancel() {
        cancelled = true;
      },
    }),
    {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    },
  );
  const result = await S.runIdempotentRequest(
    { text: 'hello', nested: { value: 1 } },
    async (payload) => {
      attempts.push(JSON.stringify(payload));
      return attempts.length === 1
        ? retryResponse
        : new Response('{}', {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
    },
  );

  assert.equal(result.status, 200);
  assert.equal(cancelled, true);
  assert.equal(attempts.length, 2);
  assert.equal(attempts[0], attempts[1]);
  assert.match(JSON.parse(attempts[0]).operation_id, /-7[0-9a-f]{3}-/);
});

test('programming TypeErrors are never retried', async () => {
  let attempts = 0;
  await assert.rejects(
    S.runIdempotentRequest({}, async () => {
      attempts += 1;
      throw new TypeError('programming bug');
    }),
    /programming bug/,
  );
  assert.equal(attempts, 1);
});

test('HTTP 4xx quota or conflict response is never retried', async () => {
  const attempts = [];
  const result = await S.runIdempotentRequest({ text: 'hello' }, async (payload) => {
    attempts.push(payload.operation_id);
    return { ok: false, status: 409 };
  });

  assert.equal(result.status, 409);
  assert.equal(attempts.length, 1);
});

test('contract violations are never retried as network failures', async () => {
  let attempts = 0;
  const violation = new Error('safe contract failure');
  violation.name = 'ApiContractViolationError';
  violation.retryable = false;

  await assert.rejects(
    S.runIdempotentRequest({}, async () => {
      attempts += 1;
      throw violation;
    }),
    violation,
  );
  assert.equal(attempts, 1);
});

test('API error messages expose only localized allowlisted codes', async () => {
  S.setUiLocale('ja');
  const localized = await S.readApiErrorMessage(
    {
      async json() {
        return {
          code: 'article_quota_exceeded',
          detail: 'private@example.com token=secret',
        };
      },
    },
    'generic fallback',
  );
  assert.equal(localized, S.t('quotaArticleExceeded'));
  assert.doesNotMatch(localized, /private|secret/);

  S.setUiLocale('en');
  const fallback = await S.readApiErrorMessage(
    {
      async json() {
        return {
          code: 'internal_database_failure',
          detail: [{ msg: 'SQL password=secret' }],
        };
      },
    },
    'generic fallback',
  );
  assert.equal(fallback, 'generic fallback');

  const inherited = Object.create({ code: 'chat_quota_exceeded' });
  inherited.detail = 'must remain private';
  assert.equal(
    await S.readApiErrorMessage(
      {
        async json() {
          return inherited;
        },
      },
      'safe fallback',
    ),
    'safe fallback',
  );
});

test('normalizeText collapses whitespace variants', () => {
  assert.equal(S.normalizeText(`  a ${NBSP} b${ZWSP}${ZWJ}c  `), 'a bc');
  assert.equal(S.normalizeText(null), '');
  assert.equal(S.normalizeText('line\nbreaks\tand   spaces'), 'line breaks and spaces');
});

test('normalizeTextForMatch maps curly quotes and dashes', () => {
  assert.equal(S.normalizeTextForMatch('“Hi” — it’s'), '"Hi" - it\'s');
});

test('escapeHtml escapes markup', () => {
  assert.equal(
    S.escapeHtml(`<a href="x">'&'</a>`),
    '&lt;a href=&quot;x&quot;&gt;&#039;&amp;&#039;&lt;/a&gt;',
  );
});

test('findNeedleInText finds exact and normalized matches', () => {
  assert.deepEqual(span(S.findNeedleInText('Hello world today', 'world')), {
    index: 6,
    length: 5,
  });

  const spaced = S.findNeedleInText('Hello  world', 'Hello world');
  assert.equal(spaced.index, 0);
  assert.equal('Hello  world'.slice(spaced.index, spaced.index + spaced.length), 'Hello  world');

  const quoted = S.findNeedleInText('She said “yes” loudly', 'said "yes"');
  assert.equal(quoted.index, 4);

  assert.equal(S.findNeedleInText('abc', 'xyz'), null);
  assert.equal(S.findNeedleInText('abc', ''), null);
});

test('findNeedleInText accepts a precomputed normalized haystack', () => {
  const text = 'Hello  world';
  const normalized = S.normalizeTextForMatch(text);
  assert.deepEqual(
    span(S.findNeedleInText(text, 'world', normalized)),
    span(S.findNeedleInText(text, 'world')),
  );
});

test('span covers the full match after whitespace (legacy off-by-one)', () => {
  // The previous implementation returned "uick" for this input because the
  // collapsed space before the match was trimmed out of the prefix length.
  const raw = 'The quick brown fox';
  const match = S.findNeedleInText(raw, 'quick');
  assert.equal(raw.slice(match.index, match.index + match.length), 'quick');

  const nbsp = `The${NBSP}quick brown fox`;
  const nbspMatch = S.findNeedleInText(nbsp, 'quick');
  assert.equal(nbsp.slice(nbspMatch.index, nbspMatch.index + nbspMatch.length), 'quick');
});

test('findRawSpanForNormalizedMatch explicit cases', () => {
  const cases = [
    // [rawText, normStart, normLength, expected raw slice]
    ['plain text here', 0, 5, 'plain'],
    ['plain text here', 6, 4, 'text'],
    ['  leading spaces', 0, 7, 'leading'],
    ['trailing spaces   ', 9, 6, 'spaces'],
    ['multi   space   gaps', 6, 5, 'space'],
    ['“quoted” text', 0, 8, '“quoted”'],
    [`a${ZWSP}b c`, 0, 2, `a${ZWSP}b`],
  ];

  for (const [raw, start, length, expected] of cases) {
    const result = S.findRawSpanForNormalizedMatch(raw, start, length);
    assert.ok(result, `no span for ${JSON.stringify([raw, start, length])}`);
    assert.equal(
      raw.slice(result.index, result.index + result.length),
      expected,
      `case: ${JSON.stringify([raw, start, length])}`,
    );
  }

  assert.equal(S.findRawSpanForNormalizedMatch('', 0, 1), null);
  assert.equal(S.findRawSpanForNormalizedMatch('ab', 0, 5), null);
  assert.equal(S.findRawSpanForNormalizedMatch('abc', 1, 0), null);
});

test('findRawSpanForNormalizedMatch fuzz: span normalizes back to the match', () => {
  const alphabet = [
    'a',
    'b',
    'c',
    ' ',
    ' ',
    NBSP,
    ' ',
    ' ',
    ZWSP,
    ZWJ,
    BOM,
    '\n',
    '\t',
    '“',
    '’',
    '—',
    '.',
    '!',
  ];
  let seed = 42;
  const rand = (max) => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed % max;
  };

  let checked = 0;
  for (let iteration = 0; iteration < 2000; iteration += 1) {
    const length = rand(40);
    let raw = '';
    for (let index = 0; index < length; index += 1) {
      raw += alphabet[rand(alphabet.length)];
    }

    const normalized = S.normalizeTextForMatch(raw);
    if (!normalized.length) continue;

    const normStart = rand(normalized.length);
    const maxLength = normalized.length - normStart;
    const normLength = 1 + rand(maxLength);
    const segment = normalized.slice(normStart, normStart + normLength);
    // Real needles are trimmed, so segments never begin or end with a space.
    if (segment.startsWith(' ') || segment.endsWith(' ')) continue;

    const result = S.findRawSpanForNormalizedMatch(raw, normStart, normLength);
    assert.ok(result, `no span for ${JSON.stringify([raw, normStart, normLength])}`);
    assert.equal(
      S.normalizeTextForMatch(raw.slice(result.index, result.index + result.length)),
      segment,
      `fuzz: ${JSON.stringify([raw, normStart, normLength])}`,
    );
    checked += 1;
  }

  assert.ok(checked > 500, `expected many checked cases, got ${checked}`);
});

test('renderChatMarkdown renders headings, lists, and inline markup', () => {
  const html = S.renderChatMarkdown(
    '# Title\n- one\n- **two**\n\n1. first\n2. second\n\n---\n`code` *em*',
  );
  assert.match(html, /<h1>Title<\/h1>/);
  assert.match(html, /<ul><li>one<\/li><li><strong>two<\/strong><\/li><\/ul>/);
  assert.match(html, /<ol><li>first<\/li><li>second<\/li><\/ol>/);
  assert.match(html, /<hr>/);
  assert.match(html, /<code>code<\/code> <em>em<\/em>/);
});

test('renderChatMarkdown escapes raw HTML', () => {
  const html = S.renderChatMarkdown('<script>alert(1)</script>');
  assert.ok(!html.includes('<script>'));
  assert.match(html, /&lt;script&gt;/);
});

test('formatVocabularyItem splits term and explanation', () => {
  assert.equal(S.formatVocabularyItem('run [verb]: 走る'), '<strong>run</strong>: 走る');
  assert.equal(S.formatVocabularyItem('run: 走る'), '<strong>run</strong>: 走る');
  assert.equal(S.formatVocabularyItem('plain'), 'plain');
});

test('parseVocabularyItem extracts term, part of speech, and meaning', () => {
  // Results cross the vm-context boundary, so rebuild them as plain objects.
  const parse = (item) => {
    const { term, partOfSpeech, explanation } = S.parseVocabularyItem(item);
    return { term, partOfSpeech, explanation };
  };

  assert.deepEqual(parse('take care of [phrasal verb]: 世話する'), {
    term: 'take care of',
    partOfSpeech: 'phrasal verb',
    explanation: '世話する',
  });
  assert.deepEqual(parse('run: 走る'), {
    term: 'run',
    partOfSpeech: '',
    explanation: '走る',
  });
  assert.deepEqual(parse('no colon here'), {
    term: '',
    partOfSpeech: '',
    explanation: 'no colon here',
  });
});

test('renderAnalysis places a vocab prefix per term and keeps the body', () => {
  const analysis = {
    translation: '訳',
    grammar: '文法',
    vocabulary: ['fox [noun]: きつね', 'lazy: 怠惰な'],
  };
  const calls = [];
  const html = S.renderAnalysis(analysis, {
    renderVocabPrefix: (term, index) => {
      calls.push([term, index]);
      return `<button data-speak-key="vocab:${index}"></button>`;
    },
  });

  assert.deepEqual(calls, [
    ['fox', 0],
    ['lazy', 1],
  ]);
  assert.match(html, /<li class="era-vocab-line"><button data-speak-key="vocab:0">/);
  assert.match(html, /<span class="era-vocab-line-body"><strong>fox<\/strong>: きつね<\/span>/);

  // Without a prefix renderer the bullet lines still render, just no button.
  const plain = S.renderAnalysis(analysis);
  assert.ok(!plain.includes('data-speak-key'));
  assert.match(plain, /<li class="era-vocab-line"><span class="era-vocab-line-body">/);
});

const preloadFixture = {
  sentences: [
    { id: 's1', index: 0, text: 'The quick brown fox jumps.' },
    { id: 's2', index: 1, text: 'It leaps over the lazy dog.' },
    { id: 's3', index: 2, text: 'Everyone applauds politely.' },
  ],
  study_items: [
    { id: 'v1', text: 'lazy dog', sentence_ids: ['s2'] },
    { id: 'v2', text: 'quick brown', sentence_ids: ['s1'] },
    { id: 'v3', text: 'applauds', sentence_ids: ['s3'] },
  ],
};

test('findSentenceById and adjacency navigate the preload', () => {
  assert.equal(S.findSentenceById(preloadFixture, 's2').index, 1);
  assert.equal(S.findSentenceById(preloadFixture, 'missing'), null);
  assert.equal(S.findSentenceById(null, 's1'), null);

  const s2 = S.findSentenceById(preloadFixture, 's2');
  assert.equal(S.getAdjacentSentence(preloadFixture, s2, 'prev').id, 's1');
  assert.equal(S.getAdjacentSentence(preloadFixture, s2, 'next').id, 's3');
  assert.equal(
    S.getAdjacentSentence(preloadFixture, S.findSentenceById(preloadFixture, 's1'), 'prev'),
    null,
  );
});

test('sortStudyItems orders items by appearance in the text', () => {
  const sorted = S.sortStudyItems(preloadFixture);
  assert.equal(sorted.map((item) => item.id).join(','), 'v2,v1,v3');

  const middle = S.getStudyItemById(preloadFixture, 'v1');
  assert.equal(S.getAdjacentStudyItem(preloadFixture, middle, 'prev').id, 'v2');
  assert.equal(S.getAdjacentStudyItem(preloadFixture, middle, 'next').id, 'v3');
});

test('language helpers normalize codes, labels, and TTS tags', () => {
  assert.equal(settings.normalizeLanguageCode('EN-us'), 'en');
  assert.equal(settings.normalizeLanguageCode('zh_Hans_CN'), 'zh');
  assert.equal(settings.normalizeLanguageCode('123'), '');
  assert.equal(settings.normalizeLanguageCode(null), '');

  assert.equal(settings.getLanguageLabel('fr'), 'Français');
  assert.equal(settings.getTtsLangTag('en'), 'en-US');
  assert.equal(settings.getTtsLangTag('pt-BR'), 'pt-BR');
  assert.equal(settings.getTtsLangTag(''), 'en-US');
  assert.equal(settings.getTtsLangTag('nl'), 'nl');
});

test('normalizeLanguageProfile validates and falls back to defaults', () => {
  const plain = (profile) => ({ target: profile.target, native: profile.native });

  assert.deepEqual(plain(settings.normalizeLanguageProfile(null)), { target: 'en', native: 'ja' });
  assert.deepEqual(plain(settings.normalizeLanguageProfile({ target: 'auto', native: 'en' })), {
    target: 'auto',
    native: 'en',
  });
  assert.deepEqual(plain(settings.normalizeLanguageProfile({ target: 'FR', native: 'xx' })), {
    target: 'fr',
    native: 'ja',
  });
});

test('i18n catalogs are complete for every supported locale', () => {
  const vm2 = settings;
  const report = JSON.parse(
    vmEval(
      vm2,
      `(() => {
      const locales = Object.keys(UI_MESSAGES);
      const jaKeys = Object.keys(UI_MESSAGES.ja).sort();
      const problems = [];
      for (const locale of locales) {
        const keys = Object.keys(UI_MESSAGES[locale]).sort();
        const missing = jaKeys.filter((key) => !keys.includes(key));
        const extra = keys.filter((key) => !jaKeys.includes(key));
        if (missing.length || extra.length) problems.push({ locale, missing, extra });
      }
      return JSON.stringify({ locales, keyCount: jaKeys.length, problems });
    })()`,
    ),
  );

  assert.deepEqual(report.problems, [], JSON.stringify(report.problems));
  assert.equal(report.locales.length, 10);
  assert.ok(report.keyCount > 100);
});

test('t() interpolates params and falls back to English for unknown locales', () => {
  settings.setUiLocale('fr');
  assert.match(settings.t('preloadDonePanel', { count: 3 }), /3 phrases/);

  assert.equal(settings.setUiLocale('xx'), 'en');
  assert.equal(settings.t('chatSend'), 'Send');

  settings.setUiLocale('ja');
  assert.equal(settings.t('chatSend'), '送信');
});

test('quick chat actions follow the UI locale', () => {
  S.setUiLocale('en');
  const enAction = S.getQuickChatAction('syntax');
  assert.match(enAction.message, /in English/);
  assert.equal(enAction.label, 'Analyze syntax');

  S.setUiLocale('ja');
  const jaAction = S.getQuickChatAction('syntax');
  assert.match(jaAction.message, /日本語で/);
  assert.equal(S.getQuickChatAction('unknown'), null);
});

test('learner presets follow the target language scale', () => {
  settings.setUiLocale('ja');
  const enForJa = settings.getLearnerLevelPresets('en');
  assert.ok(enForJa.some((preset) => preset.id === 'toeic-700'));
  assert.ok(!enForJa.some((preset) => preset.id === 'cefr-b1'));

  settings.setUiLocale('en');
  const enForEn = settings.getLearnerLevelPresets('en');
  assert.ok(enForEn.some((preset) => preset.id === 'cefr-b1'));
  assert.ok(!enForEn.some((preset) => preset.id === 'toeic-700'));

  settings.setUiLocale('ja');
  assert.ok(settings.getLearnerLevelPresets('ja').some((preset) => preset.id === 'jlpt-n2'));
  assert.ok(settings.getLearnerLevelPresets('zh').some((preset) => preset.id === 'hsk-4'));
  assert.ok(settings.getLearnerLevelPresets('ko').some((preset) => preset.id === 'topik-3'));
  // French has no dedicated scale here: CEFR regardless of UI locale.
  assert.ok(settings.getLearnerLevelPresets('fr').some((preset) => preset.id === 'cefr-b1'));
  assert.ok(settings.getLearnerPresetLabel('jlpt-n2') === 'JLPT N2');
});

test('formatLearnerLevelForApi checks the preset id, not its label', () => {
  settings.setUiLocale('ja');
  assert.equal(settings.formatLearnerLevelForApi({ preset: '', notes: 'メモ' }), 'メモ');
  assert.equal(
    settings.formatLearnerLevelForApi({ preset: 'toeic-700', notes: '' }),
    'TOEIC 700点程度',
  );
  assert.equal(
    settings.formatLearnerLevelForApi({ preset: 'toeic-700', notes: 'メモ' }),
    'TOEIC 700点程度。メモ',
  );
  assert.equal(settings.formatLearnerLevelForApi({ preset: '', notes: '' }), null);
});

test('vocabulary coverage maps stable learner preset ids to learner bands', () => {
  const expected = {
    beginner: [
      'toeic-500',
      'eiken-2',
      'cefr-a1',
      'cefr-a2',
      'jlpt-n5',
      'jlpt-n4',
      'hsk-1',
      'hsk-2',
      'topik-1',
      'topik-2',
    ],
    intermediate: [
      'toeic-600',
      'toeic-700',
      'eiken-p1',
      'cefr-b1',
      'cefr-b2',
      'jlpt-n3',
      'hsk-3',
      'hsk-4',
      'topik-3',
      'topik-4',
    ],
    advanced: [
      'toeic-800',
      'toeic-900',
      'eiken-1',
      'cefr-c1',
      'cefr-c2',
      'jlpt-n2',
      'jlpt-n1',
      'hsk-5',
      'hsk-6',
      'topik-5',
      'topik-6',
    ],
  };
  const coverage = { beginner: 18, intermediate: 12, advanced: 7 };
  const actual = JSON.parse(vmEval(settings, 'JSON.stringify(LEARNER_LEVEL_BAND_BY_PRESET_ID)'));

  assert.deepEqual(
    actual,
    Object.fromEntries(
      Object.entries(expected).flatMap(([band, presetIds]) =>
        presetIds.map((presetId) => [presetId, band]),
      ),
    ),
  );
  for (const [band, presetIds] of Object.entries(expected)) {
    for (const preset of presetIds) {
      assert.equal(settings.getVocabularyCoveragePercent({ preset }), coverage[band], preset);
    }
  }
});

test('vocabulary coverage defaults safely for notes and unset profiles', () => {
  assert.equal(settings.getVocabularyCoveragePercent({ preset: '', notes: 'News reader' }), 12);
  assert.equal(
    settings.getVocabularyCoveragePercent({ preset: 'retired-level', notes: 'News reader' }),
    12,
  );
  assert.equal(settings.getVocabularyCoveragePercent({ preset: '', notes: '' }), 8);
});

test('learner profile revisions invalidate an older preload snapshot', async () => {
  const s = loadScripts('settings.js', 'i18n.js');
  const store = {};
  s.chrome = {
    storage: {
      local: {
        async get(key) {
          if (Array.isArray(key)) {
            return Object.fromEntries(key.map((item) => [item, store[item]]));
          }
          return { [key]: store[key] };
        },
        async set(values) {
          Object.assign(store, values);
        },
      },
    },
  };

  const snapshot = await s.setLearnerProfile({ preset: 'cefr-a1', notes: '' });
  const current = await s.setLearnerProfile({ preset: 'cefr-c1', notes: 'News articles' });
  const unchanged = await s.setLearnerProfile({ preset: 'cefr-c1', notes: 'News articles' });

  assert.equal(snapshot.revision, 1);
  assert.equal(current.revision, 2);
  assert.equal(unchanged.revision, 2);
  assert.equal(s.learnerProfileRevisionMatches(snapshot, current), false);
  assert.equal(s.learnerProfileRevisionMatches(current, await s.getLearnerProfile()), true);
});

test('learner profile cache fingerprints collapse internal whitespace', () => {
  settings.setUiLocale('en');
  const spaced = {
    preset: '',
    notes: '  Read   news\narticles\tcarefully  ',
  };
  const normalized = {
    preset: '',
    notes: 'Read news articles carefully',
  };

  assert.equal(settings.normalizeLearnerProfileText(spaced.notes), 'Read news articles carefully');
  assert.equal(
    settings.getLearnerProfileCacheFingerprint(spaced),
    settings.getLearnerProfileCacheFingerprint(normalized),
  );
});

test('normalizePageUrl strips hash and trailing slash', () => {
  assert.equal(
    settings.normalizePageUrl('https://example.com/a/?q=1#top'),
    'https://example.com/a/?q=1',
  );
  assert.equal(settings.normalizePageUrl('https://example.com/a/'), 'https://example.com/a');
});

test('pageUrlsMatch tolerates hash and trailing-slash differences', () => {
  assert.ok(settings.pageUrlsMatch('https://example.com/a#x', 'https://example.com/a/'));
  assert.ok(!settings.pageUrlsMatch('https://example.com/a', 'https://example.com/b'));
  assert.ok(!settings.pageUrlsMatch('', 'https://example.com/a'));
});

test('api base url override normalizes, persists, and falls back to default', async () => {
  const s = loadScripts('settings.js', 'i18n.js');
  const store = {};
  s.chrome = {
    storage: {
      local: {
        async get(key) {
          return { [key]: store[key] };
        },
        async set(values) {
          Object.assign(store, values);
        },
        async remove(key) {
          delete store[key];
        },
      },
    },
  };

  assert.equal(s.normalizeApiBaseUrl('https://api.example.com/'), 'https://api.example.com');
  assert.equal(
    s.normalizeApiBaseUrl('https://api.example.com/stage/'),
    'https://api.example.com/stage',
  );
  assert.equal(s.normalizeApiBaseUrl('ftp://api.example.com'), '');
  assert.equal(s.normalizeApiBaseUrl('not a url'), '');
  assert.equal(s.normalizeApiBaseUrl('https://x.com/?a=1'), '');

  assert.equal(await s.getApiBaseUrl(), 'http://localhost:18765');
  await s.setApiBaseUrl('https://abc.execute-api.ap-northeast-1.amazonaws.com/');
  assert.equal(await s.getApiBaseUrl(), 'https://abc.execute-api.ap-northeast-1.amazonaws.com');
  // Empty (or invalid) input clears the override.
  await s.setApiBaseUrl('');
  assert.equal(await s.getApiBaseUrl(), 'http://localhost:18765');
});

test('normalizeCustomChatPrompts trims, drops invalid, assigns ids, caps at 20', () => {
  const out = S.normalizeCustomChatPrompts([
    { label: '  Etymology  ', message: '  Explain the origin.  ' },
    { label: '', message: 'no label' },
    { label: 'no message', message: '   ' },
    { id: 'keep-me', label: 'Kept', message: 'Body' },
  ]);
  assert.equal(out.length, 2);
  assert.deepEqual(
    { label: out[0].label, message: out[0].message },
    {
      label: 'Etymology',
      message: 'Explain the origin.',
    },
  );
  assert.match(out[0].id, /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(out[1].id, 'keep-me');

  const many = Array.from({ length: 25 }, (_, i) => ({ label: `L${i}`, message: `M${i}` }));
  assert.equal(S.normalizeCustomChatPrompts(many).length, 20);

  assert.deepEqual([...S.normalizeCustomChatPrompts(null)], []);
  assert.deepEqual([...S.normalizeCustomChatPrompts('nope')], []);
});

test('addCustomChatPrompt appends valid, rejects invalid and over-limit', () => {
  const first = S.addCustomChatPrompt([], { label: 'A', message: 'B' });
  assert.equal(first.ok, true);
  assert.equal(first.list.length, 1);

  const invalid = S.addCustomChatPrompt(first.list, { label: '  ', message: 'B' });
  assert.equal(invalid.ok, false);
  assert.equal(invalid.error, 'invalid');
  assert.equal(invalid.list.length, 1);

  const full = Array.from({ length: 20 }, (_, i) => ({
    id: `id${i}`,
    label: `L${i}`,
    message: `M${i}`,
  }));
  const overLimit = S.addCustomChatPrompt(full, { label: 'X', message: 'Y' });
  assert.equal(overLimit.ok, false);
  assert.equal(overLimit.error, 'limit');
});

test('updateCustomChatPrompt replaces by id, keeps id, rejects missing/invalid', () => {
  const list = [
    { id: 'a', label: 'A', message: 'MA' },
    { id: 'b', label: 'B', message: 'MB' },
  ];
  const ok = S.updateCustomChatPrompt(list, 'b', { label: 'B2', message: 'MB2' });
  assert.equal(ok.ok, true);
  assert.deepEqual({ ...ok.list[1] }, { id: 'b', label: 'B2', message: 'MB2' });

  assert.equal(
    S.updateCustomChatPrompt(list, 'zzz', { label: 'x', message: 'y' }).error,
    'missing',
  );
  assert.equal(S.updateCustomChatPrompt(list, 'a', { label: '', message: 'y' }).error, 'invalid');
});

test('removeCustomChatPrompt drops the matching id', () => {
  const list = [
    { id: 'a', label: 'A', message: 'MA' },
    { id: 'b', label: 'B', message: 'MB' },
  ];
  const out = S.removeCustomChatPrompt(list, 'a');
  assert.equal(out.length, 1);
  assert.equal(out[0].id, 'b');
});

test('moveCustomChatPrompt swaps neighbours and clamps at bounds', () => {
  const list = [
    { id: 'a', label: 'A', message: 'MA' },
    { id: 'b', label: 'B', message: 'MB' },
  ];
  assert.deepEqual(
    S.moveCustomChatPrompt(list, 'b', -1).map((p) => p.id),
    ['b', 'a'],
  );
  assert.deepEqual(
    S.moveCustomChatPrompt(list, 'a', -1).map((p) => p.id),
    ['a', 'b'],
  );
  assert.deepEqual(
    S.moveCustomChatPrompt(list, 'b', 1).map((p) => p.id),
    ['a', 'b'],
  );
});

test('resolveQuickChatActions returns built-ins then customs, dropping empties', () => {
  const custom = [
    { id: 'c1', label: 'Etymology', message: 'Explain the origin.' },
    { id: 'c2', label: '', message: 'dropped' },
  ];
  const builtInOnly = S.resolveQuickChatActions(['syntax'], []);
  assert.equal(builtInOnly.length, 1);
  assert.ok(builtInOnly[0].label && builtInOnly[0].message);

  const combined = S.resolveQuickChatActions(['syntax'], custom);
  assert.equal(combined.length, 2);
  assert.deepEqual({ ...combined[1] }, { label: 'Etymology', message: 'Explain the origin.' });

  const customOnly = S.resolveQuickChatActions([], custom);
  assert.equal(customOnly.length, 1);
});

test('renderContextChat appends cached custom prompts as quick actions', () => {
  S.setCustomChatPromptsCache([{ id: 'c1', label: 'Etymology', message: 'Explain "it".' }]);
  const html = S.renderContextChat('sentence:1', { quickActions: [] });
  assert.match(html, /era-context-chat-quick-action/);
  assert.match(html, />Etymology</);
  assert.match(html, /title="Explain &quot;it&quot;\."/);
  assert.match(html, /data-quick-message="Explain &quot;it&quot;\."/);
  S.setCustomChatPromptsCache([]); // reset shared cache for other tests
});

test('normalizeHiddenQuickActions dedupes, trims, drops empty, non-array -> []', () => {
  assert.deepEqual([...S.normalizeHiddenQuickActions(['a', ' b ', 'a', '', 'b'])], ['a', 'b']);
  assert.deepEqual([...S.normalizeHiddenQuickActions(null)], []);
  assert.deepEqual([...S.normalizeHiddenQuickActions('x')], []);
});

test('toggleHiddenQuickAction adds then removes an id', () => {
  const once = S.toggleHiddenQuickAction([], 'syntax');
  assert.deepEqual([...once], ['syntax']);
  const twice = S.toggleHiddenQuickAction(once, 'syntax');
  assert.deepEqual([...twice], []);
  assert.deepEqual([...S.toggleHiddenQuickAction(['a'], 'b')], ['a', 'b']);
});

test('SENTENCE_QUICK_CHAT_ACTIONS includes meaning and getQuickChatAction resolves it', () => {
  assert.deepEqual([...S.SENTENCE_QUICK_CHAT_ACTIONS], ['syntax', 'paraphrase', 'meaning']);
  const a = S.getQuickChatAction('meaning');
  assert.ok(a && typeof a.label === 'string' && typeof a.message === 'string');
  assert.ok(a.label.length > 0 && a.message.length > 0);
});

test('resolveQuickChatActions filters hidden built-ins and customs by id', () => {
  const custom = [
    { id: 'c1', label: 'Etymology', message: 'Explain the origin.' },
    { id: 'c2', label: 'Tone', message: 'Describe the tone.' },
  ];
  const all = S.resolveQuickChatActions(['syntax', 'paraphrase'], custom, []);
  assert.equal(all.length, 4);
  const filtered = S.resolveQuickChatActions(['syntax', 'paraphrase'], custom, [
    'paraphrase',
    'c1',
  ]);
  assert.equal(filtered.length, 2);
  assert.deepEqual({ ...filtered[1] }, { label: 'Tone', message: 'Describe the tone.' });
});
