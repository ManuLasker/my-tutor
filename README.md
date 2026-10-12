# my-tutor

An [Agent Skill](https://agentskills.io) that turns your coding agent into a patient, Socratic tutor. It doesn't stop at explaining a topic. It sets up everything you need to remember it:

- **Probe and plan.** A few calibration questions, then a dependency map of what you'll learn. You approve it before teaching starts.
- **Socratic lessons.** One chunk at a time, with diagrams and real code. The tutor asks before it tells.
- **Study files per topic:** flashcards, a cheat sheet with verified doc links, hands-on exercises you run in your own terminal, and an exam question bank.
- **Progress tracking.** Every graded answer is logged (chat, exams, flashcards), and a **spaced review** (`/tutor review`) brings back what you're about to forget.
- **A local study viewer** (plan, lesson, flashcards, cheat sheet, exercises, exam and progress modes). It runs offline from a small Python server.
- **Vocabulary decks** built from a word list you collect while reading a book.

Works with **Claude Code**, **GitHub Copilot** (VS Code, CLI, coding agent), **OpenAI Codex**, **Cursor**, **Gemini CLI** and other tools that read `SKILL.md` skills, on **Linux, macOS and Windows**.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/). The scripts are standard-library Python, run with `uv run`. uv picks a Python 3.8+ on its own and downloads one if none is installed, so you don't need to install Python yourself.
  - Linux / macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- A browser, for the study viewer

## Install

Pick one.

**Claude Code plugin**

```
/plugin marketplace add ManuLasker/my-tutor
/plugin install tutor@my-tutor
```

Invoke it as `/tutor:tutor <topic>`, or just say "teach me <topic>".

**Any tool, with [`npx skills`](https://github.com/vercel-labs/skills)**

```bash
npx skills add ManuLasker/my-tutor --skill tutor -g
```

**Git clone + install script** (`git pull` keeps it up to date)

```bash
git clone https://github.com/ManuLasker/my-tutor.git
cd my-tutor && ./install.sh
```

This needs bash (on Windows, Git Bash or WSL). It links `skills/tutor` into `~/.claude/skills/` (Claude Code) and `~/.agents/skills/` (Copilot, Codex, Cursor, Gemini CLI). Options:

- `--copy`: copy instead of linking.
- `--project DIR`: install for one repository only.
- `--only claude|agents`: just one of the two locations.
- `--force`: replace an existing install. The old one is moved to `~/.tutor-install-backups/`, not deleted.

**Manual:** copy `skills/tutor/` to your tool's skills folder (for example `~/.claude/skills/tutor`, `~/.agents/skills/tutor`, `~/.copilot/skills/tutor`). Keep the folder name `tutor`.

## Use

```
/tutor bash parameter expansion      # Claude Code (or: "teach me bash parameter expansion")
/tutor review                        # quiz what's due for spaced review
/tutor vocab for my book, volume 2   # build a vocab deck from a word list
```

Open the study viewer:

```bash
uv run ~/.claude/skills/tutor/scripts/serve.py    # or wherever the skill is installed
```

Then open the printed URL. The tutor starts it for you after a lesson.

## Where your data lives

Everything you learn is saved as plain Markdown and JSON in **`~/Documents/learning`**, separate from the skill:

```
~/Documents/learning/
├── INDEX.md   topics.json   learner.md     # learner.md = your level and preferences
└── <topic>/   plan.md  session.md  flashcards.json  cheatsheet.json
               exercises.json  exam.json  progress.jsonl  quiz-history.md
```

Settings (optional) go in `~/.config/tutor/config.json`:

```json
{ "home": "~/Documents/learning", "bind": "127.0.0.1" }
```

- `home`: where your learning data lives. The `TUTOR_HOME` environment variable overrides it.
- `bind`: the viewer's address. `"0.0.0.0"` makes it reachable from other devices on your network, which also means **anyone on that network can read your notes and write progress**. Only use it on a network you trust. The server refuses requests from other websites and from unknown host names either way.

**Version your learning:** make your data folder its own git repository (private, if you'd rather not share it):

```bash
cd ~/Documents/learning && git init && git add -A && git commit -m "my learning"
```

To study someone else's material, clone their learning repo and point `home` (or `TUTOR_HOME`) at it.

## Repository layout

```
skills/tutor/
├── SKILL.md                 # the instructions the agent follows
├── references/              # file formats, vocab mode, visualizations, viewer contract
├── scripts/                 # topics.py, log_progress.py, validate.py, serve.py, build_vocab_deck.py
├── assets/viewer/           # the study viewer (Alpine.js, marked, highlight.js, mermaid; all bundled)
└── hooks/                   # Claude Code Stop hook: blocks a turn that graded an answer without logging it
.claude-plugin/              # Claude Code plugin marketplace manifest
install.sh
```

## Notes

- **The `hooks` field** in `SKILL.md` is a Claude Code extension. Other tools ignore it, but the strict `skills-ref validate` reports it as an unexpected field. The hook is only a safety net: the skill's logging rule works without it.
- **Keep the installed folder named `tutor`:** the hook finds its script by that name.
- **Windows:** use the plugin or `npx skills` install. `install.sh` works in Git Bash, but Git Bash copies instead of symlinking unless symlinks are enabled, so `git pull` won't update that install. The Claude Code Stop hook runs through Git Bash, which Claude Code on Windows already requires.
- **Scripts are standard-library Python, run with `uv run`.** They resolve the data folder themselves, so the agent never edits `topics.json` or `progress.jsonl` by hand.
