#!/usr/bin/env python3
"""Set up the learning folder and register topics (stdlib only).

    python3 <skill>/scripts/topics.py init
        Create $TUTOR_HOME (default ~/Documents/learning) with topics.json,
        INDEX.md and learner.md if missing. Never overwrites anything.

    python3 <skill>/scripts/topics.py add SLUG [--title T] [--group G] [--order N]
        Create <SLUG>/, add SLUG to topics.json (deduped, sorted), and write
        <SLUG>/meta.json. Run it as soon as a topic folder is needed: progress
        logging rejects topics that are not registered.

    python3 <skill>/scripts/topics.py list [--json]
        Registered topics with title, group and whether a session exists.

Prints one line per action; exits non-zero (nothing half-written) on error.
"""
import argparse
import json
import os
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log_progress as lp  # noqa: E402  (ROOT, SLUG_RE, load_topics)

ROOT = lp.ROOT
TOPICS = os.path.join(ROOT, "topics.json")

INDEX_TEMPLATE = """# Learning Index

Topics taught by the `/tutor` skill. Each entry links to the saved session.

## Topics

"""

LEARNER_TEMPLATE = """# Learner profile

The tutor reads this at the start of every session. Edit it freely.

## Level

- (e.g. working developer — skip beginner framing; or: new to programming)

## Background

- (what you already know well, tools you use daily, certifications)

## Preferences

- Socratic: ask me one guiding question and wait before explaining.
- (anything else: language, pace, examples you like)

## Paths

- Vocabulary word lists: (folder with your book word lists, if you use vocab decks)
"""


def write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        os.chmod(tmp, 0o644)  # mkstemp makes 0600; keep normal file permissions
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def create_if_missing(path, text):
    if os.path.exists(path):
        return False
    write_atomic(path, text)
    print(f"created {path}")
    return True


def cmd_init(_a):
    os.makedirs(ROOT, exist_ok=True)
    create_if_missing(TOPICS, "[]\n")
    create_if_missing(os.path.join(ROOT, "INDEX.md"), INDEX_TEMPLATE)
    if create_if_missing(os.path.join(ROOT, "learner.md"), LEARNER_TEMPLATE):
        print("learner.md is a blank template: fill it in with the learner")
    print(f"TUTOR_HOME = {ROOT}")


def cmd_add(a):
    slug = a.slug
    if not lp.SLUG_RE.match(slug) or len(slug) > 80:
        raise lp.ProgressError(f"bad slug {slug!r}: lowercase letters, digits and dashes only")
    if not os.path.exists(TOPICS):
        cmd_init(a)
    topics = lp.load_topics()
    d = os.path.join(ROOT, slug)
    os.makedirs(d, exist_ok=True)
    if slug not in topics:
        write_atomic(TOPICS, json.dumps(sorted(set(topics) | {slug})) + "\n")
        print(f"registered {slug} in topics.json")
    meta_path = os.path.join(d, "meta.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    given = {k: v for k, v in (("title", a.title), ("group", a.group), ("order", a.order)) if v is not None}
    if given or not meta:
        meta = {"title": slug.replace("-", " "), "group": "Other", "order": 999, **meta, **given}
        write_atomic(meta_path, json.dumps(meta, ensure_ascii=False) + "\n")
        print(f"wrote {meta_path}")
    print(f"topic dir: {d}")


def cmd_list(a):
    rows = []
    for slug in lp.load_topics():
        meta = {}
        try:
            with open(os.path.join(ROOT, slug, "meta.json"), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            pass
        rows.append({"slug": slug, "title": meta.get("title", slug), "group": meta.get("group", "Other"),
                     "session": os.path.exists(os.path.join(ROOT, slug, "session.md")),
                     "plan": os.path.exists(os.path.join(ROOT, slug, "plan.md"))})
    for r in rows:
        print(json.dumps(r, ensure_ascii=False) if a.json else
              f"{r['slug']}  [{r['group']}] {r['title']}" + ("" if r["session"] else "  (no session.md)"))


def main(argv=None):
    p = argparse.ArgumentParser(description="Set up $TUTOR_HOME and register topics")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the learning folder skeleton")
    ad = sub.add_parser("add", help="create + register a topic")
    ad.add_argument("slug")
    ad.add_argument("--title")
    ad.add_argument("--group")
    ad.add_argument("--order", type=int)
    ls = sub.add_parser("list", help="list registered topics")
    ls.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        {"init": cmd_init, "add": cmd_add, "list": cmd_list}[a.cmd](a)
    except (lp.ProgressError, OSError, ValueError) as e:
        print(f"topics: error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
