// Tests for the marking layer in extension/content.js — the code that rewrites
// a live page's DOM to anchor sentences and highlight vocabulary.
//
// Run with: node --test test/content-highlighting.test.mjs
//
// These functions splice <mark> elements into text nodes the extension does not
// own. The invariant that matters most is that the reader's page survives
// unchanged apart from the marks: the visible text must be byte-identical
// before and after. Almost every plausible bug in the slicing arithmetic
// (off-by-one offsets, dropped tail text, duplicated fragments) breaks that
// invariant, so it is asserted on every highlighting test here.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { withPage } from './dom-harness.mjs';

function page(body) {
  return `<!DOCTYPE html><html lang="en"><body><main>${body}</main></body></html>`;
}

/** Marks added by the sentence-anchoring path. */
function sentenceMarks(element) {
  return [...element.querySelectorAll('mark.era-sentence-mark')];
}

/** Marks added by the vocabulary path. */
function vocabularyMarks(element) {
  return [...element.querySelectorAll('mark.era-vocabulary-mark')];
}

// --- Sentence highlighting --------------------------------------------------

test('highlightSentenceInElement: marks a whole sentence and preserves the text', async () => {
  await withPage(page('<p id="p">The council voted on Tuesday to rebuild the wall.</p>'), (p) => {
    const element = p.document.getElementById('p');
    const before = element.textContent;

    p.call(
      'highlightSentenceInElement',
      element,
      'The council voted on Tuesday to rebuild the wall.',
      's1',
    );

    const marks = sentenceMarks(element);
    assert.equal(marks.length, 1);
    assert.equal(marks[0].textContent, 'The council voted on Tuesday to rebuild the wall.');
    assert.equal(marks[0].dataset.eraSentenceId, 's1');
    assert.equal(element.textContent, before, 'page text must be unchanged');
  });
});

test('highlightSentenceInElement: spans inline elements without losing text', async () => {
  await withPage(
    page(
      '<p id="p">The <em>tokenizer</em> runs before the <strong>parser</strong> in every case.</p>',
    ),
    (p) => {
      const element = p.document.getElementById('p');
      const before = element.textContent;

      p.call(
        'highlightSentenceInElement',
        element,
        'The tokenizer runs before the parser in every case.',
        's1',
      );

      const marks = sentenceMarks(element);
      assert.equal(marks.length, 5, 'one mark per text node the sentence crosses');
      assert.equal(
        marks.map((mark) => mark.textContent).join(''),
        'The tokenizer runs before the parser in every case.',
      );
      assert.equal(element.textContent, before, 'page text must be unchanged');

      // The inline structure must survive: the marks go inside <em>/<strong>,
      // they do not replace them.
      assert.ok(element.querySelector('em mark.era-sentence-mark'));
      assert.ok(element.querySelector('strong mark.era-sentence-mark'));
    },
  );
});

test('highlightSentenceInElement: marks only the matched part of a longer block', async () => {
  await withPage(
    page('<p id="p">First sentence here. The second sentence is the target. A third follows.</p>'),
    (p) => {
      const element = p.document.getElementById('p');
      const before = element.textContent;

      p.call('highlightSentenceInElement', element, 'The second sentence is the target.', 's1');

      const marks = sentenceMarks(element);
      assert.equal(marks.length, 1);
      assert.equal(marks[0].textContent, 'The second sentence is the target.');
      assert.equal(element.textContent, before);
    },
  );
});

test('highlightSentenceInElement: pulls in a leading opening quote', async () => {
  // expandSentenceMatch() deliberately extends the match backwards over an
  // opening quote so a quoted sentence does not start mid-punctuation. It does
  // NOT extend forwards over the closing quote; that asymmetry is intentional.
  await withPage(page('<p id="p">She said “a small change” and then left the room.</p>'), (p) => {
    const element = p.document.getElementById('p');
    const before = element.textContent;

    p.call('highlightSentenceInElement', element, 'a small change', 's1');

    const marks = sentenceMarks(element);
    assert.equal(marks.length, 1);
    assert.equal(marks[0].textContent, '“a small change');
    assert.equal(element.textContent, before);
  });
});

test('highlightSentenceInElement: does nothing when the sentence is absent', async () => {
  await withPage(page('<p id="p">Some unrelated prose sits here.</p>'), (p) => {
    const element = p.document.getElementById('p');
    const before = element.innerHTML;

    p.call('highlightSentenceInElement', element, 'A sentence that is not present.', 's1');

    assert.equal(sentenceMarks(element).length, 0);
    assert.equal(element.innerHTML, before, 'a miss must leave the DOM untouched');
  });
});

