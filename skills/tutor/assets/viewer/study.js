// Study app — Alpine.js component.

// Stable id per card text (FNV-1a of `q`): the qid of flashcard progress events and
// the key of the known/unknown map, so adding or removing cards never shifts marks.
function cardId(q) {
  q = String(q || '');
  let h = 0x811c9dc5;
  for (let i = 0; i < q.length; i++) h = Math.imul(h ^ q.charCodeAt(i), 0x01000193) >>> 0;
  return `card:${h.toString(16).padStart(8, '0')}`;
}
//
// Seven modes: 'plan', 'lesson', 'flashcards', 'cheatsheet', 'exercises', 'exam'
// and 'progress', driven by per-topic files under <topic-slug>/. Plan and Lesson
// share one markdown-document view ("docs": plan.md / session.md, see DOCS). Topic list comes
// from topics.json at the root. Per-topic known/unknown marks are persisted to
// localStorage keyed by card id (see cardId), plus the last exam result per topic (`exam:<topic>`).
// Submitted exams are also POSTed to /api/progress (serve.py), which appends
// them to <topic>/progress.jsonl — the file the Progress mode reads.
//
// Mermaid: every markdown render turns ```mermaid fences into an empty
// <div class="mermaid-block" data-src="…">. A MutationObserver (started in
// init()) notices new, not-yet-rendered blocks after Alpine updates the DOM and
// renders them one at a time with mermaid.render(). Blocks are marked with
// data-state so each is rendered exactly once; when x-html replaces the HTML
// (topic / card / mode change) the fresh blocks get rendered again.
//
// Pan / zoom: every rendered diagram gets an svg-pan-zoom instance (vendor/
// svg-pan-zoom.min.js) inside a fixed-height viewport, plus a toolbar
// (＋ − ⟲ ⛶). Initial view = fit + center, but never below READABLE × natural
// size (then the top-left part shows and the user pans). Zoom: ctrl/⌘ + wheel or
// trackpad pinch (plain wheel scrolls the page), two-finger pinch on touch;
// in fullscreen the plain wheel zooms too. Instances live in Mermaid._pz
// (block element → entry) and are destroyed when their block leaves the DOM.
// Plan mode: nodes whose id matches a chunk-table row (`#` column) are clickable.

// Markdown documents shown by the doc view (Plan / Lesson modes). Each is fetched
// with cache:'no-store' on entering its mode (and in loadTopic() when already in
// it), pre-rendered into docs[kind] = { loaded, missing, html, toc } so the
// template stays pure. The ToC lists ## and ### headings.
const DOCS = {
  plan:   { file: 'plan.md',    title: 'Plan',   prefix: 'plan-' },
  lesson: { file: 'session.md', title: 'Lesson', prefix: 'lesson-' },
};
const emptyDoc = () => ({ loaded: false, missing: false, html: '', toc: [] });

// Scroll-spy for the doc-like sidebars (Plan, Lesson, Cheat sheet, Progress): the
// ToC key is the mode name; `pane` holds that mode's ToC + content and `heads` the
// section anchors inside it (ids = the ToC entries' data-id). Exercises / Exam
// highlight their current item instead (exIndex / examIndex).
const SPY = {
  plan:       { pane: '#doc-plan',       heads: '.doc-body h2[id], .doc-body h3[id]' },
  lesson:     { pane: '#doc-lesson',     heads: '.doc-body h2[id], .doc-body h3[id]' },
  cheatsheet: { pane: 'main.cheatsheet', heads: '.cheat-section[id]' },
  progress:   { pane: 'main.progress',   heads: '.prog-section[id]' },
};
const emptyTocActive = () => Object.fromEntries(Object.keys(SPY).map(k => [k, '']));

// Progress-mode sidebar entries (count = key of a progress list shown as a badge).
const PROG_TOC = [
  { id: 'prog-overview', text: 'Overview' },
  { id: 'prog-tasks',    text: 'By task' },
  { id: 'prog-weak',     text: 'Weakest tasks' },
  { id: 'prog-review',   text: 'Review next', count: 'review' },
  { id: 'prog-trend',    text: 'Exam trend' },
  { id: 'prog-recent',   text: 'Recent activity' },
];

// Observers live outside Alpine's reactive proxy (native IntersectionObserver
// methods break when called through a Proxy). `locked` pauses the spy while a
// ToC click smooth-scrolls, so the clicked entry stays highlighted even when the
// page can't scroll far enough to bring its section to the top (last sections).
const Spy = { io: new Map(), locked: false, timer: 0, done: null };

