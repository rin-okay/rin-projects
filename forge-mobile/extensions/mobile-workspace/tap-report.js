// Keep a small on-device record of missed taps. The report is readable without
// opening Forge. Only element identifiers and interaction state are recorded.
(async () => {
  'use strict';
  await window.MobileWorkspaceHost.extensions['mobile-workspace'].ready;
  const overlay = document.getElementById('mobile-overlay');
  const upper = document.getElementById('mobile-upper');
  const bar = overlay.querySelector('.mobile-tab-row');
  const scroll = overlay.querySelector('.mobile-settings-scroll');
  const key = 'forge-mobile-missed-taps-v2';
  let pending;
  let latestTap;

  function describe(node) {
    if (!(node instanceof Element)) return '';
    return node.localName + (node.id ? '#' + node.id : '') +
      [...node.classList].slice(0, 3).map(name => '.' + name).join('');
  }

  // Keep the recent event sequence even when a gesture never activates a
  // control. This path is independent of geometric guesses about intent.
  const traceKey = 'forge-mobile-touch-trace-v1';
  let trace = [];
  try { trace = JSON.parse(localStorage.getItem(traceKey) || '[]'); } catch {}
  if (!Array.isArray(trace)) trace = [];
  let writeTimer;
  function flushTrace() {
    clearTimeout(writeTimer);
    writeTimer = null;
    try { localStorage.setItem(traceKey, JSON.stringify(trace)); } catch {}
  }
  function traceEvent(type, event) {
    const point = event?.changedTouches?.[0] || event;
    trace.push({
      build: overlay.dataset.mobileBuild, time: new Date().toISOString(),
      type, tab: overlay.dataset.activeTab, target: describe(event?.target),
      ...(point && Number.isFinite(point.clientX) ? {
        point: [Math.round(point.clientX), Math.round(point.clientY)],
        hit: describe(document.elementFromPoint(point.clientX, point.clientY)),
        delayMs: Math.round(Math.max(0, performance.now() - event.timeStamp))
      } : {})
    });
    if (trace.length > 96) trace.splice(0, trace.length - 96);
    if (!writeTimer) writeTimer = setTimeout(flushTrace, 100);
  }
  traceEvent('recorder ready');
  for (const type of ['touchstart','pointerdown','touchcancel','pointercancel','touchend','pointerup','click']) {
    window.addEventListener(type, event => {
      if (!overlay.hidden) traceEvent(type, event);
    }, { capture: true, passive: true });
  }
  window.addEventListener('pagehide', flushTrace);
  document.addEventListener('visibilitychange', () => { if (document.hidden) flushTrace(); });

  function containsPoint(node, x, y) {
    const r = node.getBoundingClientRect();
    return x >= r.left && x < r.right && y >= r.top && y < r.bottom;
  }

  function viewerOpen() {
    const viewer = document.getElementById('lightboxModal');
    return viewer && viewer.getClientRects().length
      && getComputedStyle(viewer).visibility !== 'hidden';
  }

  function bounds(node) {
    const r = node.getBoundingClientRect();
    return ['x', 'y', 'width', 'height'].map(key => Math.round(r[key] * 100) / 100);
  }

  function expectedControl(x, y) {
    if (!containsPoint(upper, x, y)) return;
    if (containsPoint(bar, x, y)) {
      return [...bar.querySelectorAll('button')].find(button => containsPoint(button, x, y));
    }
    if (overlay.dataset.activeTab === 'prompt' && containsPoint(scroll, x, y)) {
      const field = overlay.querySelector('.prompt-box:not([hidden]) textarea');
      if (field && containsPoint(field, x, y)) return field;
    }
  }

  function record(reason, expected, target, x, y) {
    const entry = {
      build: overlay.dataset.mobileBuild,
      time: new Date().toISOString(), reason, tab: overlay.dataset.activeTab,
      expected: describe(expected), target: describe(target),
      point: [Math.round(x), Math.round(y)],
      layers: document.elementsFromPoint(x, y).slice(0, 5).map(describe),
      resizing: document.body.classList.contains('resizing'),
      focus: describe(document.activeElement),
      uiScale: document.getElementById('mobile-ui-scale').value,
      viewport: {
        width: innerWidth, height: innerHeight,
        visualWidth: window.visualViewport?.width, visualHeight: window.visualViewport?.height,
        scale: window.visualViewport?.scale,
        offsetLeft: window.visualViewport?.offsetLeft, offsetTop: window.visualViewport?.offsetTop
      },
      bounds: { expected: bounds(expected), target: bounds(target), bar: bounds(bar) },
      styles: {
        expectedZoom: getComputedStyle(expected).zoom,
        upperTransform: getComputedStyle(document.getElementById('mobile-upper-content')).transform
      }
    };
    try {
      const history = JSON.parse(localStorage.getItem(key) || '[]');
      localStorage.setItem(key, JSON.stringify([...history.slice(-11), entry]));
    } catch { /* The workspace also works with browser storage disabled. */ }
  }

  window.addEventListener('pointerdown', event => {
    pending = null;
    latestTap = null;
    if (overlay.hidden || viewerOpen() || !event.isPrimary) return;
    const expected = expectedControl(event.clientX, event.clientY);
    if (expected) pending = { expected, target: event.target, id: event.pointerId, x: event.clientX, y: event.clientY };
  }, { capture: true, passive: true });
  window.addEventListener('pointercancel', () => { pending = null; }, true);
  window.addEventListener('pointerup', event => {
    const tap = pending;
    if (!tap || tap.id !== event.pointerId) return;
    pending = null;
    if (Math.hypot(event.clientX - tap.x, event.clientY - tap.y) > 10) return;
    if (!tap.expected.contains(tap.target)) {
      record('Tap landed on another element', tap.expected, tap.target, tap.x, tap.y);
    } else if (tap.expected.matches('[role="tab"]')) {
      setTimeout(() => {
        if (!overlay.hidden && tap.expected.getAttribute('aria-selected') !== 'true' && latestTap === tap) {
          record('Tap reached tab but it did not activate', tap.expected, tap.target, tap.x, tap.y);
        }
      }, 450);
    }
    latestTap = tap;
  }, { capture: true, passive: true });

  // A covering iframe receives its own events. Sample the tab row before
  // leaving the page as well, while its last visible layout is still available.
  function checkTabRow() {
    if (overlay.hidden || viewerOpen()) return;
    for (const button of bar.querySelectorAll('button')) {
      const r = button.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      if (!containsPoint(upper, x, y)) continue;
      const target = document.elementFromPoint(x, y);
      if (target && !button.contains(target)) {
        record('Tab center covered', button, target, x, y);
        break;
      }
    }
  }
  window.addEventListener('pagehide', checkTabRow);
  window.addEventListener('blur', checkTabRow);
  document.addEventListener('visibilitychange', () => { if (document.hidden) checkTabRow(); });
})().catch(error => console.warn('Mobile tap report unavailable', error));
