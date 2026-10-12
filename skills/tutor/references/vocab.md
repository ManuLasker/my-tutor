# Vocabulary deck mode (language learning from books)

For words the user collected while reading. The script `${CLAUDE_SKILL_DIR}/scripts/build_vocab_deck.py` generates the deck files deterministically (flashcards, cheat sheet, exercises, exam, the top of `session.md`). **Never hand-write those files and never edit the user's word list** (it is read-only input — give the user the line to paste instead). After the deck exists, learning runs in two phases (see **Learning phases** below): self-study + chat Q&A, then a regular lesson.

## Returning to an existing deck

A vocab topic's `session.md` says "practice deck". Route by what exists:
- **No `plan.md`:** the learner is in Phase 1. Answer their questions and offer to start the lesson when they're ready.
- **`plan.md` exists:** resume the plan. Use the SKILL.md Step 1 menu, with weak batches as option 0 and option 4 = a fresh probe + a new plan. Skip "new exercises": the deck has its own.
- **The word list changed** (the learner added words): rebuild with `--force` (see Rebuild below).

## New deck

**Source format** (one paragraph per entry; the learner's word-list folder is in `learner.md` under Paths):
`**word** (optional note) — definition. Example: "Sentence from the book."`

**What it builds** — two skills, practised in order per batch of 10 (book order):
- 🔎 **Recognise** (word + book sentence → meaning): flashcards, exam task `bNN-recognise` (match 5 words → meanings + 2 decoys).
- ✍️ **Produce** (blank / meaning → word): flashcards, Exercises tab (`t1` blanks + word bank, needs the right form; `t2` meanings only, dictionary form; typed, lowercase, exact match), exam task `bNN-produce`.
- Flashcards are ordered per batch: 10 recognise, then the same 10 as produce. Entries whose note contains "story term" are recognise-only.

**Flow:**
1. **Ask** (one question round, skip what's already clear): the word-list file (list the folder named in `learner.md`; ask for it and save it there if missing), the **group** (one per book, e.g. `English · Dune` — reuse the exact existing group string from other `meta.json` files), the **title** (`Volume 2`), and **order**. Derive the slug `<book-short>-vol<N>-vocab` (e.g. `dune-vol2-vocab`) and `--book` label (`Dune Vol. 2`).
2. **Dry run** — touches nothing:
   ```bash
   uv run "${CLAUDE_SKILL_DIR}/scripts/build_vocab_deck.py" --source <file> --slug <slug> \
     --group "<group>" --title "<title>" --order <n> --book "<label>" --dry-run
   ```
   Exit 2 lists PROBLEMS: an entry with no example sentence, or a word the script can't find in its sentence. Fix via an overrides JSON in the scratchpad — `{"examples": {"word": "Natural practice sentence."}, "story_terms": ["Name"], "repeats": ["word"]}` — write a sentence that uses the word exactly as the headword spells it, tell the user which sentences you wrote, and rerun with `--overrides <path>`. Written sentences are labelled "not from the book" in the deck.

   **Repeats across volumes.** The dry-run JSON also has `repeats` and `similar`. A word already owned by an earlier vocab deck (exact headword, any book; ownership = `<slug>/vocab-words.json`, oldest deck wins) is **left out** of the new deck; on install it is logged once as `dont_know` (source `probe`, qid `word:<word>`, task = its batch `bNN-recognise`) in the earlier deck, and listed in the new deck's cheat sheet. Before installing, show the user the repeats ("you met these again: feeble, limp → Volume 1 needs retraining") and **ask about each `similar` look-alike** (`flinching` vs Volume 1's `flinch`): same word → add it to overrides `repeats`; different word (e.g. `spool` noun vs `spooled` verb) → keep. Rebuilds never re-log, and rebuilding an older deck never loses words to a newer one.
3. **Install** — the same command without `--dry-run`. It refuses to overwrite an existing slug; `--force` rebuilds (backs up the folder to `<TUTOR_HOME>-backups/`, keeps `progress.jsonl` / `quiz-history.md` / `plan.md` and everything in `session.md` from the `<!-- tutor-notes -->` line on, reuses the stored `vocab-overrides.json`). It registers the slug in `topics.json` and adds/updates the `INDEX.md` line itself.
4. **Report** counts from the script's JSON line, the viewer URL, any written sentences, and the repeats logged per earlier volume. If an earlier volume now has `dont_know` gaps, suggest retraining it first (its weak batches) before starting the new one. Close by explaining Phase 1: study in the viewer, bring questions here, and say when you're ready for the lesson.

**Rebuild** when the user adds words to a list they are still reading: same command + `--force`. Batch ids are stable (book order), so earlier progress still lines up.

### Learning phases

**Phase 1 — self-study + Q&A** (right after install, until the learner says they're ready). The learner studies on their own in the viewer (Flashcards → Exercises → Exam, batch by batch) and comes to chat with questions. In this phase:
- Answer word questions **Socratically**, like any other topic: first a guiding question from the context ("what would people use, together with branches, to build a shelter that keeps rain out?"), or a part-of-speech nudge ("is it a thing or a description of the shelter?"); ask it and **stop the turn** — don't answer it in the same message; after the learner's guess, confirm or correct and add the meaning, collocations, and how it differs from a look-alike or a nearby word in the sentence (e.g. `tarps` vs the card's word `makeshift`). Say which card / batch the sentence belongs to (`grep` `flashcards.json`). Answer directly only after one guiding question didn't land, or if the learner says "just tell me".
- Then one short check question (a new context, not the book sentence). It has a right answer → logging rule (`--task bNN-recognise|bNN-produce`, `--source chat`).
- A word the learner wants added → give the exact line to paste into their list (end of file keeps every existing card in place), then rebuild with `--force` when they confirm.
- Don't push the lesson; at most mention once "say when you're ready and we'll start the lesson". Suggest probing the day after studying, not straight away (tests retention, not short-term memory).

**Phase 2 — the lesson** (learner says ready / "start the lesson" / "probe me"). Run the regular SKILL.md Step 2 with batches as chunks (the topic is already registered):
- **Probe** — 2 words per batch (one recognise, one produce, random), one at a time, "I don't know" + notes allowed, logged with `--source probe --task bNN-recognise|bNN-produce --qid word:<word>`. With many batches, stop a strand early if both words of the previous 2 batches were don't know — the rest is "to do", not tested.
- **Plan** — `plan.md` per the Plan map standard: one chunk per batch (`c1` = batch 01 …), class `known` for a batch with both probe words right (node id stays `cN`; Status ✅), `gap` for any miss (❌), `todo` for untested; `goal` = "🎯 all <N> words: recognise + produce". Chunk table `| # | batch | words | probe | status |`. Teaching order: gaps first (book order), then untested; known batches only get a review pass at the end. Show it, wait for the OK.
- **Teach** — per batch: set it 🔄 `doing`; for each missed or untested word, Socratic: show the book sentence, ask what it could mean from context, then confirm + a second context + collocations / look-alike traps; then a mini-quiz of the batch (mix recognise and produce, every answer logged; produce accepts any correct form). Batch done when every word was answered right once → ✅ `done`. 3–5 words between pauses.
- **Save as you go** — after each batch, append to `session.md` **below** a single `<!-- tutor-notes -->` line (add it once, after the generated part, followed by `## Lesson notes`; never edit above it — rebuilds regenerate that part and keep the notes): a `### Batch NN` section with the words that tripped the learner, the extra contexts used and the traps. Update `plan.md` statuses in the same step.
- **Steps 3–7** — Q&A loop as usual; skip generating flashcards / cheat sheet / exercises / exam (the deck has them); the Step 5 quiz is a final mixed round across all batches (log each, and append to `quiz-history.md`). Update the `INDEX.md` line's last-quiz score.