test('highlightSentenceInElement: never marks script or style text', async () => {
  await withPage(
    page(
      '<div id="d"><p>Visible prose about caching.</p>' +
        '<script>var s = "Visible prose about caching.";</script></div>',
    ),
    (p) => {
      const element = p.document.getElementById('d');

      p.call('highlightSentenceInElement', element, 'Visible prose about caching.', 's1');

      const marks = sentenceMarks(element);
      assert.equal(marks.length, 1);
      assert.equal(marks[0].closest('script'), null);
      assert.ok(marks[0].closest('p'), 'the mark belongs to the visible paragraph');
    },
  );
});

test('clearSentenceMarkers: restores the original markup', async () => {
  await withPage(
    page('<p id="p">The <em>tokenizer</em> runs before the <strong>parser</strong> here.</p>'),
    (p) => {
      const element = p.document.getElementById('p');
      const beforeText = element.textContent;

      p.call(
        'highlightSentenceInElement',
        element,
        'The tokenizer runs before the parser here.',
        's1',
      );
      assert.ok(sentenceMarks(element).length > 0);

      p.call('clearSentenceMarkers');

      assert.equal(sentenceMarks(element).length, 0, 'marks must be removed');
      assert.equal(element.textContent, beforeText, 'text must survive the round trip');
      assert.ok(element.querySelector('em'), 'inline elements must survive the round trip');
    },
  );
});

// --- Sentence anchoring -----------------------------------------------------

test('applySentenceAnchor: tags the block and claims it for the sentence', async () => {
  await withPage(page('<p id="p">Never deploy on a Friday afternoon.</p>'), (p) => {
    const element = p.document.getElementById('p');

    assert.equal(p.call('applySentenceAnchor', { id: 's1', text: 'x' }, element), true);
    assert.ok(element.classList.contains('era-page-anchor'));
    assert.ok(element.classList.contains('era-page-anchor-block'));
    assert.equal(element.dataset.eraSentenceId, 's1');
  });
});

test('applySentenceAnchor: the first sentence to claim a block keeps it', async () => {
  await withPage(page('<p id="p">One block, two sentences inside it.</p>'), (p) => {
    const element = p.document.getElementById('p');

    p.call('applySentenceAnchor', { id: 'first', text: 'One block,' }, element);
    p.call('applySentenceAnchor', { id: 'second', text: 'two sentences inside it.' }, element);

    assert.equal(element.dataset.eraSentenceId, 'first');
  });
});

test('applySentenceAnchor: refuses a missing block or sentence', async () => {
  await withPage(page('<p>Anything.</p>'), (p) => {
    assert.equal(p.call('applySentenceAnchor', { id: 's1' }, null), false);
    assert.equal(p.call('applySentenceAnchor', null, p.document.querySelector('p')), false);
  });
});

test('applyDuplicateSentenceAnchors: marks every block repeating the sentence verbatim', async () => {
  await withPage(
    page(
      '<p id="a">Never deploy on a Friday afternoon.</p>' +
        '<p id="b">Never deploy on a Friday afternoon.</p>' +
        '<p id="c">A different paragraph that shares no text.</p>',
    ),
    (p) => {
      const sentence = { id: 's1', text: 'Never deploy on a Friday afternoon.' };
      const root = p.document.getElementById('a');
      const ctx = p.evaluate('createSentenceMatchContext()');

      p.call('applySentenceAnchor', sentence, root);
      p.call('applyDuplicateSentenceAnchors', sentence, root, ctx);

      for (const id of ['a', 'b']) {
        const element = p.document.getElementById(id);
        assert.ok(
          element.classList.contains('era-page-anchor-block'),
          `${id} should read as analyzed`,
        );
        assert.equal(element.dataset.eraSentenceId, 's1');
      }

      const other = p.document.getElementById('c');
      assert.ok(!other.classList.contains('era-page-anchor-block'));
      assert.equal(other.dataset.eraSentenceId, undefined);
    },
  );
});

test('applyDuplicateSentenceAnchors: a partial overlap is not a duplicate', async () => {
  await withPage(
    page(
      '<p id="a">Never deploy on a Friday afternoon.</p>' +
        '<p id="b">Never deploy on a Friday afternoon, unless the release is a rollback.</p>',
    ),
    (p) => {
      const sentence = { id: 's1', text: 'Never deploy on a Friday afternoon.' };
      const root = p.document.getElementById('a');
      const ctx = p.evaluate('createSentenceMatchContext()');

      p.call('applySentenceAnchor', sentence, root);
      p.call('applyDuplicateSentenceAnchors', sentence, root, ctx);

      assert.ok(
        !p.document.getElementById('b').classList.contains('era-page-anchor-block'),
        'only an exact full-text repeat counts as a duplicate',
      );
    },
  );
});

