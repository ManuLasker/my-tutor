# Study viewer — contract

Read this only when changing the viewer (`assets/viewer/study.html`, `study.css`, `study.js`) or `scripts/serve.py`. The viewer ships with the skill: never regenerate it from this description. Edit the shipped files, keep this contract in sync with them, and don't invent new field names or localStorage key formats (learners already have saved state).

**Serving.** `scripts/serve.py` serves the app files (`study.*`, `favicon.svg`, `vendor/`) from `assets/viewer/` and everything else from `$TUTOR_HOME`. It refuses hidden paths (`.git/`, `.claude/`), only lists directories under `<topic>/exercises/` (Exercises mode parses those listings), and accepts `POST /api/progress` (`{"events":[…]}`, 1–200 events of one topic, validated with `log_progress.normalize/validate`). `sendBeacon` posts arrive as `text/plain`, and the server accepts them too.

## Modes

A single global Alpine.js app with **seven modes**:
- **Plan mode** (first button): renders `<slug>/plan.md` (written in the plan step) — goal, probe result, mermaid dependency map (nodes colored by status, with a legend; clicking a chunk node jumps to its row in the chunk table), chunk status; re-read every time the mode is opened
- **Lesson mode** (second button): renders `<slug>/session.md` (appended after each chunk, tidied at the end) as a readable doc with a `##` / `###` ToC; re-read every time the mode is opened
- **Flashcards mode**: drill `<slug>/flashcards.json` Q&A pairs with flip/shuffle/known-unknown filter. Each known/unknown mark is also posted as a `source: "flashcard"` progress event (`qid` = `card:` + FNV-1a hex of `q`, `task` = the card's optional `task`), debounced 3 s per card so a quick k↔u change logs only the final mark, flushed with `sendBeacon` on `pagehide`
- **Cheat sheet mode**: render `<slug>/cheatsheet.json` as a reference doc with ToC + scrollable sections
- **Exercises mode**: practice writing real code against `<slug>/exercises.json` — terminal-based, paste-output-back checking with test cases (see formats.md § exercises.json)
- **Exam mode**: timed-optional practice exam from `<slug>/exam.json` — single / multi / order / match questions, per-question "I don't know" + optional note, per-question Check, Submit with score + per-task breakdown, each answer saved to `<slug>/progress.jsonl` (see formats.md § exam.json)
- **Progress mode**: reads `<slug>/progress.jsonl` — per-task mastery (flashcard events excluded), weakest tasks, review next (questions whose latest result isn't correct), exam trend (score per submitted exam), recent activity

All modes share:
- grouped topic picker (`<select>` with one `<optgroup>` per group) built from `topics.json` + each `<slug>/meta.json`, options showing mastery %
- markdown rendering via `marked` with `highlight.js` code highlighting; ```` ```mermaid ```` fences render as diagrams (Mermaid v11, `vendor/mermaid.min.js`) in every mode, each with pan / zoom / fullscreen (`vendor/svg-pan-zoom.min.js`)
- localStorage for per-topic flashcard progress
- URL state via `?topic=<slug>&mode=<mode>`

Keyboard shortcuts (flashcards mode): space (flip), ← → (nav), s (shuffle), k/u (mark known/unknown), Shift+R (reset progress).

**HTML** — `study.html`
- Loads `marked@4.x`, `highlight.js@11.x`, `mermaid@11.x` (UMD bundle `vendor/mermaid.min.js`, exact version in a comment; CDN fallback via `onerror`), `svg-pan-zoom@3.x` (UMD bundle `vendor/svg-pan-zoom.min.js` defining global `svgPanZoom`, exact version in a comment; same `onerror` CDN fallback, which fires `svgpanzoom-ready`) and `alpinejs@3.x`. Prefer self-hosted assets in `vendor/` to avoid tracking-prevention warnings; fall back to CDN if vendor files missing.
- Links a favicon: `<link rel="icon" type="image/svg+xml" href="favicon.svg">`. The root holds a self-contained `favicon.svg` (a rounded dark square `#161b22`/`#30363d` with a `#58a6ff` terminal `>_` glyph). It ships in `assets/viewer/`.
- Single Alpine component bound via `x-data="study"`.
- Header has: grouped topic `<select>` (`<optgroup>` per group), **mode toggle** (Plan / Lesson / Flashcards / Cheat sheet / Exercises / Exam / Progress), and mode-specific controls.
- Card area uses CSS 3D flip (`transform-style: preserve-3d`, `backface-visibility: hidden`).
- Cheat-sheet area uses a two-column layout: `aside.toc` (sticky) + `article.content`.
- Footer lists keyboard hints (flashcards mode only).

**JS** — `study.js`
- Registers Alpine component `study` with state including: `topics, topic, mode, cards, filtered, index, flipped, unknownOnly, known, cheatsheet`.
- `init()` fetches `topics.json`, picks topic and mode from URL query params (`?topic=<slug>&mode=<plan|lesson|flashcards|cheatsheet|exercises|exam|progress>`) or defaults (no `?mode=` → flashcards).
- `loadTopic()` fetches `<topic>/flashcards.json`, `<topic>/cheatsheet.json`, `<topic>/exercises.json` AND `<topic>/exam.json`, falling back to empty arrays if missing.
- `setMode(m)` swaps mode (`plan`|`lesson`|`flashcards`|`cheatsheet`|`exercises`|`exam`|`progress`) and updates URL. Entering `progress` re-reads `progress.jsonl` (chat sessions append too); entering `plan` / `lesson` re-reads `<topic>/plan.md` / `<topic>/session.md` (`cache: 'no-store'`).
- **Plan + Lesson share one markdown-doc view**: `loadDoc(kind)` (`loadPlan()` / `loadLesson()`) pre-renders `docs[kind] = {loaded, missing, html, toc}`; the ToC lists `##` and `###` headings (`###` indented, current section highlighted by an IntersectionObserver scroll-spy), sticky and independently scrolling; ↻ Reload in the header. **Lesson mode**: missing `session.md` → empty state "No lesson notes for this topic yet — the tutor writes session.md as each chunk is taught." Plan-only behaviors (node ↔ row click-through, legend) apply only inside `.plan-body`.
- **Plan mode**: `loadPlan()` fetches `<topic>/plan.md` (when entering the mode, or in `loadTopic()` when already in it) and pre-renders `docs.plan` (html + ToC from its headings) so the template stays pure. Missing file → empty state "No plan for this topic yet — the tutor writes one in the plan step, before teaching.". Single readable column (+ small ToC), collapses under 720px. The map follows the plan map standard (formats.md § plan.md): after the diagram renders, nodes whose id (data-id, or parsed from mermaid's `…flowchart-<id>-<n>` element id) matches the first cell of a row in a table whose first header is `#` get `cursor:pointer` + a hover outline; clicking one smooth-scrolls to that row and highlights it briefly, clicking the row's id pulses the node. Plain DOM listeners on the rendered SVG — `securityLevel` stays `'strict'`, no mermaid `click` directives. A legend (done / in progress / to do / known / gap / goal, same colors) sits under a map that uses the standard classDefs.
- **Exam mode**: per-question state pre-built in `loadTopic()` via `resetExam()`; `eq(id)` is a PURE getter; all updates go through `examPatch()` (reassign, never mutate in place). Single = radios, multi = checkboxes + "Select N", order = ↑/↓ buttons, match = one `<select>` per prompt (options lettered A, B, C…). Per question: an **"I don't know"** toggle (exclusive with answering — turning it on clears the answer; shown yellow as `? don't know`, never a red ✗) and an optional **note** (≤500 chars); the note is also updated via `examPatch()`. Check grades one question and shows explanation + source (a link only when `source` is an `http(s)` URL; anything else, e.g. `tutor quiz`, is plain text); Submit grades all (unanswered = wrong, don't know counted separately) → total %, pass/fail at 70%, per-task breakdown, then POSTs one event per question (`source: "exam"`, shared `run`) to `/api/progress` on `serve.py` and shows a saved / not-saved status (a plain static server can't save; the exam still works). Retake resets and shuffles question order (never option order). Optional informational timer = n × 83 s. Only the last result persists: `localStorage['exam:'+topic] = {score,total,date}` (try/catch).
- `scrollToSection(i)` smooth-scrolls within the cheat sheet content.
- Keyboard shortcuts (flashcards mode only): **space** flip · **←/→** prev/next · **s** shuffle · **k** mark known · **u** mark unknown · **Shift+R** reset progress. The keydown handler must early-return in every mode except `flashcards` (plan, lesson, cheatsheet, exercises, exam, progress — don't hijack typing in answer textareas / notes), and while a diagram is fullscreen / overlaid (`Mermaid.isModal()`).
- **Exercises mode**: `exState` (per-exercise transient UI state, keyed by exercise id) is **pre-built in `loadTopic()`** for every exercise + test, so `st(id, testIdx)` is a PURE getter — never lazily mutate reactive state during render (causes reactive loops). `checkTest(id, ti)` normalizes both pasted and expected (trimEnd each line, drop outer blank lines, sort if `unordered`) and sets `pass`/`fail`. `revealHint(id)` increments `hintsShown`. Exercise progress is NOT persisted (unlike flashcards).
- Markdown rendering: `marked.parse()` with a `highlight` callback delegating to `hljs.highlight`.
- **Mermaid**: a `marked` renderer override turns ```` ```mermaid ```` fences (never sent to highlight.js) into `<div class="mermaid-block" data-src="…escaped…">` — so it works in every mode (plan, lesson, cards, cheat sheet, exercises, exam). A `MutationObserver` renders new blocks after Alpine updates the DOM, one at a time via async `mermaid.render(uniqueId, src)`; `data-state` marks each block so it renders once (no loops / duplicate ids), and fresh `x-html` output (topic / card / mode change) renders again. Init: `startOnLoad:false`, `securityLevel:'strict'`, theme `base` with gh-dark `themeVariables`. Failure → source in a `<pre>` with a small error note. **Pan / zoom / fullscreen everywhere:** each rendered diagram gets one `svgPanZoom` instance (registry `Mermaid._pz`, created lazily once its viewport has a width, destroyed when its block leaves the DOM — no leaks, no duplicates) inside a viewport whose height is the fitted diagram height capped at `--mmd-max-h` (420px desktop, 320px under 720px, smaller inside cards). Initial view = fit + center, but never below 75% of natural size (larger diagrams start top-left and are panned — no horizontal page scroll). Overlay toolbar ＋ / − / ⟲ reset / ⛶ fullscreen (Fullscreen API on the block; fallback = fixed overlay with ✕ Close + Esc), re-fit on enter / exit / resize (ResizeObserver). Drag pans; ctrl/⌘ + wheel or trackpad pinch zooms (plain wheel keeps scrolling the page; in fullscreen the plain wheel zooms); touch: two-finger pinch / pan, one finger scrolls the page. Zoom 0.3–6× natural, step 1.25×. A small hint says "ctrl/⌘ + scroll to zoom · drag to pan". Toolbar clicks and drags don't flip a flashcard. If svg-pan-zoom is unavailable, diagrams fall back to a horizontal-scroll wrapper, never below 75% of natural size.
- "Unknown only" filter: hides cards where `known[origIndex] === true`.
- Persists known map to `localStorage[\`known:${topic}\`]` on every mark.
- **Marking (`markKnown`) must REASSIGN `this.known` (`this.known = {...this.known, [i]: v}`), not mutate in place** — in-place `this.known[i] = v` does not reliably re-trigger `Object.values()`-based computeds (knownCount/unknownCount/status badge).
- **Marking does NOT auto-advance** (except in unknown-only mode where marking KNOWN removes the card). Staying put lets the user change a mark (k↔u) on the same card. Manual advance via → / Next button.
- **Visual feedback on mark**: a flash animation (`flash` state, cleared via `requestAnimationFrame` + timeout so it replays on repeat marks) plus a per-card status badge (`currentStatus()` → known/unknown/none) and both `✓ known` / `✗ unknown` counts in the header.
- **DO NOT** also put `x-init="init()"` in the HTML — Alpine 3 auto-calls `init()` on a component that defines it. Both = double init = double listeners = double event handling.

**CSS** — `study.css`
- Dark theme (gh-dark palette: `#0e1116` bg, `#161b22` surface, `#30363d` border, `#58a6ff` accent).
- Card flips on `.card.flipped { transform: rotateY(180deg) }`.
- `.face` has `backface-visibility: hidden`; `.face.back` is pre-rotated 180°.
- `.mode-toggle` is a pill-grouped row of seven buttons; active button uses accent background.
- `.cheatsheet-layout` / `.exercises-layout` are `display: grid` (ToC + content); both collapse to single column under 720px.
- `.toc` is sticky, scroll independently from `.content`.
- **One shared sidebar style in every mode that has one** (Plan, Lesson, Cheat sheet, Exercises, Exam, Progress): same width (260px), title, item typography and spacing, from one rule set (`.toc`, `.toc-title`, `.toc-item`, `.toc-item.active`, `.toc-sub`, `.toc-num`, `.toc-badge`) — no per-mode overrides. One active style everywhere (subtle bg + accent text + accent left bar). Numbered lists (Exercises, Exam) align number / label / badge in fixed columns; document-like lists (Plan, Lesson, Cheat sheet, Progress) use the shared scroll-spy to highlight the current section.
- On desktop the header is sticky; a ResizeObserver writes its real height to a CSS variable that positions the sticky sidebar and scroll targets, so every mode lines up even if the header wraps. Keep header controls compact so it stays one row in sidebar modes. Under 720px the header isn't sticky and the sidebar sits above the content at full width.
- Exercises: `.diff` difficulty badge (easy/medium/hard color), `.test-block` with `.test-paste` textarea, `.test-result.pass`/`.fail`, `.test-diff` two-column expected-vs-got, collapsible `.hints`/`.solution`. Reuse `--ok`/`--no`/`--accent`.
- Monospace font for code spans/blocks.

**topics.json** — JSON array of slug strings:
```json
["bash-grep-json-key-to-files-map", "react-hooks-deep-dive"]
```

**`<slug>/meta.json`** — `{title, group, order}`. The header picker is a `<select>` with one `<optgroup>` per group, options labelled `title · NN%` where NN is the topic's overall mastery (per-task Progress mastery weighted by its attempt basis; omitted when there's no progress.jsonl). State is pre-built in `topicMeta` / `topicGroups` (pure getters); `loadProgress()` refreshes the current topic's %.

**`<slug>/flashcards.json`** — array of `{q, a}` objects (markdown bodies).
**`<slug>/cheatsheet.json`** — array of `{title, content}` objects (markdown bodies, ordered).
**`<slug>/exercises.json`** — array of `{id, title, difficulty, prompt, setup, tests:[{input, expected, unordered?}], solution, explanation, hints[]}`. `tests[].input` is a path (relative to topic dir) to an on-disk file or dir under `<slug>/exercises/<id>/`. Comparator normalizes: trimEnd per line, drop outer blank lines, sort if `unordered`.
**`<slug>/exam.json`** — array of `{id, type, task, question, options[], prompts[]?, answer[], explanation, source?}` (see formats.md).

