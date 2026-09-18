(() => {
  'use strict';

  const sourceToControl = new WeakMap();
  let activeControl = null;
  let nextId = 0;

  function labelTextFor(select) {
    const label = select.labels?.[0] || select.closest('label');
    const labelCopy = label?.cloneNode(true);
    labelCopy?.querySelectorAll('select, .era-select-control').forEach((source) => source.remove());
    const text = labelCopy?.textContent?.trim();
    return select.getAttribute('aria-label') || text || select.name || 'Select an option';
  }

  function optionText(option) {
    return option.textContent.trim();
  }

  function close(control, restoreFocus = false) {
    if (!control || !control.open) return;
    control.open = false;
    control.trigger.setAttribute('aria-expanded', 'false');
    control.popover.hidden = true;
    if (activeControl === control) activeControl = null;
    if (restoreFocus && !control.trigger.disabled) control.trigger.focus();
  }

  function sync(control) {
    const { select, trigger, options } = control;
    // Callers may replace native option markup synchronously (for example
    // when the learner scale changes). Rebuild the visible list before
    // reading option state so stale controls cannot dereference a removed
    // native option.
    if (options.length !== select.options.length) {
      rebuild(select);
      return;
    }
    const selectedIndex = select.selectedIndex;
    const selected = select.options[selectedIndex];
    const accessibleName = labelTextFor(select);
    if (select.disabled && control.open) close(control, true);
    trigger.disabled = select.disabled;
    trigger.setAttribute('aria-disabled', String(select.disabled));
    trigger.setAttribute('aria-label', accessibleName);
    control.popover.setAttribute('aria-label', accessibleName);
    trigger.querySelector('.era-select-trigger-text').textContent = selected
      ? optionText(selected)
      : '';
    options.forEach((option, index) => {
      const nativeOption = select.options[index];
      const selectedOption = index === selectedIndex;
      option.setAttribute('aria-selected', String(selectedOption));
      option.disabled = nativeOption.disabled;
      option.setAttribute('aria-disabled', String(nativeOption.disabled));
      option.classList.toggle('era-select-option-selected', selectedOption);
    });
  }

  function focusOption(control, index) {
    const enabled = control.options
      .map((option, optionIndex) => ({ option, optionIndex }))
      .filter(({ option }) => !option.disabled);
    if (!enabled.length) return;
    const next =
      enabled.find(({ optionIndex }) => optionIndex === index) ||
      enabled.reduce((closest, candidate) =>
        Math.abs(candidate.optionIndex - index) < Math.abs(closest.optionIndex - index)
          ? candidate
          : closest,
      );
    next.option.focus();
  }

  function open(control) {
    if (control.select.disabled) return;
    if (activeControl && activeControl !== control) close(activeControl);
    control.open = true;
    activeControl = control;
    control.trigger.setAttribute('aria-expanded', 'true');
    control.popover.hidden = false;
    sync(control);
    focusOption(control, control.select.selectedIndex);
  }

  function choose(control, index) {
    const option = control.select.options[index];
    if (control.select.disabled || !option || option.disabled || control.options[index]?.disabled)
      return;
    control.select.selectedIndex = index;
    control.select.dispatchEvent(new Event('change', { bubbles: true }));
    sync(control);
    queueMicrotask(() => {
      if (sourceToControl.get(control.select) === control) sync(control);
    });
    requestAnimationFrame(() => {
      if (sourceToControl.get(control.select) === control) sync(control);
    });
    close(control, true);
  }

  function cleanup(select) {
    const control = sourceToControl.get(select);
    if (!control) return;
    close(control);
    select.removeEventListener('change', control.onChange);
    control.wrapper.remove();
    sourceToControl.delete(select);
  }

  function rebuild(select) {
    cleanup(select);
    upgrade(select);
  }

  function upgrade(select) {
    if (sourceToControl.has(select)) return;

    const id = `era-select-${++nextId}`;
    const wrapper = document.createElement('div');
    wrapper.className = 'era-select-control';
    const trigger = document.createElement('button');
    trigger.className = 'era-select-trigger';
    trigger.type = 'button';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-controls', `${id}-listbox`);
    trigger.setAttribute('aria-label', labelTextFor(select));
    trigger.innerHTML =
      '<span class="era-select-trigger-text"></span><span class="era-select-trigger-icon" aria-hidden="true"></span>';

    const popover = document.createElement('div');
    popover.className = 'era-select-popover';
    popover.id = `${id}-listbox`;
    popover.setAttribute('role', 'listbox');
    popover.setAttribute('aria-label', labelTextFor(select));
    popover.hidden = true;

    const control = { select, wrapper, trigger, popover, options: [], open: false };
    [...select.options].forEach((nativeOption, index) => {
      const option = document.createElement('button');
      option.className = 'era-select-option';
      option.type = 'button';
      option.id = `${id}-option-${index}`;
      option.setAttribute('role', 'option');
      option.tabIndex = -1;
      option.textContent = optionText(nativeOption);
      option.addEventListener('click', () => choose(control, index));
      option.addEventListener('keydown', (event) => {
        const currentIndex = control.options.indexOf(option);
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          const direction = event.key === 'ArrowDown' ? 1 : -1;
          const available = control.options.filter((candidate) => !candidate.disabled);
          const position = available.indexOf(option);
          (
            available[(position + direction + available.length) % available.length] || option
          ).focus();
        } else if (event.key === 'Home' || event.key === 'End') {
          event.preventDefault();
          const available = control.options.filter((candidate) => !candidate.disabled);
          (event.key === 'Home' ? available[0] : available.at(-1))?.focus();
        } else if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          choose(control, currentIndex);
        } else if (event.key === 'Escape') {
          event.preventDefault();
          close(control, true);
        } else if (event.key === 'Tab') {
          close(control);
        }
      });
      popover.append(option);
      control.options.push(option);
    });

    trigger.addEventListener('click', () => (control.open ? close(control) : open(control)));
    trigger.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        open(control);
        const offset = event.key === 'ArrowDown' ? 1 : -1;
        focusOption(control, select.selectedIndex + offset);
      } else if (event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        open(control);
        focusOption(control, event.key === 'Home' ? 0 : control.options.length - 1);
      } else if (event.key === 'Escape') {
        close(control, true);
      }
    });
    control.onChange = () => sync(control);
    select.addEventListener('change', control.onChange);

    select.after(wrapper);
    wrapper.append(trigger, popover);
    select.classList.add('era-select-source');
    select.setAttribute('aria-hidden', 'true');
    select.tabIndex = -1;
    sourceToControl.set(select, control);
    sync(control);
  }

  function upgradeAll(root = document) {
    root.querySelectorAll?.('select.era-select').forEach(upgrade);
    if (root.matches?.('select.era-select')) upgrade(root);
  }

  function upgradedSelectsFor(node, includeAssociatedLabel = false) {
    const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    const select = element?.closest?.('select.era-select.era-select-source');
    if (select && sourceToControl.has(select)) return [select];
    if (!includeAssociatedLabel) return [];
    if (element?.closest?.('.era-select-control')) return [];
    const label = element?.closest?.('label');
    const labeledSelect = label?.control;
    return labeledSelect && sourceToControl.has(labeledSelect) ? [labeledSelect] : [];
  }

  function isInteractiveTarget(target) {
    return Boolean(
      target.closest?.(
        'button, a[href], input, select, textarea, label, [contenteditable="true"], [tabindex]:not([tabindex="-1"])',
      ),
    );
  }

  document.addEventListener(
    'pointerdown',
    (event) => {
      if (!activeControl || activeControl.wrapper.contains(event.target)) return;
      const control = activeControl;
      const targetIsInteractive = isInteractiveTarget(event.target);
      close(control);
      if (!targetIsInteractive) {
        requestAnimationFrame(() => {
          if (!control.open && !isInteractiveTarget(document.activeElement))
            control.trigger.focus();
        });
      } else {
        queueMicrotask(() => {
          if (!control.open && control.wrapper.contains(document.activeElement))
            control.trigger.focus();
        });
      }
    },
    true,
  );

  const pendingRebuilds = new Set();
  const pendingSyncs = new Set();
  let flushScheduled = false;

  function flushMutations() {
    flushScheduled = false;
    for (const select of pendingRebuilds) {
      pendingSyncs.delete(select);
      if (select.isConnected) rebuild(select);
    }
    pendingRebuilds.clear();
    for (const select of pendingSyncs) {
      const control = sourceToControl.get(select);
      if (control) sync(control);
    }
    pendingSyncs.clear();
  }

  function scheduleMutation(select, rebuildRequired) {
    if (rebuildRequired) pendingRebuilds.add(select);
    else if (!pendingRebuilds.has(select)) pendingSyncs.add(select);
    if (!flushScheduled) {
      flushScheduled = true;
      queueMicrotask(flushMutations);
    }
  }

  const observer = new MutationObserver((records) => {
    for (const record of records) {
      record.removedNodes.forEach((node) => {
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        if (node.matches?.('select.era-select.era-select-source')) cleanup(node);
        node.querySelectorAll?.('select.era-select.era-select-source').forEach(cleanup);
      });
      const changedNodes = [...record.addedNodes, ...record.removedNodes];
      const controlOnlyMutation =
        record.type === 'childList' &&
        changedNodes.length > 0 &&
        changedNodes.every(
          (node) =>
            node.nodeType === Node.ELEMENT_NODE && node.classList.contains('era-select-control'),
        );
      const includeAssociatedLabel = record.type !== 'attributes' && !controlOnlyMutation;
      for (const select of upgradedSelectsFor(record.target, includeAssociatedLabel)) {
        const sourceChanged = record.target === select;
        const rebuildRequired =
          record.type === 'childList' || record.type === 'characterData' || !sourceChanged;
        scheduleMutation(select, rebuildRequired);
      }
      record.addedNodes.forEach((node) => {
        if (node.nodeType === Node.ELEMENT_NODE) upgradeAll(node);
      });
    }
  });

  document.addEventListener('DOMContentLoaded', () => {
    upgradeAll();
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['disabled', 'selected', 'value', 'aria-label'],
      characterData: true,
    });
  });

  window.SelectUI = {
    upgradeAll,
    refresh(select) {
      const control = sourceToControl.get(select);
      if (control) sync(control);
    },
  };
})();