const Mermaid = {
  _ready: false,
  _seq: 0,
  _queue: Promise.resolve(),
  _scanQueued: false,
  _failed: false,         // vendor AND CDN bundle both failed to load

  esc(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },

  // HTML placeholder emitted by the markdown renderer.
  placeholder(src) {
    return `<div class="mermaid-block" data-src="${this.esc(src)}"><div class="mermaid-loading">rendering diagram…</div></div>\n`;
  },

  // Initialize lazily (the bundle may arrive late via the CDN fallback).
  ensure() {
    if (this._ready) return true;
    if (!window.mermaid || typeof window.mermaid.render !== 'function') return false;
    const css = getComputedStyle(document.documentElement);
    const v = (name, fb) => (css.getPropertyValue(name) || '').trim() || fb;
    const bg = v('--bg', '#0e1116'), surface = v('--surface', '#161b22'),
          surface2 = v('--surface-2', '#1c2128'), border = v('--border', '#30363d'),
          fg = v('--fg', '#c9d1d9'), muted = v('--fg-muted', '#8b949e'),
          accent = v('--accent', '#58a6ff');
    try {
      window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        suppressErrorRendering: true,
        theme: 'base',
        fontFamily: getComputedStyle(document.body).fontFamily,
        themeVariables: {
          darkMode: true,
          background: bg,
          fontSize: '15px',
          primaryColor: surface,
          primaryTextColor: fg,
          primaryBorderColor: accent,
          secondaryColor: surface2,
          secondaryTextColor: fg,
          secondaryBorderColor: border,
          tertiaryColor: surface2,
          tertiaryTextColor: fg,
          tertiaryBorderColor: border,
          lineColor: muted,
          textColor: fg,
          mainBkg: surface,
          nodeBorder: accent,
          nodeTextColor: fg,
          clusterBkg: bg,
          clusterBorder: border,
          titleColor: fg,
          edgeLabelBackground: surface2,
          noteBkgColor: surface2,
          noteTextColor: fg,
          noteBorderColor: border,
        },
      });
      this._ready = true;
    } catch {
      this._ready = false;
    }
    return this._ready;
  },

  // Coalesce DOM mutations into one scan per frame.
  scheduleScan() {
    if (this._scanQueued) return;
    this._scanQueued = true;
    requestAnimationFrame(() => {
      this._scanQueued = false;
      this.scan();
    });
  },

  scan() {
    this.sweep();
    const blocks = document.querySelectorAll('.mermaid-block:not([data-state])');
    for (const el of blocks) {
      el.setAttribute('data-state', 'queued');
      this._queue = this._queue.then(() => this.renderOne(el)).catch(() => {});
    }
  },

  async renderOne(el) {
    if (!el.isConnected) return;               // replaced before its turn came
    const src = el.dataset.src || '';
    if (!this.ensure()) {
      // Bundle not here (yet): wait for `mermaid-ready` (CDN fallback) or `mermaid-failed`.
      if (this._failed) this.fail(el, src, 'Mermaid library not loaded (vendor/mermaid.min.js).');
      else el.setAttribute('data-state', 'waiting');
      return;
    }
    const id = `mmd-${Date.now().toString(36)}-${++this._seq}`;
    try {
      const { svg, bindFunctions } = await window.mermaid.render(id, src);
      if (!el.isConnected) return;
      el.setAttribute('data-state', 'done');
      el.innerHTML = `<div class="mmd-frame"><div class="mermaid-viewport">${svg}</div></div>`;
      if (bindFunctions) bindFunctions(el);
      this.bindBlock(el);
      this.attach(el);
      if (el.closest('.plan-body')) this.linkPlan(el, src);
    } catch (err) {
      this.fail(el, src, String(err && err.message ? err.message : err).split('\n')[0]);
    } finally {
      // Mermaid renders into a temp node in <body>; make sure nothing is left behind.
      for (const tmp of document.querySelectorAll(`#d${id}, #i${id}`)) tmp.remove();
    }
  },

  // Fallback when svg-pan-zoom is unavailable (vendor + CDN failed): mermaid
  // emits width="100%" + max-width:<natural>px, which shrinks wide graphs until
  // labels are unreadable. Fill the container up to natural size, but never below
  // 75% of it — past that the .mmd-static viewport scrolls horizontally.
  size(svgEl) {
    if (!svgEl) return;
    const natural = parseFloat(svgEl.style.maxWidth) ||
      parseFloat((svgEl.getAttribute('viewBox') || '').split(/\s+/)[2]) || 0;
    if (!natural) return;
    svgEl.removeAttribute('width');
    svgEl.style.width = '100%';
    svgEl.style.maxWidth = `${natural}px`;
    svgEl.style.minWidth = `${Math.round(natural * 0.75)}px`;
  },

  fail(el, src, msg) {
    if (!el.isConnected) return;
    el.setAttribute('data-state', 'error');
    el.innerHTML = '';
    const note = document.createElement('div');
    note.className = 'mermaid-error';
    note.textContent = `⚠ Diagram could not be rendered${msg ? ': ' + msg : ''}`;
    const pre = document.createElement('pre');
    pre.className = 'mermaid-src';
    pre.textContent = src;
    el.append(note, pre);
  },

  // Watch the whole page: x-html swaps in new blocks whenever content changes.
  observe() {
    new MutationObserver(() => this.scheduleScan())
      .observe(document.body, { childList: true, subtree: true });
    const retry = () => {
      for (const el of document.querySelectorAll('.mermaid-block[data-state="waiting"]')) el.removeAttribute('data-state');
      this.scheduleScan();
    };
    window.addEventListener('mermaid-ready', retry);
    window.addEventListener('mermaid-failed', () => { this._failed = true; retry(); });
    // svg-pan-zoom arrived late (CDN fallback): upgrade diagrams rendered without it.
    window.addEventListener('svgpanzoom-ready', () => {
      for (const el of document.querySelectorAll('.mermaid-block[data-pz="pending"]')) this.attach(el);
    });
    document.addEventListener('fullscreenchange', () => this.onFsChange());
    // Esc closes the fallback overlay (native fullscreen handles Esc itself).
    window.addEventListener('keydown', (e) => {
      if (this._overlay && e.key === 'Escape') {
        e.preventDefault();
        e.stopImmediatePropagation();
        this.closeOverlay();
      }
    }, { capture: true });
    this.scheduleScan();
  },

  // ---- Pan / zoom ---------------------------------------------------------

  _pz: new Map(),         // .mermaid-block element -> entry; exactly one per rendered diagram
  _overlay: null,         // fallback "fullscreen" overlay: { wrap, el, ph }
  READABLE: 0.75,         // initial view never shows a diagram below 75% of natural size
  MIN_Z: 0.3,             // zoom limits, relative to natural size (min drops further if
  MAX_Z: 6,               //   needed so the whole diagram can always be zoomed out to)
  STEP: 0.25,             // zoomScaleSensitivity: ＋/− buttons and one wheel notch = ×1.25
  PAD: 12,                // px around the fitted diagram
  TOP: 46,                // px band at the top reserved for the hint + toolbar
  FS_MAX: 2,              // fullscreen fit may enlarge small diagrams up to 2×

  // True while the diagram is in native fullscreen or the fallback overlay.
  isFs(el) {
    return document.fullscreenElement === el || el.classList.contains('mmd-overlaid');
  },

  // A diagram is covering the page: the flashcard shortcuts must stand down.
  isModal() {
    return !!this._overlay ||
      !!(document.fullscreenElement && document.fullscreenElement.classList.contains('mermaid-block'));
  },

  // Click / drag bookkeeping shared by pan-zoom and static diagrams (installed once per block).
  bindBlock(el) {
    el.addEventListener('pointerdown', (e) => {
      el._mmdDown = { x: e.clientX, y: e.clientY };
      el._mmdDragged = false;
    }, true);
    el.addEventListener('pointermove', (e) => {
      const d = el._mmdDown;
      if (d && e.buttons && Math.hypot(e.clientX - d.x, e.clientY - d.y) > 4) el._mmdDragged = true;
    }, true);
    el.addEventListener('pointerup', () => { el._mmdDown = null; }, true);
    // Bubble phase: stopPropagation keeps toolbar clicks / pans from flipping a flashcard.
    el.addEventListener('click', (e) => {
      const btn = e.target.closest('.mmd-toolbar button');
      if (btn) {
        e.stopPropagation();
        btn.blur();
        this.action(el, btn.dataset.act);
        return;
      }
      const dragged = el._mmdDragged;
      el._mmdDragged = false;
      if (dragged) { e.stopPropagation(); return; }
      const node = e.target.closest('g.node.mmd-link');
      if (node && el._planRows) {
        e.stopPropagation();
        this.jumpToRow(el, node.dataset.mmdId);
      }
    });
  },

  toolbarHtml() {
    return `<div class="mmd-toolbar" role="toolbar" aria-label="diagram controls">` +
      `<button type="button" data-act="in" title="zoom in" aria-label="zoom in">＋</button>` +
      `<button type="button" data-act="out" title="zoom out" aria-label="zoom out">−</button>` +
      `<button type="button" data-act="reset" title="reset view" aria-label="reset view">⟲</button>` +
      `<button type="button" data-act="fs" title="fullscreen" aria-label="fullscreen">⛶</button>` +
      `</div>` +
      `<div class="mmd-hint" aria-hidden="true">` +
      `<span class="t-fine">ctrl/⌘ + scroll to zoom · drag to pan</span>` +
      `<span class="t-coarse">pinch to zoom · two fingers to pan</span>` +
      `<span class="t-fs">scroll to zoom · drag to pan · esc to close</span>` +
      `</div>`;
  },

  viewBoxOf(svgEl) {
    const v = (svgEl.getAttribute('viewBox') || '').split(/[\s,]+/).map(parseFloat);
    if (v.length !== 4 || v.some(n => !Number.isFinite(n)) || v[2] <= 0 || v[3] <= 0) return null;
    return { x: v[0], y: v[1], width: v[2], height: v[3] };
  },

  // Give a freshly rendered block its viewport + toolbar; the pan-zoom instance
  // itself is created by layout() once the viewport has a width (x-show'n
  // modes are display:none until opened).
  attach(el) {
    if (this._pz.has(el)) return;
    const vp = el.querySelector('.mermaid-viewport');
    const svgEl = vp && vp.querySelector('svg');
    if (!svgEl) return;
    const vb = this.viewBoxOf(svgEl);
    if (!window.svgPanZoom || !vb) {
      vp.classList.add('mmd-static');
      this.size(svgEl);
      el.setAttribute('data-pz', window.svgPanZoom ? 'off' : 'pending');
      return;
    }
    el.setAttribute('data-pz', 'on');
    vp.classList.remove('mmd-static');
    vp.insertAdjacentHTML('afterend', this.toolbarHtml());
    svgEl.setAttribute('width', '100%');
    svgEl.setAttribute('height', '100%');
    svgEl.style.width = '100%';
    svgEl.style.height = '100%';
    svgEl.style.maxWidth = 'none';
    svgEl.style.minWidth = '0';
    const entry = { el, vp, svg: svgEl, vb, pz: null, ro: null, lastW: 0, lastFs: null, touch: null };
    this._pz.set(el, entry);
    this.bindInput(entry);
    entry.ro = new ResizeObserver(() => this.layout(entry));
    entry.ro.observe(vp);
  },

  // Wheel + touch. Plain wheel is left to the page (a reading page shouldn't
  // trap scrolling); ctrl/⌘ + wheel (also what trackpad pinch sends) zooms.
  bindInput(entry) {
    const { el, vp } = entry;
    vp.addEventListener('wheel', (e) => {
      if (!entry.pz) return;
      if (!(e.ctrlKey || e.metaKey || this.isFs(el))) { this.nudge(el); return; }
      e.preventDefault();
      const raw = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * 400 : e.deltaY;
      const d = Math.max(-300, Math.min(300, raw));
      this.zoomAt(entry, Math.pow(1 + this.STEP, -d / 100), e.clientX, e.clientY);
    }, { passive: false });

    // Touch: one finger scrolls the page (pans the diagram only in fullscreen);
    // two fingers pinch-zoom + pan. svg-pan-zoom's own touch handling is halted.
    const pts = (e) => [...e.touches].map(t => ({ x: t.clientX, y: t.clientY }));
    const pair = (p) => ({ x: (p[0].x + p[1].x) / 2, y: (p[0].y + p[1].y) / 2,
                           d: Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y) });
    const onTouch = (e) => {
      if (!entry.pz) return;
      const p = pts(e);
      if (e.type !== 'touchmove') {
        entry.touch = p.length >= 2 ? { two: pair(p) }
          : (p.length === 1 && this.isFs(el)) ? { one: p[0] } : null;
        return;
      }
      const t = entry.touch;
      if (!t) return;
      if (p.length >= 2 && t.two) {
        if (e.cancelable) e.preventDefault();
        const cur = pair(p);
        entry.pz.panBy({ x: cur.x - t.two.x, y: cur.y - t.two.y });
        if (t.two.d > 0 && cur.d > 0) this.zoomAt(entry, cur.d / t.two.d, cur.x, cur.y);
        t.two = cur;
      } else if (p.length === 1 && t.one) {
        if (e.cancelable) e.preventDefault();
        entry.pz.panBy({ x: p[0].x - t.one.x, y: p[0].y - t.one.y });
        t.one = p[0];
      }
    };
    for (const type of ['touchstart', 'touchmove', 'touchend', 'touchcancel']) {
      vp.addEventListener(type, onTouch, { passive: false });
    }
  },

  zoomAt(entry, factor, clientX, clientY) {
    const r = entry.svg.getBoundingClientRect();
    entry.pz.zoomAtPointBy(factor, { x: clientX - r.left, y: clientY - r.top });
  },

  // Briefly highlight the hint when a plain wheel passes over the diagram.
  nudge(el) {
    el.classList.remove('mmd-nudge');
    void el.offsetWidth;                    // restart the animation
    el.classList.add('mmd-nudge');
    clearTimeout(el._nudgeTimer);
    el._nudgeTimer = setTimeout(() => el.classList.remove('mmd-nudge'), 1400);
  },

  maxHeight(vp) {
    return parseFloat(getComputedStyle(vp).getPropertyValue('--mmd-max-h')) || 420;
  },

  // Real (natural = 1) scale for the default view of a W×H viewport.
  initialScale(entry, W, H, fs) {
    const vb = entry.vb, P = this.PAD;
    const fit = Math.min((W - 2 * P) / vb.width, (H - this.TOP - P) / vb.height);
    if (fs) return Math.max(0.05, Math.min(fit, this.FS_MAX));
    return Math.max(Math.min(fit, 1), Math.min(1, this.READABLE));
  },

  // (Re)size the viewport and (re)create / resize the instance. Runs from the
  // ResizeObserver (width or fullscreen state changed) and on fullscreen toggles.
  layout(entry, force) {
    if (!entry.el.isConnected) return;
    const fs = this.isFs(entry.el);
    const W = entry.vp.clientWidth;
    if (!W) return;                          // hidden — the observer fires again when shown
    if (!force && W === entry.lastW && fs === entry.lastFs) return;
    entry.lastW = W;
    entry.lastFs = fs;
    if (fs) {
      entry.vp.style.height = '';
    } else {
      const maxH = this.maxHeight(entry.vp);
      const s = this.initialScale(entry, W, maxH, false);
      const h = Math.min(maxH, Math.ceil(entry.vb.height * s + this.TOP + this.PAD));
      entry.vp.style.height = `${Math.max(140, h)}px`;
    }
    if (!entry.pz) {
      entry.pz = window.svgPanZoom(entry.svg, {
        panEnabled: true,
        zoomEnabled: true,
        controlIconsEnabled: false,
        dblClickZoomEnabled: false,
        mouseWheelZoomEnabled: false,          // own wheel handler (ctrl/⌘ rule)
        preventMouseEventsDefault: true,
        zoomScaleSensitivity: this.STEP,
        minZoom: 0.01,
        maxZoom: 100,                          // real limits are set in resetView()
        fit: false,
        contain: false,
        center: false,
        beforePan: (_old, next) => this.limitPan(entry, next),
        customEventsHandler: {
          haltEventListeners: ['touchstart', 'touchend', 'touchmove', 'touchleave', 'touchcancel'],
          init() {},
          destroy() {},
        },
      });
    } else {
      entry.pz.resize();
    }
    this.resetView(entry);
  },

  // Default view: fitted + centred below the toolbar band (never below READABLE
  // outside fullscreen); too-big diagrams start at their top-left corner.
  resetView(entry) {
    const pz = entry.pz;
    if (!pz) return;
    const sz = pz.getSizes();
    const W = sz.width, H = sz.height, vb = entry.vb, P = this.PAD;
    if (!W || !H) return;
    const fs = this.isFs(entry.el);
    const s = this.initialScale(entry, W, H, fs);
    const orig = sz.realZoom / (pz.getZoom() || 1);  // svg-pan-zoom's zoom is relative to this
    const T = this.TOP;
    const fitAll = Math.min((W - 2 * P) / vb.width, (H - T - P) / vb.height);
    pz.setMinZoom(Math.min(this.MIN_Z, fitAll, s) / orig);
    pz.setMaxZoom(Math.max(this.MAX_Z, s) / orig);
    pz.zoom(s / orig);
    const cw = vb.width * s, ch = vb.height * s;
    const x = cw <= W ? (W - cw) / 2 : P;
    const y = ch <= H - T - P ? T + (H - T - P - ch) / 2 : T;
    pz.pan({ x: x - vb.x * s, y: y - vb.y * s });
  },

  // Keep at least a sliver of the diagram on screen while panning.
  limitPan(entry, next) {
    const pz = entry.pz;
    if (!pz) return true;
    const s = pz.getSizes(), z = s.realZoom, vb = entry.vb, g = 48;
    const clamp = (v, lo, hi) => (lo > hi ? v : Math.max(lo, Math.min(hi, v)));
    return {
      x: clamp(next.x, g - (vb.x + vb.width) * z, s.width - g - vb.x * z),
      y: clamp(next.y, g - (vb.y + vb.height) * z, s.height - g - vb.y * z),
    };
  },

  action(el, act) {
    const entry = this._pz.get(el);
    if (!entry || !entry.pz) return;
    if (act === 'in') entry.pz.zoomIn();
    else if (act === 'out') entry.pz.zoomOut();
    else if (act === 'reset') this.resetView(entry);
    else if (act === 'fs') this.toggleFs(el);
  },

  toggleFs(el) {
    if (this.isFs(el)) { this.exitFs(el); return; }
    if (el.requestFullscreen && document.fullscreenEnabled) {
      el.requestFullscreen().catch(() => this.openOverlay(el));
    } else {
      this.openOverlay(el);
    }
  },

  exitFs(el) {
    if (document.fullscreenElement === el) return document.exitFullscreen().catch(() => {});
    if (this._overlay && this._overlay.el === el) this.closeOverlay();
    return Promise.resolve();
  },

  onFsChange() {
    for (const entry of this._pz.values()) {
      const fs = this.isFs(entry.el);
      entry.el.classList.toggle('mmd-fs', fs);
      this.fsButton(entry.el, fs);
      if (fs !== entry.lastFs) requestAnimationFrame(() => this.layout(entry, true));
    }
  },

  fsButton(el, fs) {
    const b = el.querySelector('.mmd-toolbar [data-act="fs"]');
    if (!b) return;
    b.title = fs ? 'exit fullscreen (Esc)' : 'fullscreen';
    b.setAttribute('aria-label', b.title);
    b.classList.toggle('on', fs);
  },

  // Fallback when the Fullscreen API is missing or refused (e.g. iPhone Safari):
  // move the block into a fixed overlay, leaving a placeholder to return to.
  openOverlay(el) {
    if (this._overlay) this.closeOverlay();
    const ph = document.createElement('div');
    ph.className = 'mmd-placeholder';
    ph.style.height = `${el.offsetHeight}px`;
    el.replaceWith(ph);
    const wrap = document.createElement('div');
    wrap.className = 'mmd-overlay';
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-modal', 'true');
    wrap.setAttribute('aria-label', 'diagram');
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'mmd-close';
    close.textContent = '✕ Close';
    close.title = 'close (Esc)';
    close.addEventListener('click', () => this.closeOverlay());
    wrap.append(close, el);
    document.body.appendChild(wrap);
    document.documentElement.classList.add('mmd-noscroll');
    el.classList.add('mmd-overlaid', 'mmd-fs');
    this._overlay = { wrap, el, ph };
    this.fsButton(el, true);
    const entry = this._pz.get(el);
    if (entry) requestAnimationFrame(() => this.layout(entry, true));
  },

  closeOverlay() {
    const o = this._overlay;
    if (!o) return;
    this._overlay = null;
    o.el.classList.remove('mmd-overlaid', 'mmd-fs');
    this.fsButton(o.el, false);
    if (o.ph.isConnected) o.ph.replaceWith(o.el);   // content re-rendered meanwhile → drop it
    o.wrap.remove();
    document.documentElement.classList.remove('mmd-noscroll');
    const entry = this._pz.get(o.el);
    if (entry && o.el.isConnected) requestAnimationFrame(() => this.layout(entry, true));
    else this.sweep();
  },

  // Destroy instances whose block left the DOM (x-html re-render, topic switch).
  sweep() {
    for (const [el, entry] of this._pz) {
      if (el.isConnected) continue;
      try { if (entry.pz) entry.pz.destroy(); } catch { /* svg already gone */ }
      if (entry.ro) entry.ro.disconnect();
      entry.pz = null;
      this._pz.delete(el);
    }
  },

  // ---- Plan map click-through --------------------------------------------

  // Mermaid node id: data-id when present, else parsed from "…flowchart-<id>-<n>".
  nodeId(g) {
    if (g.dataset.id) return g.dataset.id;
    const m = /(?:^|-)flowchart-(.+?)-\d+$/.exec(g.id || '');
    return m ? m[1] : '';
  },

  legendHtml() {
    const item = (cls, label) => `<span class="lg ${cls}"><i></i>${label}</span>`;
    return `<div class="mmd-legend">` +
      item('done', 'done') + item('doing', 'in progress') + item('todo', 'to do') +
      item('known', 'known') + item('gap', 'gap') + item('goal', 'goal') +
      `</div>`;
  },

  // Link plan-map nodes to the chunk table rows (first column `#`, values = node ids).
  linkPlan(el, src) {
    const body = el.closest('.plan-body');
    if (!body) return;
    if (/^\s*classDef\s+(done|doing|todo|known|gap|goal)\b/m.test(src)) {
      el.insertAdjacentHTML('beforeend', this.legendHtml());
    }
    const rows = new Map();
    for (const table of body.querySelectorAll('table')) {
      const th = table.querySelector('tr th');
      if (!th || th.textContent.trim() !== '#') continue;
      for (const tr of table.querySelectorAll('tbody tr')) {
        const id = tr.cells[0] ? tr.cells[0].textContent.trim().toLowerCase() : '';
        if (id && !rows.has(id)) rows.set(id, tr);
      }
    }
    const nodes = new Map();
    for (const g of el.querySelectorAll('svg g.node')) {
      const id = this.nodeId(g).toLowerCase();
      if (!id || !rows.has(id) || nodes.has(id)) continue;
      g.classList.add('mmd-link');
      g.dataset.mmdId = id;
      nodes.set(id, g);
    }
    if (!nodes.size) return;
    el._planRows = rows;
    el._planNodes = nodes;
    for (const [id, tr] of rows) {
      if (!nodes.has(id)) continue;
      const td = tr.cells[0];
      td.classList.add('plan-id-link');
      td.title = 'show in the map';
      td.onclick = () => this.pulseNode(el, id);
    }
    const legend = el.querySelector('.mmd-legend');
    if (legend) legend.insertAdjacentHTML('beforeend', `<span class="lg-tip">click a chunk to jump to its row</span>`);
  },

  flashClass(node, cls, ms) {
    node.classList.remove(cls);
    void (node.getBoundingClientRect && node.getBoundingClientRect());   // restart animation
    node.classList.add(cls);
    clearTimeout(node._flashTimer);
    node._flashTimer = setTimeout(() => node.classList.remove(cls), ms);
  },

  jumpToRow(el, id) {
    const tr = el._planRows && el._planRows.get(id);
    if (!tr) return;
    const go = () => {
      tr.scrollIntoView({ behavior: 'smooth', block: 'center' });
      this.flashClass(tr, 'plan-row-hit', 2000);
    };
    if (this.isFs(el)) this.exitFs(el).then(() => setTimeout(go, 80));
    else go();
  },

  // Row id clicked: bring the diagram into view, centre the node if it's off-screen, pulse it.
  pulseNode(el, id) {
    const g = el._planNodes && el._planNodes.get(id);
    if (!g || !g.isConnected) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const entry = this._pz.get(el);
    if (entry && entry.pz) {
      const vr = entry.vp.getBoundingClientRect(), nr = g.getBoundingClientRect();
      const inside = nr.left >= vr.left && nr.right <= vr.right && nr.top >= vr.top && nr.bottom <= vr.bottom;
      if (!inside) {
        entry.pz.panBy({
          x: (vr.left + vr.width / 2) - (nr.left + nr.width / 2),
          y: (vr.top + vr.height / 2) - (nr.top + nr.height / 2),
        });
      }
    }
    this.flashClass(g, 'mmd-pulse', 1800);
  },
};