// --- Vocabulary highlighting ------------------------------------------------

test('highlightTextInElement: marks every occurrence and preserves the text', async () => {
  await withPage(
    page('<p id="p">Cache the cache so the cache stays warm for the next cache lookup.</p>'),
    (p) => {
      const element = p.document.getElementById('p');
      const before = element.textContent;

      p.call('highlightTextInElement', element, 'cache', 'item-1');

      const marks = vocabularyMarks(element);
      assert.equal(marks.length, 3);
      for (const mark of marks) {
        assert.equal(mark.textContent, 'cache');
        assert.equal(mark.dataset.eraStudyItemId, 'item-1');
      }
      assert.equal(element.textContent, before, 'page text must be unchanged');
    },
  );
});

test('highlightTextInElement: matching is case sensitive', async () => {
  // Documented CURRENT behaviour. findNeedleInText() locates a single-word
  // needle with a case-sensitive indexOf; only its multi-word fallback is
  // case-insensitive. So a vocabulary item never highlights where the article
  // capitalizes it — typically the sentence-initial occurrence.
  await withPage(page('<p id="p">Cache the cache so the cache stays warm.</p>'), (p) => {
    const element = p.document.getElementById('p');

    p.call('highlightTextInElement', element, 'cache', 'item-1');

    const marks = vocabularyMarks(element);
    assert.equal(marks.length, 2, "the capitalized 'Cache' is not matched by 'cache'");
    assert.ok(marks.every((mark) => mark.textContent === 'cache'));
  });
});

test('highlightTextInElement: terminates instead of re-entering its own marks', async () => {
  // The loop walks the element again after each insertion. isHighlightableTextNode
  // must reject text already inside a mark, or this would never return.
  await withPage(page('<p id="p">word word word word word word.</p>'), (p) => {
    const element = p.document.getElementById('p');
    const before = element.textContent;

    p.call('highlightTextInElement', element, 'word', 'item-1');

    assert.equal(vocabularyMarks(element).length, 6);
    assert.equal(element.textContent, before);
  });
});

test('highlightTextInElement: does not mark inside an existing sentence mark', async () => {
  await withPage(page('<p id="p">The cache warms up quickly on restart.</p>'), (p) => {
    const element = p.document.getElementById('p');

    p.call('highlightSentenceInElement', element, 'The cache warms up quickly on restart.', 's1');
    p.call('highlightTextInElement', element, 'cache', 'item-1');

    assert.equal(
      vocabularyMarks(element).length,
      0,
      'text already claimed by a sentence mark is off limits',
    );
  });
});

test('highlightTextInElement: marks a multi-word phrase across inline markup', async () => {
  await withPage(
    page('<p id="p">Use the <em>retry</em> budget carefully in production code.</p>'),
    (p) => {
      const element = p.document.getElementById('p');
      const before = element.textContent;

      p.call('highlightTextInElement', element, 'budget carefully', 'item-1');

      const marks = vocabularyMarks(element);
      assert.equal(marks.length, 1);
      assert.equal(marks[0].textContent, 'budget carefully');
      assert.equal(element.textContent, before);
    },
  );
});

test('highlightTextInElement: leaves the DOM alone when the phrase is absent', async () => {
  await withPage(page('<p id="p">Nothing here matches the needle.</p>'), (p) => {
    const element = p.document.getElementById('p');
    const before = element.innerHTML;

    p.call('highlightTextInElement', element, 'absent phrase', 'item-1');

    assert.equal(vocabularyMarks(element).length, 0);
    assert.equal(element.innerHTML, before);
  });
});

// --- Text-node collection ---------------------------------------------------

test('collectHighlightableTextSegments: returns visible text nodes in document order', async () => {
  await withPage(
    page('<div id="d">Alpha <em>Bravo</em> Charlie<script>"Delta"</script></div>'),
    (p) => {
      // Results cross the vm-context boundary, so rebuild them as plain host
      // values before deep-equality assertions.
      const segments = [
        ...p.call('collectHighlightableTextSegments', p.document.getElementById('d')),
      ];

      assert.deepEqual(
        segments.map((segment) => segment.text),
        ['Alpha ', 'Bravo', ' Charlie'],
        'script text must not be offered for highlighting',
      );
    },
  );
});

test('collectHighlightableTextSegments: returns nothing for a non-node argument', async () => {
  await withPage(page('<p>Anything.</p>'), (p) => {
    assert.equal(p.call('collectHighlightableTextSegments', null).length, 0);
    assert.equal(p.call('collectHighlightableTextSegments', 'not a node').length, 0);
  });
});
