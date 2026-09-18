// Reading panel view: renders sentence/vocabulary explanations inside
// sidepanel.html and keeps the page highlights in sync through the
// background service worker. Depends on settings.js and shared.js.
(function () {
  let activePreload = null;
  let activePageUrl = '';
  let activePageTitle = '';
  let activeReadingOwner = null;
  let sentenceDomLinks = new Map();
  let activeSentenceId = null;
  let hoveredSentenceId = null;
  let activeSentenceScreen = 'list';
  let panelTheme = 'light';
  // Identifies the utterance currently playing, e.g. `sentence:<id>` or
  // `study:<id>`; null when nothing is being read aloud.
  let speakingKey = null;
  const accordionAnimations = new WeakMap();
  const ACCORDION_DURATION_MS = 220;

  function getReadingRoot() {
    return document.getElementById(READING_PANEL_ROOT_ID);
  }

  function prefersReducedMotion() {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true;
  }

  function clearAccordionStyles(content) {
    content.style.height = '';
    content.style.opacity = '';
    content.style.overflow = '';
    content.style.transform = '';
    content.style.transition = '';
  }

  function animateAccordionContent(
    content,
    { expand, container = content.parentElement, onFinish = () => {} },
  ) {
    if (!content) return;

    const previous = accordionAnimations.get(content);
    let startHeight = 0;
    if (previous) {
      window.clearTimeout(previous.timeoutId);
      const computed = window.getComputedStyle(content);
      content.style.transition = 'none';
      content.style.height = computed.height;
      content.style.opacity = computed.opacity;
      content.style.transform = computed.transform === 'none' ? '' : computed.transform;
      startHeight = Number.parseFloat(computed.height) || 0;
    }

    container?.classList.add('era-accordion-animating');
    const finish = () => {
      if (accordionAnimations.get(content)?.finish !== finish) return;
      accordionAnimations.delete(content);
      clearAccordionStyles(content);
      container?.classList.remove('era-accordion-animating');
      onFinish();
    };

    if (prefersReducedMotion()) {
      accordionAnimations.set(content, { finish, timeoutId: null });
      finish();
      return;
    }

    if (!previous && !expand) {
      startHeight = content.getBoundingClientRect().height;
    }
    content.style.height = `${startHeight}px`;
    content.style.overflow = 'hidden';
    content.style.transition = 'none';
    if (expand) {
      content.style.opacity = '0';
      content.style.transform = 'translateY(-4px)';
    } else {
      content.style.opacity = window.getComputedStyle(content).opacity;
      content.style.transform =
        window.getComputedStyle(content).transform === 'none'
          ? 'translateY(0)'
          : window.getComputedStyle(content).transform;
    }
    void content.offsetHeight;
    content.style.transition = `height ${ACCORDION_DURATION_MS}ms ease, opacity ${ACCORDION_DURATION_MS}ms ease, transform ${ACCORDION_DURATION_MS}ms ease`;
    content.style.height = expand ? `${content.scrollHeight}px` : '0px';
    content.style.opacity = expand ? '1' : '0';
    content.style.transform = expand ? 'translateY(0)' : 'translateY(-4px)';

    const timeoutId = window.setTimeout(finish, ACCORDION_DURATION_MS + 20);
    accordionAnimations.set(content, { finish, timeoutId });
  }

  function bindSummaryAccordion(panel) {
    const accordion = panel.querySelector('.era-panel-summary-accordion');
    const toggle = accordion?.querySelector('.era-panel-summary-toggle');
    const content = accordion?.querySelector('.era-panel-summary');
    if (!accordion || !toggle || !content) return;

    let requestedOpen = accordion.open;
    let ignoreNextInternalToggle = false;
    const setOpenInternally = (open) => {
      if (accordion.open === open) return;
      ignoreNextInternalToggle = true;
      accordion.open = open;
    };
    const requestState = (expand) => {
      requestedOpen = expand;
      if (expand) {
        setOpenInternally(true);
      }
      animateAccordionContent(content, {
        expand,
        container: accordion,
        onFinish: () => {
          if (expand) return;
          setOpenInternally(false);
        },
      });
    };

    accordion.addEventListener('toggle', () => {
      if (ignoreNextInternalToggle) {
        ignoreNextInternalToggle = false;
        return;
      }
      if (accordion.open !== requestedOpen) {
        requestState(accordion.open);
      }
    });

    toggle.addEventListener('click', (event) => {
      event.preventDefault();
      requestState(!requestedOpen);
    });
  }

  function requestPageFocus(payload) {
    const tabId = typeof getActiveContentTabId === 'function' ? getActiveContentTabId() : null;
    chrome.runtime
      .sendMessage({
        type: 'PAGE_FOCUS_REQUEST',
        payload: { ...payload, pageUrl: activePageUrl, tabId },
      })
      .catch(() => {});
  }

  function notifyPageState({ persist = true } = {}) {
    if (persist) {
      persistReadingUiState();
    }
    chrome.runtime
      .sendMessage({
        type: 'PAGE_HIGHLIGHT_STATE',
        payload: {
          pageUrl: activePageUrl,
          activeSentenceId,
          hoveredSentenceId,
        },
      })
      .catch(() => {});
  }

  async function persistReadingUiState() {
    const pageUrl = activePageUrl;
    const owner = activeReadingOwner;
    const ui = {
      activeSentenceId,
      hoveredSentenceId,
      activeSentenceScreen,
    };
    if (!pageUrl || !isAuthScope(owner)) return;

    const session = await getReadingSession(pageUrl, owner);
    if (
      !session ||
      !pageUrlsMatch(session.pageUrl, pageUrl) ||
      !authScopesMatch(activeReadingOwner, owner) ||
      !pageUrlsMatch(activePageUrl, pageUrl)
    ) {
      return;
    }

    await setReadingSession(
      {
        ...session,
        ui: { ...session.ui, ...ui },
        updatedAt: Date.now(),
      },
      owner,
    );
  }

  function domLinksFromStatus(domLinkStatus = {}) {
    const map = new Map();
    for (const sentence of activePreload?.sentences || []) {
      map.set(sentence.id, Boolean(domLinkStatus[sentence.id]));
    }
    return map;
  }

  function isSentenceLinked(sentenceId) {
    return Boolean(sentenceDomLinks.get(sentenceId));
  }

  function canSpeakText() {
    return (
      typeof window !== 'undefined' &&
      'speechSynthesis' in window &&
      'SpeechSynthesisUtterance' in window
    );
  }

  function stopSpeaking() {
    if (canSpeakText()) {
      window.speechSynthesis.cancel();
    }
    speakingKey = null;
    updateSpeechButtonStates();
  }

  // Reads `text` aloud. `lang` overrides the voice per item (used by the
  // cross-article vocabulary book); otherwise the mounted article's target
  // language is used. Triggering the same `key` again while it is playing
  // stops playback (toggle).
  function speakText(key, text, lang = '') {
    if (!key || !text || !canSpeakText()) return;

    pauseAudioReading({ persist: false });

    if (speakingKey === key && window.speechSynthesis.speaking) {
      stopSpeaking();
      return;
    }

    window.speechSynthesis.cancel();
    speakingKey = key;

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = getTtsLangTag(lang || activePreload?.target_language || 'en');
    utterance.rate = 0.95;
    utterance.onend = () => {
      if (speakingKey === key) {
        speakingKey = null;
        updateSpeechButtonStates();
      }
    };
    utterance.onerror = utterance.onend;

    updateSpeechButtonStates();
    window.speechSynthesis.speak(utterance);
  }

  function renderSpeakIcon(isSpeaking) {
    // Playing: a stop square makes "tap to stop" unambiguous. Resting: a
    // speaker glyph reads as "audio" and never as navigation (unlike the old
    // play triangle, which collided with the list's drill-in affordance).
    if (isSpeaking) {
      return `
      <svg class="era-speak-svg" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
        <rect x="5.5" y="5.5" width="9" height="9" rx="1.5" fill="currentColor"></rect>
      </svg>
    `;
    }

    return `
    <svg class="era-speak-svg" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path d="M4 8v4h2.5L10 15V5L6.5 8H4z" fill="currentColor"></path>
      <path d="M12.5 7.6a3.4 3.4 0 0 1 0 4.8" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"></path>
      <path d="M14.4 5.6a6 6 0 0 1 0 8.8" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"></path>
    </svg>
  `;
  }

  // --- Continuous read-aloud (audio reading mode) ------------------------------
  // Plays the article sentence by sentence; the current sentence follows along
  // as the active highlight in the panel list and on the page. Pausing keeps
  // the position; resuming restarts the current sentence (useful for
  // re-listening). The `generation` token invalidates utterance callbacks from
  // cancelled runs.

  const audioReader = { active: false, index: 0, rate: 1.0, generation: 0 };

  function resetAudioReader() {
    audioReader.active = false;
    audioReader.index = 0;
    audioReader.generation += 1;
  }

  function audioSentenceCount() {
    return activePreload?.sentences?.length || 0;
  }

  function pauseAudioReading({ persist = true } = {}) {
    if (!audioReader.active) return;
    audioReader.active = false;
    audioReader.generation += 1;
    if (canSpeakText()) {
      window.speechSynthesis.cancel();
    }
    updateAudioBar();
    if (persist) {
      persistReadingUiState();
    }
  }

  function startAudioReading() {
    if (!audioSentenceCount() || !canSpeakText()) return;

    stopSpeaking();
    if (activeSentenceId) {
      const current = findSentenceById(activePreload, activeSentenceId);
      if (current) {
        audioReader.index = current.index;
      }
    }
    audioReader.index = Math.min(Math.max(audioReader.index, 0), audioSentenceCount() - 1);
    audioReader.active = true;
    playCurrentAudioSentence();
  }

  function playCurrentAudioSentence() {
    const sentence = activePreload?.sentences?.[audioReader.index];
    if (!sentence) {
      pauseAudioReading();
      return;
    }

    const generation = ++audioReader.generation;
    window.speechSynthesis.cancel();

    // Follow along in the panel and on the page (no storage writes per
    // sentence; the position persists once on pause/stop).
    activeSentenceId = sentence.id;
    updatePanelSentenceHighlights();
    scrollPanelSentenceIntoView(sentence.id);
    requestPageFocus({ type: 'sentence', sentenceId: sentence.id, scroll: true });
    notifyPageState({ persist: false });

    const utterance = new SpeechSynthesisUtterance(sentence.text);
    utterance.lang = getTtsLangTag(activePreload?.target_language || 'en');
    utterance.rate = audioReader.rate;
    const advance = () => {
      if (!audioReader.active || audioReader.generation !== generation) return;
      if (audioReader.index + 1 >= audioSentenceCount()) {
        pauseAudioReading();
        return;
      }
      audioReader.index += 1;
      playCurrentAudioSentence();
    };
    utterance.onend = advance;
    utterance.onerror = advance;
    window.speechSynthesis.speak(utterance);
    updateAudioBar();
  }

  function jumpAudioReadingTo(index) {
    audioReader.index = Math.min(Math.max(index, 0), Math.max(audioSentenceCount() - 1, 0));
    if (audioReader.active) {
      playCurrentAudioSentence();
    } else {
      updateAudioBar();
    }
  }

  function stepAudioReading(delta) {
    jumpAudioReadingTo(audioReader.index + delta);
  }

  function setAudioReadingRateValue(rate) {
    audioReader.rate = Number(rate) || 1.0;
    if (typeof setAudioReadingRate === 'function') {
      setAudioReadingRate(audioReader.rate).catch(() => {});
    }
    if (audioReader.active) {
      playCurrentAudioSentence();
    }
  }

  function renderAudioPlayIcon(playing) {
    if (playing) {
      return `
      <svg class="era-audio-svg" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
        <rect x="5" y="4.5" width="3.4" height="11" rx="1.2" fill="currentColor"></rect>
        <rect x="11.6" y="4.5" width="3.4" height="11" rx="1.2" fill="currentColor"></rect>
      </svg>
    `;
    }
    return `
    <svg class="era-audio-svg" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path d="M6.5 4.8v10.4c0 .7.76 1.12 1.35.74l8.1-5.2a.88.88 0 0 0 0-1.48l-8.1-5.2a.88.88 0 0 0-1.35.74z" fill="currentColor"></path>
    </svg>
  `;
  }

  function renderAudioBar() {
    const total = audioSentenceCount();
    const isSupported = canSpeakText();
    const label = audioReader.active ? t('audioPause') : t('audioPlay');
    const rates = AUDIO_READING_RATES.map(
      (rate) =>
        `<option value="${rate}" ${rate === audioReader.rate ? 'selected' : ''}>${rate}x</option>`,
    ).join('');

    return `
    <div class="era-audio-bar" role="group" aria-label="${escapeHtml(t('audioPlay'))}">
      <div class="era-audio-playback">
        <button
          class="era-audio-play ${audioReader.active ? 'era-audio-playing' : ''}"
          type="button"
          aria-label="${escapeHtml(label)}"
          title="${escapeHtml(label)}"
          ${isSupported ? '' : 'disabled'}
        >${renderAudioPlayIcon(audioReader.active)}</button>
        <select class="era-audio-rate era-select" aria-label="rate">${rates}</select>
      </div>
      <span class="era-audio-position">${audioReader.index + 1} / ${total}</span>
    </div>
  `;
  }

  function updateAudioBar() {
    const root = getReadingRoot();
    const bar = root?.querySelector('.era-audio-bar');
    if (!bar) return;

    const play = bar.querySelector('.era-audio-play');
    if (play) {
      const label = audioReader.active ? t('audioPause') : t('audioPlay');
      play.classList.toggle('era-audio-playing', audioReader.active);
      play.innerHTML = renderAudioPlayIcon(audioReader.active);
      play.setAttribute('aria-label', label);
      play.setAttribute('title', label);
    }
    const position = bar.querySelector('.era-audio-position');
    if (position) {
      position.textContent = `${audioReader.index + 1} / ${audioSentenceCount()}`;
    }
    const rate = bar.querySelector('.era-audio-rate');
    if (rate) {
      rate.value = String(audioReader.rate);
      window.SelectUI?.refresh(rate);
    }
  }

  function bindAudioBarEvents(panel) {
    const bar = panel.querySelector('.era-audio-bar');
    if (!bar) return;

    bar.querySelector('.era-audio-play')?.addEventListener('click', () => {
      if (audioReader.active) {
        pauseAudioReading();
      } else {
        startAudioReading();
      }
    });
    // Sentence stepping has no on-screen buttons on the list view (tap a
    // sentence directly, or use the left/right arrow keys); the audio bar
    // shows only playback + speed and the current position.
    bar.querySelector('.era-audio-rate')?.addEventListener('change', (event) => {
      setAudioReadingRateValue(event.target.value);
    });
  }

  // Renders a read-aloud toggle. `key` scopes the playing state, `text` is
  // spoken, and `label` is the resting accessible label (swapped for a stop
  // label while playing). `extraClass` adds layout-specific styling and
  // `lang` pins the voice for this item.
  function renderSpeakButton({ key, text, label, extraClass = '', lang = '' }) {
    const isSupported = canSpeakText();
    const isSpeaking = speakingKey === key;
    const currentLabel = isSpeaking ? t('speakStop') : label;
    const classes = [
      'era-sentence-speak-button',
      extraClass,
      isSpeaking ? 'era-sentence-speaking' : '',
    ]
      .filter(Boolean)
      .join(' ');

    return `
    <button
      class="${classes}"
      type="button"
      data-speak-key="${escapeHtml(key)}"
      data-speak-text="${escapeHtml(text)}"
      data-speak-label="${escapeHtml(label)}"
      ${lang ? `data-speak-lang="${escapeHtml(lang)}"` : ''}
      aria-label="${escapeHtml(currentLabel)}"
      title="${escapeHtml(currentLabel)}"
      ${isSupported ? '' : 'disabled'}
    >
      <span class="era-speak-icon">${renderSpeakIcon(isSpeaking)}</span>
    </button>
  `;
  }

  function renderSpeakSentenceButton(sentence) {
    return renderSpeakButton({
      key: `sentence:${sentence.id}`,
      text: sentence.text,
      label: t('speakSentence'),
    });
  }

  async function mountReadingPanel(session) {
    if (!session?.preload?.sentences?.length) {
      console.warn('[Untangle] mountReadingPanel skipped: no sentences in session');
      clearReadingPanel();
      return false;
    }

    try {
      activePreload = session.preload;
      activePageUrl = session.pageUrl;
      activePageTitle = session.pageTitle || '';
      activeReadingOwner = isAuthScope(session.owner)
        ? { userId: session.owner.userId, loginId: session.owner.loginId }
        : null;
      sentenceDomLinks = domLinksFromStatus(session.domLinkStatus);

      const ui = session.ui || {};
      activeSentenceId = ui.activeSentenceId || null;
      hoveredSentenceId = ui.hoveredSentenceId || null;
      activeSentenceScreen = ui.activeSentenceScreen || 'list';

      if (typeof getPanelTheme === 'function') {
        panelTheme = await getPanelTheme();
      }

      resetAudioReader();
      if (typeof getAudioReadingRate === 'function') {
        try {
          audioReader.rate = await getAudioReadingRate();
        } catch {
          // Keep the default rate.
        }
      }

      // The panel renders in the learner's native (explanation) language.
      if (typeof getLanguageProfile === 'function') {
        try {
          setUiLocale((await getLanguageProfile()).native);
        } catch {
          // Keep the current locale when the profile is unavailable.
        }
      }

      const root = getReadingRoot();
      if (!root) {
        console.warn('[Untangle] mountReadingPanel: #readingPanelRoot not found');
        return false;
      }

      root.hidden = false;
      root.className = 'era-reading-panel-root';
      root.innerHTML = renderReadingPanelMarkup(activePreload, sentenceDomLinks);
      root.dataset.preloadId = activePreload.id;
      applyPanelTheme(root);
      bindPanelEvents(root);
      bindPanelKeyboardNavigation();

      if (activeSentenceId && activeSentenceScreen === 'detail') {
        const sentence = findSentenceById(activePreload, activeSentenceId);
        if (sentence) {
          renderPanelDetailView();
          updatePanelScreenMode(root);
        }
      }

      updatePanelSentenceHighlights();
      notifyPageState({ persist: false });
      return true;
    } catch (error) {
      console.error('[Untangle] mountReadingPanel failed:', error);
      clearReadingPanel();
      return false;
    }
  }

  function clearReadingPanel() {
    resetAudioReader();
    stopSpeaking();
    const root = getReadingRoot();
    if (root) {
      root.hidden = true;
      root.innerHTML = '';
      delete root.dataset.preloadId;
      root.className = '';
    }
    activePreload = null;
    activePageUrl = '';
    activePageTitle = '';
    activeReadingOwner = null;
    sentenceDomLinks = new Map();
    activeSentenceId = null;
    hoveredSentenceId = null;
    activeSentenceScreen = 'list';
    clearContextChats();
  }

  // Each i18n meta phrase carries a leading " · " so the values read as one
  // sentence in locales that still concatenate them. The panel renders them as
  // discrete chips instead, so strip any leading separator before standalone use.
  function cleanMetaSegment(text) {
    return text.replace(/^[\s·・]+/, '').trim();
  }

  // Build the meta row as an ordered list of independent phrases (sync status,
  // vocabulary, learner level, truncation notice). Chips wrap onto a second line
  // when the panel is narrow instead of crowding into a single dense string.
  function buildPanelMetaSegments(preload, linkedCount) {
    const studyItems = preload.study_items || [];
    const coverage = preload.vocabulary_coverage;
    const segments = [t('metaSync', { linked: linkedCount, total: preload.sentences.length })];

    if (coverage) {
      segments.push(
        t('metaVocabCoverage', {
          count: coverage.item_count,
          percent: coverage.coverage_percent,
        }),
      );
    } else if (studyItems.length) {
      segments.push(t('metaVocab', { count: studyItems.length }));
    }

    if (preload.learner_level) {
      segments.push(t('metaLevel', { level: preload.learner_level }));
    }

    // Plan-cap truncation: tell the reader when a long article was only
    // partially analyzed (the per-plan sentence limit applied).
    if (
      preload.sentences_detected &&
      preload.sentence_limit &&
      preload.sentences_detected > preload.sentences.length
    ) {
      segments.push(
        t('metaTruncated', {
          analyzed: preload.sentences.length,
          detected: preload.sentences_detected,
        }),
      );
    }

    return segments.map(cleanMetaSegment).filter(Boolean);
  }

  function renderPanelMetaItems(segments) {
    return segments
      .map((segment) => `<span class="era-panel-meta-item">${escapeHtml(segment)}</span>`)
      .join('');
  }

  function renderReadingPanelMarkup(preload, domLinks) {
    const linkedCount = [...domLinks.values()].filter(Boolean).length;

    return `
    <div class="era-panel-header">
      <div>
        <p class="era-panel-label">Untangle</p>
        <h2 class="era-panel-title">${escapeHtml(t('panelTitle'))}</h2>
      </div>
      <div class="era-panel-header-actions"></div>
    </div>
    <details class="era-panel-summary-accordion">
      <summary class="era-panel-summary-toggle">${escapeHtml(t('summaryToggle'))}</summary>
      <p class="era-panel-summary">${escapeHtml(preload.summary || '')}</p>
    </details>
    <div class="era-panel-meta">${renderPanelMetaItems(buildPanelMetaSegments(preload, linkedCount))}</div>
    ${renderAudioBar()}
    <div class="era-panel-body era-panel-body-sentence">
      <div class="era-panel-detail">${renderPanelSentenceListView(preload)}</div>
    </div>
  `;
  }

  function renderPanelSentenceListView(preload) {
    const sentences = preload?.sentences || [];
    if (!sentences.length) {
      return renderPanelDetailEmpty();
    }

    const items = sentences
      .map((sentence) => {
        const isLinked = isSentenceLinked(sentence.id);
        const linkClass = isLinked ? 'era-sentence-linked' : 'era-sentence-unlinked';
        const linkLabel = isLinked ? t('sentenceLinked') : t('sentenceUnlinked');
        const isActive = sentence.id === activeSentenceId;
        const isHover = sentence.id === hoveredSentenceId && !isActive;
        const itemClasses = [
          'era-sentence-item',
          isActive ? 'era-sentence-item-active' : '',
          isHover ? 'era-sentence-item-hover' : '',
        ]
          .filter(Boolean)
          .join(' ');
        const buttonClasses = [
          'era-sentence-button',
          linkClass,
          isActive ? 'era-sentence-active' : '',
          isHover ? 'era-sentence-hover' : '',
        ]
          .filter(Boolean)
          .join(' ');

        return `
        <li class="${itemClasses}" data-sentence-id="${escapeHtml(sentence.id)}">
          <button
            class="${buttonClasses}"
            type="button"
            data-sentence-id="${escapeHtml(sentence.id)}"
            title="${escapeHtml(linkLabel)}"
          >
            <span class="era-sentence-index">${sentence.index + 1}</span>
            <span class="era-sentence-text">${escapeHtml(sentence.text)}</span>
            <span class="era-sentence-link-icon ${isLinked ? 'is-linked' : 'is-unlinked'}" aria-hidden="true"></span>
          </button>
        </li>
      `;
      })
      .join('');

    return `
    <p class="era-panel-reading-hint">${escapeHtml(t('readingHint'))}</p>
    <ul class="era-sentence-list era-sentence-reading-list">${items}</ul>
  `;
  }

  function renderPanelSentenceDetailView(sentence) {
    const total = activePreload?.sentences?.length || 0;
    const previousSentence = getAdjacentSentence(activePreload, sentence, 'prev');
    const nextSentence = getAdjacentSentence(activePreload, sentence, 'next');

    return `
    <div class="era-panel-detail-view">
      <div class="era-panel-detail-toolbar">
        <button class="era-panel-back-button" type="button">${escapeHtml(t('backToList'))}</button>
        <div class="era-panel-detail-nav">
          <button
            class="era-panel-nav-button"
            type="button"
            data-nav="prev"
            title="${escapeHtml(t('navPrevTitle'))}"
            ${previousSentence ? '' : 'disabled'}
          > <span class="era-chevron era-chevron-left" aria-hidden="true"></span>${escapeHtml(t('navPrev'))}</button>
          <span class="era-panel-detail-position">${sentence.index + 1} / ${total}</span>
          <button
            class="era-panel-nav-button"
            type="button"
            data-nav="next"
            title="${escapeHtml(t('navNextTitle'))}"
            ${nextSentence ? '' : 'disabled'}
          >${escapeHtml(t('navNext'))}<span class="era-chevron era-chevron-right" aria-hidden="true"></span></button>
        </div>
      </div>
      ${renderPanelDetailContent(sentence)}
    </div>
  `;
  }

  function applyPanelTheme(panel) {
    delete document.documentElement.dataset.eraPanelTheme;

    // Theme the whole side panel document (settings, word book, empty states)
    // through :root[data-theme], not just the reading panel subtree.
    document.documentElement.dataset.theme = panelTheme;

    if (!panel) return;

    panel.dataset.eraTheme = panelTheme;
  }

  function renderPanelDetailEmpty() {
    return `
    <div class="era-panel-detail-empty">
      <p>${escapeHtml(t('detailEmpty'))}</p>
    </div>
  `;
  }

  // Read-aloud button used in place of the bullet for each vocabulary line in
  // a sentence's explanation. Keyed by sentence + index so playback state stays
  // unique across sentences.
  function renderVocabLineSpeakPrefix(sentenceId, term, index) {
    if (!term) return '';
    return renderSpeakButton({
      key: `vocab:${sentenceId}:${index}`,
      text: term,
      label: t('speakTerm'),
      extraClass: 'era-vocab-speak',
    });
  }

  function renderPanelDetailContent(sentence) {
    const analysis = toAnalysisResponse(sentence);

    return `
    <div class="era-panel-detail-inner">
      <div class="era-section era-section-original">
        <div class="era-section-head">
          <h3>${escapeHtml(t('sectionOriginal'))}</h3>
          ${renderSpeakSentenceButton(sentence)}
        </div>
        <p>${escapeHtml(sentence.text)}</p>
      </div>
      ${renderAnalysis(analysis, {
        renderVocabPrefix: (term, index) => renderVocabLineSpeakPrefix(sentence.id, term, index),
      })}
      ${renderContextChat(getSentenceChatKey(sentence.id), { quickActions: SENTENCE_QUICK_CHAT_ACTIONS })}
    </div>
  `;
  }

  function isPanelDetailNavigationActive() {
    return activeSentenceScreen === 'detail' && Boolean(activeSentenceId);
  }

  function navigatePanelDetailAdjacent(direction) {
    if (activeSentenceScreen === 'detail' && activeSentenceId) {
      const adjacent = getAdjacentSentence(
        activePreload,
        findSentenceById(activePreload, activeSentenceId),
        direction,
      );
      if (!adjacent) return false;
      selectSentenceInPanel(adjacent, { scrollPage: true });
      return true;
    }

    return false;
  }

  function handlePanelDetailKeydown(event) {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
    if (isKeyboardEditableTarget(event.target)) return;

    let direction = null;
    if (event.key === 'ArrowLeft' || event.key === '[') direction = 'prev';
    if (event.key === 'ArrowRight' || event.key === ']') direction = 'next';
    if (!direction) return;

    if (audioReader.active) {
      stepAudioReading(direction === 'prev' ? -1 : 1);
      event.preventDefault();
      return;
    }

    if (!isPanelDetailNavigationActive()) return;
    if (navigatePanelDetailAdjacent(direction)) {
      event.preventDefault();
    }
  }

  let panelKeyboardBound = false;

  function bindPanelKeyboardNavigation() {
    if (panelKeyboardBound) return;
    panelKeyboardBound = true;
    document.addEventListener('keydown', handlePanelDetailKeydown);
  }

  function selectSentenceInPanel(sentence, { scrollPage = true } = {}) {
    if (!sentence) return;

    if (audioReader.active) {
      jumpAudioReadingTo(sentence.index);
      return;
    }

    activeSentenceScreen = 'detail';
    activeSentenceId = sentence.id;
    if (scrollPage) {
      requestPageFocus({ type: 'sentence', sentenceId: sentence.id, scroll: true });
    } else {
      notifyPageState();
    }

    renderPanelDetailView();
    updatePanelScreenMode(getReadingRoot());
    notifyPageState();
  }

  function showSentenceListInPanel() {
    activeSentenceScreen = 'list';
    renderPanelDetailView();
    updatePanelScreenMode(getReadingRoot());
    if (activeSentenceId) {
      scrollPanelSentenceIntoView(activeSentenceId);
    }
    notifyPageState();
  }

  function updatePanelScreenMode(panel) {
    panel?.classList.toggle('era-panel-sentence-detail-mode', activeSentenceScreen === 'detail');
  }

  function scrollPanelSentenceIntoView(sentenceId) {
    if (!sentenceId) return;
    const item = document.querySelector(
      `#${READING_PANEL_ROOT_ID} .era-sentence-item[data-sentence-id="${CSS.escape(sentenceId)}"]`,
    );
    item?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function updatePanelSentenceHighlights() {
    const panel = getReadingRoot();
    if (!panel || activeSentenceScreen !== 'list') return;

    panel.querySelectorAll('.era-sentence-item').forEach((item) => {
      const sentenceId = item.dataset.sentenceId;
      const isLinked = isSentenceLinked(sentenceId);
      const isActive = sentenceId === activeSentenceId;
      const isHover = sentenceId === hoveredSentenceId && !isActive;

      item.classList.toggle('era-sentence-item-active', isActive);
      item.classList.toggle('era-sentence-item-hover', isHover);

      const button = item.querySelector('.era-sentence-button');
      if (!button) return;

      button.classList.toggle('era-sentence-active', isActive);
      button.classList.toggle('era-sentence-hover', isHover);
      button.classList.toggle('era-sentence-linked', isLinked);
      button.classList.toggle('era-sentence-unlinked', !isLinked);
      button.title = isLinked ? t('sentenceLinked') : t('sentenceUnlinked');
      const icon = button.querySelector('.era-sentence-link-icon');
      if (icon) {
        icon.classList.toggle('is-linked', isLinked);
        icon.classList.toggle('is-unlinked', !isLinked);
      }
    });
  }

  function renderPanelDetailView() {
    const panel = getReadingRoot();
    const detail = panel?.querySelector('.era-panel-detail');
    if (!detail) return;

    if (!activePreload?.sentences?.length) {
      detail.innerHTML = renderPanelDetailEmpty();
      updatePanelScreenMode(panel);
      return;
    }

    if (activeSentenceScreen === 'detail' && activeSentenceId) {
      const sentence = findSentenceById(activePreload, activeSentenceId);
      if (!sentence) {
        activeSentenceScreen = 'list';
      } else {
        detail.innerHTML = renderPanelSentenceDetailView(sentence);
        bindSentenceDetailEvents(detail);
        attachContextChat(detail, {
          chatKey: getSentenceChatKey(sentence.id),
          payload: buildSentenceChatPayload(sentence),
        });
        detail.scrollTop = 0;
        updatePanelScreenMode(panel);
        return;
      }
    }

    activeSentenceScreen = 'list';
    detail.innerHTML = renderPanelSentenceListView(activePreload);
    bindSentenceReadingEvents(detail);
    bindSpeechEvents(detail);

    if (activeSentenceId) {
      scrollPanelSentenceIntoView(activeSentenceId);
    }
    updatePanelScreenMode(panel);
  }

  function bindSentenceDetailEvents(detail) {
    detail
      .querySelector('.era-panel-back-button')
      ?.addEventListener('click', showSentenceListInPanel);
    bindSpeechEvents(detail);

    const currentSentence = findSentenceById(activePreload, activeSentenceId);
    detail.querySelectorAll('.era-panel-nav-button[data-nav]').forEach((button) => {
      button.addEventListener('click', () => {
        if (!currentSentence) return;
        const adjacent = getAdjacentSentence(activePreload, currentSentence, button.dataset.nav);
        if (adjacent) {
          selectSentenceInPanel(adjacent, { scrollPage: true });
        }
      });
    });
  }

  function bindPanelEvents(panel) {
    bindSentenceReadingEvents(panel);
    bindSpeechEvents(panel);
    bindAudioBarEvents(panel);
    bindSummaryAccordion(panel);
    updatePanelScreenMode(panel);
  }

  function bindSentenceReadingEvents(container) {
    container.querySelectorAll('.era-sentence-button').forEach((button) => {
      button.addEventListener('click', () => {
        const sentence = findSentenceById(activePreload, button.dataset.sentenceId);
        if (sentence) {
          selectSentenceInPanel(sentence, { scrollPage: true });
        }
      });

      button.addEventListener('mouseenter', () => {
        hoveredSentenceId = button.dataset.sentenceId;
        updatePanelSentenceHighlights();
        notifyPageState({ persist: false });
      });

      button.addEventListener('mouseleave', (event) => {
        if (event.relatedTarget?.closest(`#${READING_PANEL_ROOT_ID} .era-sentence-button`)) return;
        if (event.relatedTarget?.closest('.era-page-anchor')) return;
        if (hoveredSentenceId === button.dataset.sentenceId) {
          hoveredSentenceId = null;
          notifyPageState({ persist: false });
        }
      });
    });
  }

  function bindSpeechEvents(container) {
    container.querySelectorAll('[data-speak-key]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        speakText(
          button.dataset.speakKey,
          button.dataset.speakText,
          button.dataset.speakLang || '',
        );
      });
    });
  }

  function updateSpeechButtonStates() {
    const root = getReadingRoot();
    if (!root) return;

    root.querySelectorAll('[data-speak-key]').forEach((button) => {
      const isSpeaking = button.dataset.speakKey === speakingKey;
      button.classList.toggle('era-sentence-speaking', isSpeaking);
      const icon = button.querySelector('.era-speak-icon');
      if (icon) {
        icon.innerHTML = renderSpeakIcon(isSpeaking);
      }
      const label = isSpeaking ? t('speakStop') : button.dataset.speakLabel || t('speakGeneric');
      button.setAttribute('aria-label', label);
      button.setAttribute('title', label);
    });
  }

  function buildPanelLanguageFields() {
    return {
      target_language: activePreload?.target_language || null,
      native_language: activePreload?.native_language || null,
    };
  }

  function buildSentenceChatPayload(sentence) {
    return {
      message: '',
      sentence_id: sentence.id,
      context_label: 'sentence',
      context_text: sentence.text,
      context_analysis: sentence.analysis,
      page_preload_id: activePreload?.id || null,
      page_url: activePageUrl,
      page_title: activePageTitle,
      history: [],
      ...buildPanelLanguageFields(),
    };
  }

  function refreshDomLinkStatus(domLinkStatus = {}) {
    if (!activePreload?.sentences?.length) {
      return;
    }

    sentenceDomLinks = domLinksFromStatus(domLinkStatus);
    const root = getReadingRoot();
    if (!root || root.hidden) {
      return;
    }

    const linkedCount = [...sentenceDomLinks.values()].filter(Boolean).length;
    const meta = root.querySelector('.era-panel-meta');
    if (meta) {
      meta.innerHTML = renderPanelMetaItems(buildPanelMetaSegments(activePreload, linkedCount));
    }

    updatePanelSentenceHighlights();
  }

  // Re-render the open sentence detail so quick-action visibility / custom
  // prompts match settings without requiring a full remount.
  function refreshContextChatActions() {
    if (!activePreload || activeSentenceScreen !== 'detail' || !activeSentenceId) {
      return;
    }
    const root = getReadingRoot();
    if (!root) return;
    renderPanelDetailView();
    updatePanelScreenMode(root);
  }

  if (typeof chrome !== 'undefined' && chrome.storage?.onChanged) {
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== 'local') return;
      if (changes[HIDDEN_QUICK_ACTIONS_KEY]) {
        setHiddenQuickActionsCache(changes[HIDDEN_QUICK_ACTIONS_KEY].newValue);
      }
      if (changes[CUSTOM_CHAT_PROMPTS_KEY]) {
        setCustomChatPromptsCache(changes[CUSTOM_CHAT_PROMPTS_KEY].newValue);
      }
      if (changes[HIDDEN_QUICK_ACTIONS_KEY] || changes[CUSTOM_CHAT_PROMPTS_KEY]) {
        refreshContextChatActions();
      }
    });
  }

  window.ReadingPanel = {
    mountReadingPanel,
    clearReadingPanel,
    refreshContextChatActions,
    mountFromPreload: async (preload, pageUrl, pageTitle = '', owner = null) => {
      const rawPageUrl = pageUrl || preload?.page_url || '';
      const normalizedPageUrl =
        typeof normalizePageUrl === 'function' ? normalizePageUrl(rawPageUrl) : rawPageUrl;
      if (!preload?.sentences?.length || !normalizedPageUrl) {
        console.warn('[Untangle] mountFromPreload skipped: missing preload or page URL');
        return false;
      }
      const resolvedOwner = isAuthScope(owner) ? owner : await getAuthScope();
      if (!isAuthScope(resolvedOwner)) {
        return false;
      }

      return mountReadingPanel({
        pageUrl: normalizedPageUrl,
        pageTitle,
        preload,
        owner: resolvedOwner,
        domLinkStatus: {},
        ui: {},
      });
    },
    mountFromStorage: async (expectedPageUrl = '', expectedOwner = null) => {
      const pageUrl = expectedPageUrl || activePageUrl;
      const owner = expectedOwner || (await getAuthScope());
      if (!pageUrl || !isAuthScope(owner)) {
        return false;
      }

      const session = await getReadingSession(pageUrl, owner);
      if (!session?.preload?.sentences?.length) {
        return false;
      }

      if (!pageUrlsMatch(session.pageUrl, pageUrl)) {
        return false;
      }

      return mountReadingPanel(session);
    },
    applyExternalHighlightState: (payload) => {
      if (!payload || !pageUrlsMatch(payload.pageUrl, activePageUrl)) {
        return;
      }
      if (payload.hoveredSentenceId !== undefined) hoveredSentenceId = payload.hoveredSentenceId;
      updatePanelSentenceHighlights();
    },
    applyExternalSelection: (payload) => {
      if (!payload || !pageUrlsMatch(payload.pageUrl, activePageUrl)) {
        return;
      }

      if (payload.type === 'sentence' && payload.sentenceId) {
        const sentence = findSentenceById(activePreload, payload.sentenceId);
        if (!sentence) return;
        if (audioReader.active) {
          jumpAudioReadingTo(sentence.index);
          return;
        }
        activeSentenceScreen = payload.activeSentenceScreen === 'list' ? 'list' : 'detail';
        activeSentenceId = sentence.id;
        renderPanelDetailView();
        updatePanelScreenMode(getReadingRoot());
        updatePanelSentenceHighlights();
      }
    },
    refreshDomLinkStatus,
    // Applies a theme change made in another context (observed through
    // storage.onChanged) to the mounted panel without re-persisting it.
    applyExternalTheme: (theme) => {
      panelTheme = theme === 'dark' ? 'dark' : 'light';
      applyPanelTheme(getReadingRoot());
    },
    // Read-aloud primitives shared with panel views outside the reading panel
    // (the vocabulary book reuses the same buttons, state, and voices).
    renderSpeakButton,
    bindSpeechEvents,
    animateAccordionContent,
    // Re-renders the mounted panel after a native-language change so the UI
    // switches language immediately (the analysis content itself only changes
    // on the next preload).
    applyUiLocale: (locale) => {
      setUiLocale(locale);
      const root = getReadingRoot();
      if (!root || root.hidden || !activePreload) return;
      root.innerHTML = renderReadingPanelMarkup(activePreload, sentenceDomLinks);
      applyPanelTheme(root);
      bindPanelEvents(root);
      renderPanelDetailView();
      updatePanelSentenceHighlights();
    },
  };
})();