document.addEventListener('alpine:init', () => {
  marked.use({
    renderer: {
      // ```mermaid fences become a placeholder; everything else uses the default renderer.
      code(code, infostring) {
        const lang = String(infostring || '').trim().split(/\s+/)[0].toLowerCase();
        if (lang === 'mermaid') return Mermaid.placeholder(code);
        return false;
      },
    },
  });

  marked.setOptions({
    breaks: true,
    highlight(code, lang) {
      if (lang === 'mermaid') return code;   // never highlighted (handled by the renderer)
      try {
        if (lang && hljs.getLanguage(lang)) {
          return hljs.highlight(code, { language: lang }).value;
        }
        return hljs.highlightAuto(code).value;
      } catch {
        return code;
      }
    },
  });

  Alpine.data('study', () => ({
    topics: [],
    topic: '',
    mode: 'flashcards',     // 'plan' | 'lesson' | 'flashcards' | 'cheatsheet' | 'exercises' | 'exam' | 'progress'

    // Doc state for Plan (<topic>/plan.md) and Lesson (<topic>/session.md); rendered
    // once per fetch so the template stays pure. toc = [{ id, text, level: 2|3 }].
    DOCS,
    docKinds: Object.keys(DOCS),
    docs: { plan: emptyDoc(), lesson: emptyDoc() },
    // Section id highlighted in each doc-like sidebar (scroll-spy; see SPY). Reassigned, never mutated.
    tocActive: emptyTocActive(),
    PROG_TOC,

    // Flashcards state
    cards: [],
    filtered: [],
    index: 0,
    flipped: false,
    unknownOnly: false,
    known: {},            // { [cardId]: true (known) | false (unknown) }
    cardIds: [],          // cardId(q) per card, same order as `cards`
    flash: null,          // 'known' | 'unknown' | null — drives the flash animation
    _flashTimer: null,

    // Cheat sheet state
    cheatsheet: [],

    // Exercises state
    exercises: [],
    exIndex: 0,
    exState: {},          // per-exercise transient UI state, keyed by exercise id (not persisted)

    // Exam state
    exam: [],             // raw questions from exam.json
    examOrder: [],        // display order: indices into exam (shuffled on retake)
    examIndex: 0,         // position in examOrder
    examState: {},        // per-question answer state, keyed by question id (not persisted)
    examResult: null,     // {score, total, pct, pass, dontKnow, byTask} after Submit
    examSave: null,       // null | {state: 'saving'|'saved'|'error', saved, error} — disk save of the last submit
    examLast: null,       // last saved result {score, total, date} from localStorage
    examTimerOn: false,
    examRemaining: 0,     // seconds left on the informational countdown
    _examTimer: null,

    // Progress state (from <topic>/progress.jsonl; pre-computed on load so getters stay pure)
    progressLoaded: false,
    progressMissing: false,
    progress: null,       // see computeProgress()

    // Topic picker: per-topic {title, group, order} from <slug>/meta.json plus an
    // overall mastery % from <slug>/progress.jsonl. Pre-built into topicGroups.
    topicMeta: {},        // slug -> { title, group, order, pct }
    topicGroups: [],      // [{ group, items: [{ slug, text }] }]

    async init() {
      try {
        const r = await fetch('topics.json', { cache: 'no-store' });
        if (r.ok) this.topics = await r.json();
      } catch {
        this.topics = [];
      }
      // Fallback labels first so the picker renders immediately; real names load async.
      this.topicMeta = Object.fromEntries(this.topics.map(s => [s, this.defaultMeta(s)]));
      this.buildTopicGroups();
      this.loadTopicMeta();

      const params = new URLSearchParams(location.search);
      const requested = params.get('topic');
      this.topic = (requested && this.topics.includes(requested))
        ? requested
        : (this.topics[0] || '');

      const reqMode = params.get('mode');
      if (['plan', 'lesson', 'cheatsheet', 'flashcards', 'exercises', 'exam', 'progress'].includes(reqMode)) {
        this.mode = reqMode;
      }

      Mermaid.observe();
      this.trackHeader();

      if (this.topic) await this.loadTopic();

      // Blur buttons after click so they don't steal focus from keyboard shortcuts.
      document.addEventListener('click', (e) => {
        const btn = e.target.closest('button');
        if (btn) btn.blur();
      });

      // Capture phase so we catch keys before any focused element absorbs them.
      window.addEventListener('keydown', (e) => {
        if (e.target.matches('input, textarea')) return;
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        // A fullscreen / overlaid diagram covers the page: don't flip or switch cards behind it.
        if (Mermaid.isModal()) return;

        // In plan/lesson/cheatsheet/exercises/exam/progress mode, let the page scroll / typing happen normally.
        if (this.mode !== 'flashcards') return;

        if (e.code === 'Space')      { e.preventDefault(); this.flip();  return; }
        if (e.code === 'ArrowRight') { e.preventDefault(); this.next();  return; }
        if (e.code === 'ArrowLeft')  { e.preventDefault(); this.prev();  return; }

        switch (e.key) {
          case 's': case 'S': e.preventDefault(); this.shuffle();        break;
          case 'k': case 'K': e.preventDefault(); this.markKnown(true);  break;
          case 'u': case 'U': e.preventDefault(); this.markKnown(false); break;
          // Reset is destructive — Shift+R only.
          case 'R':           e.preventDefault(); this.resetKnown();     break;
        }
      }, { capture: true });
    },

    async loadTopic() {
      // Load flashcards (may be missing for some topics — fall back to empty)
      try {
        const r = await fetch(`${this.topic}/flashcards.json`, { cache: 'no-store' });
        this.cards = r.ok ? await r.json() : [];
      } catch {
        this.cards = [];
      }

      // Load cheatsheet (may be missing for older topics — fall back to empty)
      try {
        const r = await fetch(`${this.topic}/cheatsheet.json`, { cache: 'no-store' });
        this.cheatsheet = r.ok ? await r.json() : [];
      } catch {
        this.cheatsheet = [];
      }

      // Load exercises (may be missing for older topics — fall back to empty)
      try {
        const r = await fetch(`${this.topic}/exercises.json`, { cache: 'no-store' });
        this.exercises = r.ok ? await r.json() : [];
      } catch {
        this.exercises = [];
      }
      // Pre-build transient UI state for every exercise + test so st() is a
      // PURE getter (no mutation during render — avoids reactive loops).
      this.exState = {};
      for (const ex of this.exercises) {
        const tests = {};
        (ex.tests || []).forEach((_, i) => {
          tests[i] = {
            pasted: '', result: '', expected: '', got: '',
            previewOpen: false, previewLoaded: false, previewItems: [], previewErr: ''
          };
        });
        this.exState[ex.id] = { hintsShown: 0, solShown: false, tests };
      }
      this.exIndex = 0;
      this.tocActive = emptyTocActive();
      this.$nextTick(() => this.spy('cheatsheet'));

      // Load exam questions (may be missing for most topics — fall back to empty)
      try {
        const r = await fetch(`${this.topic}/exam.json`, { cache: 'no-store' });
        this.exam = r.ok ? await r.json() : [];
      } catch {
        this.exam = [];
      }
      if (!Array.isArray(this.exam)) this.exam = [];
      this.resetExam(false);
      this.examLast = this.loadExamLast();

      this.cardIds = this.cards.map(c => cardId(c && c.q));
      const topic = this.topic;
      const known = await this.loadKnown();
      if (topic !== this.topic) return;     // topic switched while loading
      this.known = known;
      this.applyFilter();
      this.index = 0;
      this.flipped = false;

      // Progress is fetched lazily (only when the Progress mode is shown) so
      // topics without a progress.jsonl don't log 404s in the other modes.
      this.progress = this.computeProgress([]);
      this.progressLoaded = false;
      this.progressMissing = false;
      if (this.mode === 'progress') await this.loadProgress();

      // Plan / lesson docs are fetched lazily too, and re-read every time their mode is entered.
      this.docs = { plan: emptyDoc(), lesson: emptyDoc() };
      if (this.isDocMode()) await this.loadDoc(this.mode);

      this.updateUrl();
    },

    // ---- PLAN / LESSON (markdown docs) ----------------------------------------

    isDocMode() { return Object.prototype.hasOwnProperty.call(DOCS, this.mode); },

    loadPlan()   { return this.loadDoc('plan'); },
    loadLesson() { return this.loadDoc('lesson'); },

    // Fetch <topic>/<file> and pre-render it (HTML + ToC from its ## / ### headings).
    async loadDoc(kind) {
      const cfg = DOCS[kind];
      const topic = this.topic;
      if (!cfg || !topic) return;
      let text = '';
      let missing = false;
      try {
        const r = await fetch(`${topic}/${cfg.file}`, { cache: 'no-store' });
        if (r.ok) text = await r.text();
        else missing = true;
      } catch {
        missing = true;
      }
      if (topic !== this.topic) return;     // topic switched while loading
      let html = '';
      let toc = [];
      if (!missing && text.trim()) {
        html = marked.parse(text, { headerIds: true, headerPrefix: cfg.prefix });
        try {
          const doc = new DOMParser().parseFromString(html, 'text/html');
          toc = [...doc.querySelectorAll('h2[id], h3[id]')].map(h => ({
            id: h.id, text: h.textContent.trim(), level: h.tagName === 'H3' ? 3 : 2,
          }));
        } catch { toc = []; }
      }
      // Field-level assignments on this doc only: the same markdown gives the same
      // string, so Alpine skips the x-html update (no re-render / diagram flicker),
      // and the other doc's pane is never touched.
      const d = this.docs[kind];
      d.missing = missing || !text.trim();
      d.html = html;
      d.toc = toc;
      d.loaded = true;
      this.$nextTick(() => this.spy(kind));
    },

    // ---- SIDEBAR (shared by every mode with an aside.toc) ---------------------

    // The sticky header's real height → --header-h, which the sticky sidebar's
    // top / height and the sections' scroll-margin derive from (the header wraps
    // to more rows at narrow widths or with wide mode-specific controls).
    trackHeader() {
      const header = document.querySelector('header');
      if (!header) return;
      const set = () => document.documentElement.style.setProperty('--header-h', `${header.offsetHeight}px`);
      set();
      if (window.ResizeObserver) new ResizeObserver(set).observe(header);
    },

    // Scroll-spy (key = a SPY entry = its mode): highlight the ToC entry of the
    // section being read. The observer only fires when a section anchor crosses the
    // top band of the viewport; the current one is then the last whose top is above
    // the band's lower edge. Re-run whenever the pane's content is (re)rendered or
    // its mode is entered (observers on hidden panes report nothing useful).
    spy(key) {
      const cfg = SPY[key];
      const old = Spy.io.get(key);
      if (old) old.disconnect();
      Spy.io.delete(key);
      const pane = cfg && document.querySelector(cfg.pane);
      const heads = pane ? [...pane.querySelectorAll(cfg.heads)] : [];
      if (!heads.length || !window.IntersectionObserver) return;
      const update = () => {
        if (this.mode !== key || Spy.locked) return;
        const line = window.innerHeight * 0.3;
        let cur = heads[0];
        for (const h of heads) {
          if (h.getBoundingClientRect().top <= line) cur = h;
          else break;
        }
        this.setTocActive(key, cur.id);
      };
      const io = new IntersectionObserver(update, { rootMargin: '0px 0px -70% 0px', threshold: 0 });
      heads.forEach(h => io.observe(h));
      Spy.io.set(key, io);
    },

    setTocActive(key, id) {
      if (this.tocActive[key] === id) return;
      this.tocActive = { ...this.tocActive, [key]: id };
      this.$nextTick(() => this.revealTocItem(SPY[key].pane));
    },

    // ToC click in a doc-like sidebar: highlight it now, smooth-scroll to it, and
    // pause the spy until the scroll ends.
    tocGo(key, id) {
      this.setTocActive(key, id);
      if (Spy.done) Spy.done();
      const done = Spy.done = () => {
        if (Spy.done !== done) return;
        Spy.locked = false;
        Spy.done = null;
        clearTimeout(Spy.timer);
        window.removeEventListener('scrollend', done);
      };
      Spy.locked = true;
      window.addEventListener('scrollend', done);
      Spy.timer = setTimeout(done, 1500);      // no scroll needed / no scrollend support
      this.scrollToId(id);
    },

    // Keep the active entry visible inside a scrollable ToC (only scrolls the ToC, never the page).
    revealTocItem(paneSel) {
      const a = document.querySelector(`${paneSel} .toc .toc-item.active`);
      const toc = a && a.closest('.toc');
      if (!toc || toc.scrollHeight <= toc.clientHeight) return;
      const t = a.getBoundingClientRect().top - toc.getBoundingClientRect().top + toc.scrollTop;
      const b = t + a.offsetHeight;
      if (t < toc.scrollTop + 40) toc.scrollTop = Math.max(0, t - 40);
      else if (b > toc.scrollTop + toc.clientHeight - 40) toc.scrollTop = b - toc.clientHeight + 40;
    },

    // Pure getter for per-exercise transient state. testIdx omitted → exercise-level state.
    st(id, testIdx) {
      const e = this.exState[id];
      if (!e) return { hintsShown: 0, solShown: false, tests: {} };
      if (testIdx === undefined) return e;
      return e.tests[testIdx] || { pasted: '', result: '', expected: '', got: '' };
    },

    // Normalize output for comparison: trimEnd each line, drop outer blank lines,
    // optionally sort lines (for order-independent output).
    normalizeOutput(text, unordered) {
      let lines = String(text == null ? '' : text)
        .split('\n')
        .map(l => l.replace(/\s+$/, ''));
      while (lines.length && lines[0] === '') lines.shift();
      while (lines.length && lines[lines.length - 1] === '') lines.pop();
      if (unordered) lines = lines.slice().sort();
      return lines.join('\n');
    },

    checkTest(id, testIdx) {
      const ex = this.exercises.find(x => x.id === id);
      if (!ex) return;
      const test = ex.tests[testIdx];
      const s = this.st(id, testIdx);
      const exp = this.normalizeOutput(test.expected, test.unordered);
      const got = this.normalizeOutput(s.pasted, test.unordered);
      s.expected = exp;
      s.got = got;
      s.result = exp === got ? 'pass' : 'fail';
    },

    revealHint(id) {
      const ex = this.exercises.find(x => x.id === id);
      const e = this.st(id);
      const max = (ex && ex.hints ? ex.hints.length : 0);
      if (e.hintsShown < max) e.hintsShown++;
    },

    // Input paths in exercises.json are relative to the TOPIC folder, but the
    // page is served from the root — so prefix with the topic to get a real URL.
    inputUrl(input) {
      return `${this.topic}/${input}`;
    },

    // Toggle the inline input preview; lazy-load the real file(s) from disk on first open.
    async togglePreview(id, testIdx) {
      const ex = this.exercises.find(x => x.id === id);
      const s = this.st(id, testIdx);
      s.previewOpen = !s.previewOpen;
      if (!s.previewOpen || s.previewLoaded) return;
      const path = this.inputUrl(ex.tests[testIdx].input);
      try {
        const items = await this.loadInput(path);
        s.previewItems = items;
        s.previewLoaded = true;
      } catch (err) {
        s.previewErr = String(err && err.message ? err.message : err);
        s.previewLoaded = true;
      }
    },

    // Resolve an input path to a list of {rel, content}. Handles a single file
    // OR a directory (parses the http.server listing, recurses, fetches files).
    async loadInput(path) {
      const r = await fetch(path, { cache: 'no-store' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const ct = r.headers.get('content-type') || '';
      const body = await r.text();
      const isDir = ct.includes('text/html') && /Directory listing for/i.test(body);
      if (!isDir) {
        const name = decodeURIComponent(path.split('/').pop());
        return [{ rel: name, content: this.truncate(body) }];
      }
      const out = [];
      await this.collectDir(path, body, '', 0, out);
      out.sort((a, b) => a.rel.localeCompare(b.rel));
      return out;
    },

    async collectDir(basePath, listingHtml, prefix, depth, out) {
      if (depth > 5) return;
      const doc = new DOMParser().parseFromString(listingHtml, 'text/html');
      const hrefs = [...doc.querySelectorAll('a')]
        .map(a => a.getAttribute('href'))
        .filter(h => h && !h.startsWith('/') && h !== '../' && h !== './');
      const base = basePath.replace(/\/$/, '');
      for (const href of hrefs) {
        const isDir = href.endsWith('/');
        const name = decodeURIComponent(href.replace(/\/$/, ''));
        const childPath = `${base}/${href}`;
        if (isDir) {
          const rr = await fetch(childPath, { cache: 'no-store' });
          const hh = await rr.text();
          await this.collectDir(childPath, hh, `${prefix}${name}/`, depth + 1, out);
        } else {
          const rr = await fetch(childPath, { cache: 'no-store' });
          const content = await rr.text();
          out.push({ rel: `${prefix}${name}`, content: this.truncate(content) });
        }
      }
    },

    truncate(text, max = 2000) {
      if (text.length <= max) return text;
      return text.slice(0, max) + `\n… (${text.length - max} more chars)`;
    },

    // ---- EXAM ------------------------------------------------------------

    // Pre-build answer state for every question so eq() is a PURE getter
    // (no mutation during render — avoids reactive loops). Also used by Retake.
    resetExam(shuffle) {
      const state = {};
      for (const q of this.exam) {
        state[q.id] = {
          picked: [],                                            // single / multi: chosen option indices
          order: (q.options || []).map((_, i) => i),             // order: current arrangement
          match: (q.prompts || []).map(() => null),              // match: option index per prompt
          touched: false,                                        // order: user moved something
          idk: false,                                            // "I don't know" — exclusive with answering
          note: '',                                              // optional note, saved with the answer
          checked: false,
          correct: null,
        };
      }
      this.examState = state;
      const order = this.exam.map((_, i) => i);
      if (shuffle) {
        for (let i = order.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [order[i], order[j]] = [order[j], order[i]];
        }
      }
      this.examOrder = order;
      this.examIndex = 0;
      this.examResult = null;
      this.examSave = null;
      this.stopExamTimer();
      if (this.examTimerOn) this.startExamTimer();
    },

    // Pure getter for per-question state.
    eq(id) {
      return this.examState[id] || { picked: [], order: [], match: [], touched: false, idk: false, note: '', checked: false, correct: null };
    },

    // Replace (not mutate) the question's state object so every dependent re-renders.
    examPatch(id, patch) {
      this.examState = { ...this.examState, [id]: { ...this.eq(id), ...patch } };
    },

    examCur() {
      return this.exam[this.examOrder[this.examIndex]];
    },

    examGo(delta) {
      const n = this.examOrder.length;
      if (!n) return;
      this.examIndex = Math.min(n - 1, Math.max(0, this.examIndex + delta));
      this.$nextTick(() => this.revealTocItem('main.exam'));
    },

    letter(i) { return String.fromCharCode(65 + i); },

    // Markdown → plain text for <option> labels (which can't hold HTML).
    plain(md) {
      return String(md || '').replace(/[`*_]/g, '').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1');
    },

    // Only absolute http(s) URLs become links; anything else (e.g. "tutor quiz") is plain text.
    isUrl(s) {
      return typeof s === 'string' && /^https?:\/\//i.test(s);
    },

    typeLabel(t) {
      return { single: 'single', multi: 'multi', order: 'order', match: 'match' }[t] || t;
    },

    togglePick(q, oi) {
      const s = this.eq(q.id);
      if (s.checked) return;
      let picked;
      if (q.type === 'single') picked = [oi];
      else picked = s.picked.includes(oi) ? s.picked.filter(x => x !== oi) : [...s.picked, oi];
      this.examPatch(q.id, { picked, idk: false });
    },

    moveItem(q, pos, dir) {
      const s = this.eq(q.id);
      const to = pos + dir;
      if (s.checked || to < 0 || to >= s.order.length) return;
      const order = s.order.slice();
      [order[pos], order[to]] = [order[to], order[pos]];
      this.examPatch(q.id, { order, touched: true, idk: false });
    },

    setMatch(q, pi, value) {
      const s = this.eq(q.id);
      if (s.checked) return;
      const match = s.match.slice();
      match[pi] = value === '' ? null : Number(value);
      this.examPatch(q.id, { match, idk: false });
    },

    // "I don't know" is exclusive with answering: turning it on clears any answer.
    toggleIdk(q) {
      const s = this.eq(q.id);
      if (s.checked) return;
      if (s.idk) { this.examPatch(q.id, { idk: false }); return; }
      this.examPatch(q.id, {
        idk: true,
        picked: [],
        order: (q.options || []).map((_, i) => i),
        match: (q.prompts || []).map(() => null),
        touched: false,
      });
    },

    examAnswered(q) {
      const s = this.eq(q.id);
      if (q.type === 'single' || q.type === 'multi') return s.picked.length > 0;
      if (q.type === 'order') return s.touched || s.checked;
      if (q.type === 'match') return s.match.length > 0 && s.match.every(v => v !== null);
      return false;
    },

    examIsCorrect(q) {
      const s = this.eq(q.id);
      const ans = q.answer || [];
      if (q.type === 'single' || q.type === 'multi') {
        const a = ans.slice().sort((x, y) => x - y);
        const p = s.picked.slice().sort((x, y) => x - y);
        return a.length === p.length && a.every((v, i) => v === p[i]);
      }
      if (q.type === 'order') return ans.length === s.order.length && ans.every((v, i) => v === s.order[i]);
      if (q.type === 'match') return ans.length === s.match.length && ans.every((v, i) => v === s.match[i]);
      return false;
    },

    checkQuestion(q) {
      const s = this.eq(q.id);
      if (s.checked) return;
      this.examPatch(q.id, { checked: true, correct: !s.idk && this.examIsCorrect(q) });
    },

    // 'unanswered' | 'answered' | 'dont_know' | 'correct' | 'wrong'
    examStatus(q) {
      const s = this.eq(q.id);
      if (s.idk) return 'dont_know';
      if (s.checked) return s.correct ? 'correct' : 'wrong';
      return this.examAnswered(q) ? 'answered' : 'unanswered';
    },

    // Answered or explicitly marked "I don't know".
    examAnsweredCount() {
      return this.exam.filter(q => this.examAnswered(q) || this.eq(q.id).idk).length;
    },

    // Option highlight after Check (single / multi).
    optClass(q, oi) {
      const s = this.eq(q.id);
      const picked = s.picked.includes(oi);
      if (!s.checked) return { picked };
      const right = (q.answer || []).includes(oi);
      return { picked, right, wrong: picked && !right };
    },

    orderClass(q, pos) {
      const s = this.eq(q.id);
      if (!s.checked || s.idk) return {};
      const ok = (q.answer || [])[pos] === s.order[pos];
      return { right: ok, wrong: !ok };
    },

    matchClass(q, pi) {
      const s = this.eq(q.id);
      if (!s.checked || s.idk) return {};
      const ok = (q.answer || [])[pi] === s.match[pi];
      return { right: ok, wrong: !ok };
    },

    // Grade everything (unanswered = wrong, "I don't know" = not correct but
    // reported separately), reveal all answers, save the result locally and
    // try to append it to <topic>/progress.jsonl via serve.py.
    submitExam() {
      if (!this.exam.length || this.examResult) return;
      const state = { ...this.examState };
      const byTask = {};
      const events = [];
      const ts = this.localIso(new Date());
      const run = `exam-${Date.now()}`;
      let score = 0;
      let dontKnow = 0;
      for (const q of this.exam) {
        const s = this.eq(q.id);
        const correct = s.idk ? false
          : (s.checked ? s.correct : (this.examAnswered(q) && this.examIsCorrect(q)));
        state[q.id] = { ...s, checked: true, correct };
        const t = q.task || '—';
        if (!byTask[t]) byTask[t] = { task: t, correct: 0, total: 0 };
        byTask[t].total++;
        if (correct) { byTask[t].correct++; score++; }
        if (s.idk) dontKnow++;

        const ev = {
          ts, topic: this.topic, source: 'exam', task: String(q.task || ''), qid: String(q.id),
          question: this.shortText(q.question, 200),
          result: s.idk ? 'dont_know' : (correct ? 'correct' : 'wrong'),
          attempt: 1,
        };
        const answer = s.idk ? '' : this.answerText(q, s);
        if (answer) ev.answer = answer;
        if (s.note && s.note.trim()) ev.note = s.note.trim().slice(0, 500);
        ev.run = run;
        events.push(ev);
      }
      this.examState = state;
      const total = this.exam.length;
      const pct = Math.round((score / total) * 100);
      this.examResult = {
        score, total, pct, dontKnow,
        pass: pct >= 70,
        byTask: Object.values(byTask).sort((a, b) =>
          String(a.task).localeCompare(String(b.task), undefined, { numeric: true })),
      };
      this.stopExamTimer();
      this.saveExamLast(score, total);
      this.saveExamProgress(events);
      requestAnimationFrame(() => {
        const el = document.getElementById('exam-score');
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    },

    retakeExam() {
      this.resetExam(true);
    },

    // POST the submitted answers to serve.py. Never throws — a failed save
    // must not break the exam (plain `http.server` answers 501 here).
    async saveExamProgress(events) {
      this.examSave = { state: 'saving', saved: 0, error: '' };
      try {
        const r = await fetch('api/progress', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ events }),
        });
        let body = null;
        try { body = await r.json(); } catch { body = null; }
        if (r.ok && body && body.ok) {
          this.examSave = { state: 'saved', saved: body.saved, error: '' };
          if (this.progressLoaded) this.loadProgress();
        } else if (body && body.error) {
          this.examSave = { state: 'error', saved: 0, error: `Not saved to disk: ${body.error}` };
        } else {
          this.examSave = { state: 'error', saved: 0, error: '' };
        }
      } catch {
        this.examSave = { state: 'error', saved: 0, error: '' };
      }
    },

    // Short, plain-text description of the chosen answer (for progress.jsonl).
    answerText(q, s) {
      const opt = (i) => `${this.letter(i)}: ${this.shortText(q.options[i], 60)}`;
      let txt = '';
      if (q.type === 'single' || q.type === 'multi') {
        txt = s.picked.slice().sort((a, b) => a - b).map(opt).join(' | ');
      } else if (q.type === 'order') {
        if (s.touched) txt = 'order: ' + s.order.map(i => this.letter(i)).join(' > ');
      } else if (q.type === 'match') {
        if (s.match.some(v => v !== null)) {
          txt = 'match: ' + s.match.map((v, i) => `${i + 1}→${v === null ? '—' : this.letter(v)}`).join(', ');
        }
      }
      return txt.slice(0, 500);
    },

    // Markdown → single-line plain text, capped at `max` chars.
    shortText(md, max) {
      const t = this.plain(md).replace(/^[#>\s-]+/gm, '').replace(/\s+/g, ' ').trim();
      return t.length <= max ? t : t.slice(0, max - 1) + '…';
    },

    // Local time as "YYYY-MM-DDTHH:MM:SS" (matches progress.jsonl `ts`).
    localIso(d) {
      const p = (n) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
             `T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    },

    loadExamLast() {
      try {
        const v = JSON.parse(localStorage.getItem(`exam:${this.topic}`) || 'null');
        return v && typeof v.score === 'number' ? v : null;
      } catch {
        return null;
      }
    },

    saveExamLast(score, total) {
      const d = new Date();
      const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      this.examLast = { score, total, date };
      try {
        localStorage.setItem(`exam:${this.topic}`, JSON.stringify(this.examLast));
      } catch { /* storage unavailable — keep in memory only */ }
    },

    // Informational countdown at real exam pace: 90 min / 65 q ≈ 83 s per question.
    toggleExamTimer() {
      this.examTimerOn = !this.examTimerOn;
      if (this.examTimerOn && !this.examResult) this.startExamTimer();
      else this.stopExamTimer();
    },

    startExamTimer() {
      this.stopExamTimer();
      this.examRemaining = this.exam.length * 83;
      this._examTimer = setInterval(() => {
        if (this.examRemaining > 0) this.examRemaining--;
        else this.stopExamTimer();
      }, 1000);
    },

    stopExamTimer() {
      clearInterval(this._examTimer);
      this._examTimer = null;
    },

    fmtTime(sec) {
      const m = Math.floor(Math.max(0, sec) / 60);
      const s = Math.max(0, sec) % 60;
      return `${m}:${String(s).padStart(2, '0')}`;
    },

    // ---- PROGRESS ----------------------------------------------------------

    // Fetch <topic>/progress.jsonl, parse line by line (bad lines skipped) and
    // pre-compute every view so the template only reads `this.progress`.
    async loadProgress() {
      const topic = this.topic;
      if (!topic) return;
      let text = '';
      let missing = false;
      try {
        const r = await fetch(`${topic}/progress.jsonl`, { cache: 'no-store' });
        if (r.ok) text = await r.text();
        else missing = true;
      } catch {
        missing = true;
      }
      if (topic !== this.topic) return;     // topic switched while loading
      const events = [];
      text.split('\n').forEach((line, i) => {
        if (!line.trim()) return;
        try {
          const e = JSON.parse(line);
          if (e && typeof e === 'object' && ['correct', 'wrong', 'dont_know'].includes(e.result)) {
            e._i = i;
            events.push(e);
          }
        } catch { /* skip malformed line */ }
      });
      this.progressMissing = missing;
      this.progress = this.computeProgress(events);
      this.progressLoaded = true;
      this.setTopicPct(topic, this.overallPct(this.progress));
      this.$nextTick(() => this.spy('progress'));
    },

    // ── Topic picker ────────────────────────────────────────────────
    defaultMeta(slug) {
      return { title: slug.replace(/-/g, ' '), group: 'Other', order: 999, pct: null };
    },

    async loadTopicMeta() {
      await Promise.all(this.topics.map(async (slug) => {
        const meta = this.defaultMeta(slug);
        try {
          const r = await fetch(`${slug}/meta.json`, { cache: 'no-store' });
          if (r.ok) {
            const m = await r.json();
            if (typeof m.title === 'string' && m.title.trim()) meta.title = m.title.trim();
            if (typeof m.group === 'string' && m.group.trim()) meta.group = m.group.trim();
            if (Number.isFinite(m.order)) meta.order = m.order;
          }
        } catch { /* keep fallback label */ }
        try {
          const r = await fetch(`${slug}/progress.jsonl`, { cache: 'no-store' });
          if (r.ok) {
            const events = (await r.text()).split('\n').flatMap((line, i) => {
              if (!line.trim()) return [];
              try {
                const e = JSON.parse(line);
                return (e && ['correct', 'wrong', 'dont_know'].includes(e.result)) ? [{ ...e, _i: i }] : [];
              } catch { return []; }
            });
            meta.pct = this.overallPct(this.computeProgress(events));
          }
        } catch { /* no progress yet */ }
        // Keep a pct already computed by loadProgress() if this fetch had none.
        if (meta.pct === null && this.topicMeta[slug]) meta.pct = this.topicMeta[slug].pct;
        this.topicMeta = { ...this.topicMeta, [slug]: meta };
      }));
      this.buildTopicGroups();
    },

    // Overall mastery = per-task mastery weighted by how many attempts it's based on.
    overallPct(p) {
      if (!p || !p.byTask || !p.byTask.length) return null;
      let num = 0, den = 0;
      for (const t of p.byTask) { num += t.mastery * t.basis; den += t.basis; }
      return den ? Math.round(num / den) : null;
    },

    setTopicPct(slug, pct) {
      if (!this.topicMeta[slug]) return;
      this.topicMeta = { ...this.topicMeta, [slug]: { ...this.topicMeta[slug], pct } };
      this.buildTopicGroups();
    },

    buildTopicGroups() {
      const groups = {};
      for (const slug of this.topics) {
        const m = this.topicMeta[slug] || this.defaultMeta(slug);
        (groups[m.group] = groups[m.group] || []).push({ slug, m });
      }
      this.topicGroups = Object.entries(groups)
        .sort(([a], [b]) => (a === 'Other') - (b === 'Other') || a.localeCompare(b))
        .map(([group, items]) => ({
          group,
          items: items
            .sort((x, y) => x.m.order - y.m.order || x.m.title.localeCompare(y.m.title))
            .map(({ slug, m }) => ({
              slug,
              text: m.pct === null ? m.title : `${m.title} · ${m.pct}%`,
            })),
        }));
    },

    // Mastery rule: for each question id (qid) take its LAST 5 attempts; events
    // without a qid count via the task's LAST 10 such events. Mastery = correct
    // share of those (wrong and "don't know" both count as not correct).
    computeProgress(raw) {
      const evs = raw.slice().sort((a, b) =>
        String(a.ts || '').localeCompare(String(b.ts || '')) || a._i - b._i);
      const counts = { correct: 0, wrong: 0, dont_know: 0 };
      const tasks = {};
      for (const e of evs) {
        // Self-rated flashcard marks show in Recent / Review next, but don't
        // move graded mastery (per-task %, weakest, topic %).
        if (e.source === 'flashcard') continue;
        counts[e.result]++;
        const t = (e.task === undefined || e.task === null || e.task === '') ? '—' : String(e.task);
        if (!tasks[t]) tasks[t] = { task: t, answered: 0, correct: 0, wrong: 0, dont_know: 0, byQid: {}, noQid: [] };
        const row = tasks[t];
        row.answered++;
        row[e.result]++;
        if (e.qid) (row.byQid[e.qid] = row.byQid[e.qid] || []).push(e.result);
        else row.noQid.push(e.result);
      }
      const byTask = Object.values(tasks).map(row => {
        const recent = Object.values(row.byQid).flatMap(rs => rs.slice(-5)).concat(row.noQid.slice(-10));
        const ok = recent.filter(r => r === 'correct').length;
        return {
          task: row.task, answered: row.answered, correct: row.correct, wrong: row.wrong,
          dont_know: row.dont_know, basis: recent.length,
          mastery: recent.length ? Math.round(ok / recent.length * 100) : 0,
        };
      }).sort((a, b) => a.task.localeCompare(b.task, undefined, { numeric: true }));

      const weakest = byTask.filter(t => t.answered >= 2)
        .slice().sort((a, b) => a.mastery - b.mastery || b.answered - a.answered)
        .slice(0, 5);

      // Most recent result per question (qid, else the question text).
      const latest = {};
      for (const e of evs) latest[e.qid ? `id:${e.qid}` : `q:${String(e.question || '').trim().toLowerCase()}`] = e;
      const review = Object.values(latest)
        .filter(e => e.result !== 'correct')
        .sort((a, b) => String(b.ts || '').localeCompare(String(a.ts || '')))
        .map(e => this.progressRow(e));

      // Exam runs, chronological.
      const runs = {};
      for (const e of evs) {
        if (e.source !== 'exam' || !e.run) continue;
        if (!runs[e.run]) runs[e.run] = { run: e.run, ts: String(e.ts || ''), total: 0, correct: 0, dont_know: 0 };
        const r = runs[e.run];
        r.total++;
        if (e.result === 'correct') r.correct++;
        if (e.result === 'dont_know') r.dont_know++;
      }
      const trend = Object.values(runs)
        .sort((a, b) => a.ts.localeCompare(b.ts))
        .map(r => ({ ...r, pct: Math.round(r.correct / r.total * 100), date: this.fmtDate(r.ts) }));

      return {
        total: evs.length,
        counts,
        byTask,
        weakest,
        review,
        trend,
        trendSvg: this.trendSvg(trend),
        recent: evs.slice(-15).reverse().map(e => this.progressRow(e)),
      };
    },

    progressRow(e) {
      return {
        key: `${e._i}`,
        question: String(e.question || '(no question text)'),
        task: (e.task === undefined || e.task === null || e.task === '') ? '—' : String(e.task),
        source: String(e.source || '?'),
        result: e.result,
        date: this.fmtDate(e.ts),
        answer: e.answer ? String(e.answer) : '',
        note: e.note ? String(e.note) : '',
      };
    },

    fmtDate(ts) {
      const s = String(ts || '');
      return s.length >= 16 ? `${s.slice(0, 10)} ${s.slice(11, 16)}` : (s.slice(0, 10) || '—');
    },

    resultLabel(r) {
      return { correct: '✓ correct', wrong: '✗ wrong', dont_know: '? don\'t know' }[r] || r;
    },

    // Exam score per run as an inline SVG bar chart (70% pass line dashed).
    trendSvg(trend) {
      if (!trend.length) return '';
      const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
      const bw = 28, gap = 12, h = 140, top = 16, bottom = 22, left = 34;
      const w = left + trend.length * (bw + gap) + gap;
      const y = (pct) => top + (h - top - bottom) * (1 - pct / 100);
      let out = `<svg class="trend-svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="exam score per run">`;
      for (const g of [0, 50, 100]) {
        out += `<line class="grid" x1="${left}" x2="${w}" y1="${y(g)}" y2="${y(g)}"/>`;
        out += `<text class="axis" x="${left - 6}" y="${y(g) + 4}" text-anchor="end">${g}%</text>`;
      }
      out += `<line class="pass" x1="${left}" x2="${w}" y1="${y(70)}" y2="${y(70)}"/>`;
      trend.forEach((r, i) => {
        const x = left + gap + i * (bw + gap);
        const yy = y(r.pct);
        out += `<rect class="${r.pct >= 70 ? 'ok' : 'no'}" x="${x}" y="${yy}" width="${bw}" height="${Math.max(1, y(0) - yy)}" rx="3">` +
               `<title>${esc(`${r.date} — ${r.correct}/${r.total} correct (${r.pct}%), ${r.dont_know} don't know`)}</title></rect>`;
        out += `<text class="val" x="${x + bw / 2}" y="${yy - 4}" text-anchor="middle">${r.pct}</text>`;
        out += `<text class="axis" x="${x + bw / 2}" y="${h - 6}" text-anchor="middle">${i + 1}</text>`;
      });
      return out + '</svg>';
    },

    setMode(m) {
      this.mode = m;
      this.updateUrl();
      // Re-read progress every time the mode is opened (chat sessions append too).
      if (m === 'progress') this.loadProgress();
      // Re-read plan.md / session.md every time Plan / Lesson is opened (the tutor
      // updates chunk status and appends each taught chunk to session.md).
      if (this.isDocMode()) this.loadDoc(m);
      // Scroll to top of cheatsheet when entering the mode
      if (m === 'cheatsheet') {
        requestAnimationFrame(() => {
          const el = document.getElementById('cheatsheet-content');
          if (el) el.scrollIntoView({ behavior: 'auto', block: 'start' });
        });
        this.$nextTick(() => this.spy('cheatsheet'));
      }
    },

    exerciseMode() { return this.mode === 'exercises'; },

    updateUrl() {
      const params = new URLSearchParams();
      if (this.topic) params.set('topic', this.topic);
      if (this.mode && this.mode !== 'flashcards') params.set('mode', this.mode);
      const qs = params.toString();
      history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
    },

    renderSection(md) {
      return marked.parse(md || '');
    },

    scrollToSection(i) {
      this.scrollToId(`section-${i}`);
    },

    scrollToId(id) {
      const el = document.getElementById(id);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },

    // The known map is keyed by card id. With no saved map, or a legacy one keyed by
    // deck position (shifts when cards are added / removed), rebuild it from the
    // flashcard marks in progress.jsonl (latest mark wins); without any, convert the
    // legacy positions against the current deck.
    async loadKnown() {
      const topic = this.topic;
      const key = `known:${topic}`;
      let saved = null;
      try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch { /* storage unavailable */ }
      const legacy = saved && typeof saved === 'object' && Object.keys(saved).some(k => /^\d+$/.test(k));
      if (saved && typeof saved === 'object' && !legacy) return saved;

      const known = {};
      try {
        const r = await fetch(`${topic}/progress.jsonl`, { cache: 'no-store' });
        if (r.ok) {
          for (const line of (await r.text()).split('\n')) {
            try {
              const e = JSON.parse(line);
              if (e && e.source === 'flashcard' && typeof e.qid === 'string') known[e.qid] = e.result === 'correct';
            } catch { /* skip bad line */ }
          }
        }
      } catch { /* no progress file: static server or offline */ }
      if (!Object.keys(known).length && legacy) {
        for (const [i, v] of Object.entries(saved)) if (this.cardIds[i]) known[this.cardIds[i]] = v;
      }
      try { localStorage.setItem(key, JSON.stringify(known)); } catch { /* storage unavailable */ }
      return known;
    },

    saveKnown() {
      try {
        localStorage.setItem(`known:${this.topic}`, JSON.stringify(this.known));
      } catch { /* storage unavailable — keep in memory only */ }
    },

    applyFilter() {
      const indexed = this.cards.map((card, i) => ({ card, origIndex: i }));
      this.filtered = this.unknownOnly
        ? indexed.filter(x => !this.known[this.cardIds[x.origIndex]])
        : indexed;
    },

    onFilterChange() {
      this.applyFilter();
      this.index = 0;
      this.flipped = false;
    },

    current() {
      return this.filtered[this.index] || { card: { q: '', a: '' }, origIndex: -1 };
    },

    renderQ() { return marked.parse(this.current().card.q || ''); },
    renderA() { return marked.parse(this.current().card.a || ''); },

    flip() {
      if (!this.filtered.length) return;
      this.flipped = !this.flipped;
    },

    next() {
      if (!this.filtered.length) return;
      this.flipped = false;
      this.index = (this.index + 1) % this.filtered.length;
    },

    prev() {
      if (!this.filtered.length) return;
      this.flipped = false;
      this.index = (this.index - 1 + this.filtered.length) % this.filtered.length;
    },

    shuffle() {
      for (let i = this.filtered.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [this.filtered[i], this.filtered[j]] = [this.filtered[j], this.filtered[i]];
      }
      this.index = 0;
      this.flipped = false;
    },

    markKnown(isKnown) {
      const cur = this.current();
      if (cur.origIndex < 0) return;

      // Reassign (not in-place mutate) so Alpine reliably re-runs knownCount()
      // and the status badge. In-place `this.known[id] = x` doesn't always
      // trigger reactivity for Object.values()-based computeds.
      this.known = { ...this.known, [this.cardIds[cur.origIndex]]: isKnown };
      this.saveKnown();
      this.logCard(cur.card, isKnown);

      // Visual flash feedback. Clear first, then set on the next frame so the
      // CSS animation re-triggers even when re-marking with the same value
      // (animations only replay when the class is removed and re-added).
      this.flash = null;
      clearTimeout(this._flashTimer);
      requestAnimationFrame(() => {
        this.flash = isKnown ? 'known' : 'unknown';
        this._flashTimer = setTimeout(() => { this.flash = null; }, 450);
      });

      // In "unknown only" mode, marking a card KNOWN removes it from the deck
      // (it's no longer unknown) and shows the next one.
      if (this.unknownOnly && isKnown) {
        this.filtered.splice(this.index, 1);
        if (this.index >= this.filtered.length) {
          this.index = Math.max(0, this.filtered.length - 1);
        }
        this.flipped = false;
      }
      // Otherwise: STAY on the card so you can flip back, re-read, or change
      // your mark (k <-> u). Advance manually with → / Next.
    },

    // Each mark also becomes a progress event (source 'flashcard', self-rated:
    // known = correct, unknown = wrong) so the tutor sees which cards you miss.
    // Debounced per card: flipping k <-> u quickly logs only the final mark.
    // Never throws; a plain static server just doesn't save.
    logCard(card, isKnown) {
      const q = String((card && card.q) || '');
      if (!q || !this.topic) return;
      const qid = cardId(q);
      const pad = (n) => String(n).padStart(2, '0');
      const d = new Date();
      const ts = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
      const ev = {
        ts, topic: this.topic, source: 'flashcard', task: String((card && card.task) || ''), qid,
        question: this.shortText(q, 200), result: isKnown ? 'correct' : 'wrong', attempt: 1,
      };
      this._cardLog = this._cardLog || {};
      this._cardLog[`${this.topic}|${qid}`] = ev;
      clearTimeout(this._cardTimer);
      this._cardTimer = setTimeout(() => this.flushCardLog(), 3000);
      if (!this._cardHook) {
        this._cardHook = true;
        window.addEventListener('pagehide', () => this.flushCardLog(true));
      }
    },

    flushCardLog(beacon = false) {
      clearTimeout(this._cardTimer);
      const pending = Object.values(this._cardLog || {});
      this._cardLog = {};
      const byTopic = {};
      for (const ev of pending) (byTopic[ev.topic] = byTopic[ev.topic] || []).push(ev);
      for (const events of Object.values(byTopic)) {
        const body = JSON.stringify({ events });
        try {
          if (beacon && navigator.sendBeacon) { navigator.sendBeacon('api/progress', body); continue; }
          fetch('api/progress', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
            .then(r => { if (r.ok && this.progressLoaded && events[0].topic === this.topic) this.loadProgress(); })
            .catch(() => { /* not saved: static server or offline */ });
        } catch { /* ignore */ }
      }
    },

    // Status of the current card: 'known' | 'unknown' | 'none'
    currentStatus() {
      const cur = this.current();
      if (cur.origIndex < 0) return 'none';
      const v = this.known[this.cardIds[cur.origIndex]];
      if (v === true) return 'known';
      if (v === false) return 'unknown';
      return 'none';
    },

    statusLabel() {
      return { known: '✓ Known', unknown: '✗ Needs practice', none: 'Unmarked' }[this.currentStatus()];
    },

    knownCount() {
      return this.cardIds.filter(id => this.known[id] === true).length;
    },

    unknownCount() {
      return this.cardIds.filter(id => this.known[id] === false).length;
    },

    resetKnown() {
      if (!confirm('Reset known/unknown progress for this topic?')) return;
      this.known = {};
      this.saveKnown();     // keep an empty map so the next load doesn't rebuild it from history
      this.applyFilter();
      this.index = 0;
      this.flipped = false;
    },
  }));
});
