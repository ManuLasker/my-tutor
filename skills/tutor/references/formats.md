# File formats

Read the section you need before writing that file. `python3 ${CLAUDE_SKILL_DIR}/scripts/validate.py <slug>` checks every file below (exit 0 = all good). Run it after writing or changing any of them.

## Contents

- [plan.md and the plan map standard](#planmd)
- [session.md](#sessionmd)
- [flashcards.json](#flashcardsjson)
- [cheatsheet.json](#cheatsheetjson)
- [exercises.json and exercises/](#exercisesjson)
- [exam.json](#examjson)
- [Writing quiz options](#writing-quiz-options)
- [progress.jsonl](#progressjsonl)
- [quiz-history.md and INDEX.md](#quiz-historymd-and-indexmd)

## plan.md

```markdown
# Plan — <topic>

## Goal
## Probe result        (table: | strand | status ✅/❌ |)
## Dependency map      (the mermaid block below)
## Chunks              (table below)
```

**Plan map standard.** The viewer's Plan mode depends on it, so follow it exactly:

- The map is a `flowchart LR` block. Node ids: chunks `c1…cN`, already-known foundations `k1…kN`, the sink `goal`. A gap the probe found inside a chunk reuses that chunk's id with class `gap`.
- The block ends with these classDefs, verbatim:
  ```
  classDef done fill:#12261e,stroke:#3fb950,color:#e6edf3
  classDef doing fill:#0d2240,stroke:#58a6ff,color:#e6edf3,stroke-width:2px
  classDef todo fill:#161b22,stroke:#30363d,color:#8b949e
  classDef known fill:#12261e,stroke:#3fb950,color:#e6edf3,stroke-dasharray:4 3
  classDef gap fill:#2a1215,stroke:#f85149,color:#e6edf3
  classDef goal fill:#1f1a0d,stroke:#d29922,color:#e6edf3
  ```
  followed by `class` lines assigning every node, e.g. `class c1,c2 done`, `class c3 doing`, `class c4,c5 todo`, `class k1,k2 known`, `class goal goal`. Emoji in labels are optional; the colors carry the status.
- Chunk table: first column header `#` with values `c1…cN` matching the node ids, plus a **Status** column: ⬜ to do · 🔄 in progress · ✅ done (and ❌ gap where relevant). E.g. `| # | chunk | exam tasks | depth | status |`.
- Example:
  ```mermaid
  flowchart LR
    k1["ML basics"] --> c1["Tokens & embeddings"]
    c1 --> c2["Transformers"] --> c3["Prompting"] --> goal["🎯 Domain 2 exam-ready"]
    classDef done fill:#12261e,stroke:#3fb950,color:#e6edf3
    classDef doing fill:#0d2240,stroke:#58a6ff,color:#e6edf3,stroke-width:2px
    classDef todo fill:#161b22,stroke:#30363d,color:#8b949e
    classDef known fill:#12261e,stroke:#3fb950,color:#e6edf3,stroke-dasharray:4 3
    classDef gap fill:#2a1215,stroke:#f85149,color:#e6edf3
    classDef goal fill:#1f1a0d,stroke:#d29922,color:#e6edf3
    class c1 done
    class c2 doing
    class c3 todo
    class k1 known
    class goal goal
  ```
- **Keep it current:** when a chunk starts, set its node to `doing` and its Status to 🔄. After its check-for-understanding, set `done` and ✅. Update the `class` lines and the Status column in the same edit.
- In the viewer, a node whose id matches a row's `#` cell is clickable (it jumps to that row), and a status legend sits under the map.

## session.md

The complete lesson, not a summary, so the learner can re-read it later. Append each chunk as it is taught; tidy it at the end.

It is rendered by `marked`, where a single newline does NOT break a line:

- Separate every paragraph, list, table, code fence and heading with a **blank line**. Text directly after a table row gets swallowed into the table.
- Never pack several items into one line with `·` or `;`. Use a real `-` bullet list (nested for sub-points). `·` is fine inside code blocks and table cells.
- Lead-in labels (`Checks:`, `Traps:`, `Gotchas:`) go on their own line in bold, then a blank line, then a bullet list.

Template:

```markdown
# <Topic>

> Taught: YYYY-MM-DD

## TL;DR
<3 bullets>

## Explanation
<the full teaching content with diagrams>

## Key Examples
<code blocks>

## Gotchas
<list of traps>

## Visualization
<link as /<slug>/interactive/ (root-relative: the lesson renders inside /study.html)>

## Related Topics
<plain names, no fake wikilinks>
```

## flashcards.json

```json
[
  { "q": "What does -r do in read?", "a": "Treats backslashes literally (raw mode), so `\\n` is not interpreted." },
  { "q": "How do you change the field separator for read?", "a": "Set IFS inline: `IFS=',' read -r a b`", "task": "1.2" }
]
```

- `q` and `a` are markdown (backticks, fenced blocks, tables). Optional `task` ties the card to a plan/exam task.
- **Atomic:** one fact per card.
- **Count scales with the topic:** about 3–5 cards per distinct concept, gotcha or flag taught. Small topics land around 20–40, wide ones well past 100. Never pad with near-duplicates.
- **Cover the gotchas**, not just definitions. Every "wait, why doesn't this work?" moment and every clarifying question the learner asked becomes a card.
- Card ids in progress are a hash of `q`. Editing a card's question starts its flashcard history fresh, so fix typos sparingly.

## cheatsheet.json

```json
[
  { "title": "Section name", "content": "markdown body..." }
]
```

- About 8–20 reference-shaped sections ("I need this in 6 months"), each roughly 10–40 lines: operator tables, idiom recipes, flag references, gotcha lists. Denser and more table-shaped than `session.md`; don't copy long prose from it.
- **The last section is always "References & further reading":** official docs and manuals grouped per tool, deep-linked to the relevant page or anchor where useful. **Verify every URL** (web fetch) before writing it; don't type doc URLs from memory. A broken link is worse than none.

## exercises.json

The learner works in their real terminal against input files on disk, then pastes the output into the viewer, which compares it per test case.

```json
[
  {
    "id": "grep-files-with-match",
    "title": "List files that contain a pattern",
    "difficulty": "easy",
    "prompt": "markdown — what to produce. Be EXACT about output format (sorted? one per line?).",
    "setup": "short note: cd into the dir / pipe the file / etc.",
    "tests": [
      { "input": "exercises/<id>/t1", "expected": "a.log\nc.log", "unordered": false },
      { "input": "exercises/<id>/t2.json", "expected": "..." }
    ],
    "solution": "the reference command(s)",
    "explanation": "why the solution works",
    "hints": ["concept nudge", "closer", "near-spoiler"]
  }
]
```

- 10–15 exercises, easy → hard, at least one per major concept taught. `difficulty` is `easy | medium | hard`.
- Inputs live under `<slug>/exercises/<id>/`: a file (`t1.json`, `t1.txt`) or a directory (`t1/` with several files). `tests[].input` is relative to the topic folder.
- **Deterministic output is required**, because the comparison is exact. Bake determinism into the task (`sort`, anchors, strip `./`), or set `"unordered": true` (both sides get sorted). The comparator trims trailing whitespace per line and drops outer blank lines. Store tabs/newlines as `\t` / `\n`.
- **Generate `expected` by running the reference solution** on each input. Never write expected output by hand.
- Verify before finishing: run each `solution` on each input (cd into directory inputs, substitute the file name for file inputs) and confirm the normalized stdout equals `expected`.
- **Non-CLI topics** (e.g. certification prep): scenario drills. The input `.txt` lists numbered scenarios; `expected` has one `<n> <token>` line per scenario, using an allowed token list stated in the prompt. Compute calculation drills with code, never by hand.

## exam.json

About 12–15 exam-style questions, more for certification topics. **Research first:** the official exam guide/objectives, plus reputable prep sources for question style. Write **original** questions. Never copy, and never use leaked "exam dump" sites. Also append the questions asked in the chat quiz, with `"source": "tutor quiz"`.

```json
{ "id": "d1-q01", "type": "single|multi|order|match", "task": "1.2",
  "question": "markdown (multi ends with '(Select TWO.)')",
  "options": ["markdown", "..."],
  "prompts": ["markdown"],
  "answer": [0],
  "explanation": "why right + why each tempting distractor is wrong",
  "source": "https://… URL, or \"tutor quiz\"" }
```

- `single`: 4 options, `answer=[i]`.
- `multi`: 5 options, `answer` = sorted indices of all correct options.
- `order`: options in SHUFFLED display order; `answer` = option indices in the correct order (must not be the identity).
- `match`: 3–5 `prompts` (only for match); `answer[k]` = option index for `prompts[k]`.
- `source` renders as a link only when it is an `http(s)` URL.

## Writing quiz options

Applies to chat quizzes, probes and `exam.json`.

- **Options are bare claims.** No justification inside an option ("…because…"). Reasoning goes in the explanation.
- **Build distractors by mutation:** write the correct claim first, then change it to match one specific, real misconception (wrong direction, wrong service, wrong limit, wrong stage). Keep the same skeleton, length and register.
- Each distractor is **tempting yet unambiguously wrong**. No "arguably also right" options.
- **No shape tells:** no asymmetric bold, and no option that is longer, more hedged or more precise than the rest. If someone could pick the answer without knowing the topic, rewrite.

## progress.jsonl

One JSON event per graded answer. **Only `scripts/log_progress.py` (chat) and `serve.py` (viewer) write it. Never hand-edit it.**

```json
{"ts":"2026-09-30T23:40:00","topic":"<slug>","source":"chat|exam|probe|backfill|flashcard","task":"1.1","qid":"d1-q04","question":"≤200 chars","result":"correct|wrong|dont_know","attempt":1,"answer":"optional ≤500","note":"optional ≤500","run":"optional id"}
```

- Required: `ts, topic, source, task` (may be `""`), `question, result, attempt` (int ≥ 1). No other fields.
- `ts`: `YYYY-MM-DDTHH:MM:SS`, local time.
- `task` ≤ 20, `qid` ≤ 80, `run` ≤ 80 chars, using only letters, digits and `. _ : # -`. A bad value is rejected, not truncated.
- `question` is markdown-stripped and truncated to 200; `answer`/`note` are truncated to 500.
- `topic` must be registered (`scripts/topics.py add`).
- Sources: `chat`/`probe` come from you, `exam` and `flashcard` (self-rated known/unknown) come from the viewer, `backfill` is for old imports. Flashcard events show under Recent and Review next but don't count toward mastery.
- Use a stable `qid` whenever a question may be asked again (the `exam.json` id, `word:<word>` for vocab, or your own like `c3-temp-ranking`). Spaced review (`--due`) groups history by `qid`, falling back to the question text.

## quiz-history.md and INDEX.md

`<slug>/quiz-history.md` is a readable summary per quiz (`progress.jsonl` holds the per-answer record):

```markdown
## YYYY-MM-DD HH:MM

- Q1: <question> — ✅/❌ "<learner's answer>"
- Q2: <question> — ✅/❌ "<learner's answer>"
- Score: 4/5
- Notes: <what tripped them up>
```

`INDEX.md` has one line per topic, sorted alphabetically:

```markdown
- [<topic>](./<slug>/session.md) — taught YYYY-MM-DD — last quiz: 4/5
```
