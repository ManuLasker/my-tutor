#!/usr/bin/env python3
"""Check a topic's study files against references/formats.md (stdlib only).

    python3 <skill>/scripts/validate.py SLUG [SLUG ...]   # or --all

Checks meta.json, flashcards.json, cheatsheet.json, exercises.json (+ that
every test input exists), exam.json (per-type answer rules) and plan.md (map
standard). Missing optional files are skipped. Prints ERROR / WARN lines;
exit 1 if any ERROR, else 0. It does not run exercise solutions; do that
yourself as formats.md describes.
"""
import argparse
import json
import os
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log_progress as lp  # noqa: E402

CLASSDEFS = ("done", "doing", "todo", "known", "gap", "goal")


class Report:
    def __init__(self, slug):
        self.slug, self.errors, self.warns = slug, 0, 0

    def err(self, where, msg):
        self.errors += 1
        print(f"ERROR {self.slug}/{where}: {msg}")

    def warn(self, where, msg):
        self.warns += 1
        print(f"WARN  {self.slug}/{where}: {msg}")


def load(path, rep, name):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except ValueError as e:
        rep.err(name, f"invalid JSON: {e}")
        return None


def is_str(v, empty_ok=False):
    return isinstance(v, str) and (empty_ok or v.strip() != "")


def check_meta(d, rep):
    path = os.path.join(d, "meta.json")
    m = load(path, rep, "meta.json")
    if m is None:
        if os.path.exists(path):
            return  # invalid JSON, already reported
        rep.warn("meta.json", "missing (picker falls back to the slug under 'Other')")
        return
    if not isinstance(m, dict):
        return rep.err("meta.json", "must be an object")
    for k in ("title", "group"):
        if not is_str(m.get(k)):
            rep.err("meta.json", f"'{k}' must be a non-empty string")
    if "order" in m and (isinstance(m["order"], bool) or not isinstance(m["order"], (int, float))):
        rep.err("meta.json", "'order' must be a number")


def check_cards(d, rep):
    cards = load(os.path.join(d, "flashcards.json"), rep, "flashcards.json")
    if cards is None:
        return
    if not isinstance(cards, list):
        return rep.err("flashcards.json", "must be an array")
    seen = set()
    for i, c in enumerate(cards):
        if not isinstance(c, dict) or not is_str(c.get("q")) or not is_str(c.get("a")):
            rep.err("flashcards.json", f"card {i}: needs non-empty 'q' and 'a'")
            continue
        extra = set(c) - {"q", "a", "task"}
        if extra:
            rep.warn("flashcards.json", f"card {i}: unknown field(s) {sorted(extra)}")
        if "task" in c and not (c["task"] == "" or (is_str(c["task"]) and lp.ID_RE.match(c["task"]))):
            rep.err("flashcards.json", f"card {i}: bad task {c['task']!r}")
        key = c["q"].strip().lower()
        if key in seen:
            rep.warn("flashcards.json", f"card {i}: duplicate question (shares a progress id)")
        seen.add(key)


def check_cheatsheet(d, rep):
    cs = load(os.path.join(d, "cheatsheet.json"), rep, "cheatsheet.json")
    if cs is None:
        return
    if not isinstance(cs, list) or not cs:
        return rep.err("cheatsheet.json", "must be a non-empty array")
    for i, s in enumerate(cs):
        if not isinstance(s, dict) or not is_str(s.get("title")) or not is_str(s.get("content")):
            rep.err("cheatsheet.json", f"section {i}: needs non-empty 'title' and 'content'")
    last = cs[-1].get("title", "") if isinstance(cs[-1], dict) else ""
    if os.path.exists(os.path.join(d, "vocab-words.json")):
        return  # generated vocab deck: no doc links to add
    if not re.search(r"reference|further reading", str(last), re.I):
        rep.warn("cheatsheet.json", "last section should be 'References & further reading'")


def check_exercises(d, rep):
    ex = load(os.path.join(d, "exercises.json"), rep, "exercises.json")
    if ex is None:
        return
    if not isinstance(ex, list):
        return rep.err("exercises.json", "must be an array")
    ids = set()
    root = os.path.realpath(d)
    for i, e in enumerate(ex):
        w = f"exercises.json[{i}]"
        if not isinstance(e, dict):
            rep.err(w, "must be an object")
            continue
        for k in ("id", "title", "prompt", "solution", "explanation"):
            if not is_str(e.get(k)):
                rep.err(w, f"'{k}' must be a non-empty string")
        if not is_str(e.get("setup"), empty_ok=True):
            rep.err(w, "'setup' must be a string")
        if e.get("id") in ids:
            rep.err(w, f"duplicate id {e.get('id')!r}")
        ids.add(e.get("id"))
        if e.get("difficulty") not in ("easy", "medium", "hard"):
            rep.err(w, "difficulty must be easy | medium | hard")
        hints = e.get("hints")
        if not isinstance(hints, list) or not all(is_str(h) for h in hints):
            rep.err(w, "'hints' must be an array of strings")
        tests = e.get("tests")
        if not isinstance(tests, list) or not tests:
            rep.err(w, "'tests' must be a non-empty array")
            continue
        for j, t in enumerate(tests):
            if not isinstance(t, dict) or not is_str(t.get("input")) or not isinstance(t.get("expected"), str):
                rep.err(w, f"test {j}: needs 'input' (path) and 'expected' (string)")
                continue
            p = os.path.realpath(os.path.join(d, t["input"]))
            if not p.startswith(root + os.sep):
                rep.err(w, f"test {j}: input escapes the topic folder")
            elif not os.path.exists(p):
                rep.err(w, f"test {j}: input not found: {t['input']}")
            if "unordered" in t and not isinstance(t["unordered"], bool):
                rep.err(w, f"test {j}: 'unordered' must be true/false")


def check_exam(d, rep):
    qs = load(os.path.join(d, "exam.json"), rep, "exam.json")
    if qs is None:
        return
    if not isinstance(qs, list):
        return rep.err("exam.json", "must be an array")
    ids = set()
    for i, q in enumerate(qs):
        if not isinstance(q, dict):
            rep.err(f"exam.json[{i}]", "must be an object")
            continue
        w = f"exam.json[{q.get('id', i)}]"
        qid = q.get("id")
        if not is_str(qid) or not lp.ID_RE.match(qid) or len(qid) > lp.LIMITS["qid"]:
            rep.err(w, "id must use letters, digits and . _ : # - (≤80 chars); it becomes the progress qid")
        if qid in ids:
            rep.err(w, "duplicate id")
        ids.add(qid)
        if not is_str(q.get("task"), empty_ok=True) or (q.get("task") and not lp.ID_RE.match(q["task"])):
            rep.err(w, "task must be a string like '1.2'")
        for k in ("question", "explanation"):
            if not is_str(q.get(k)):
                rep.err(w, f"'{k}' must be a non-empty string")
        opts, ans, typ = q.get("options"), q.get("answer"), q.get("type")
        if not isinstance(opts, list) or len(opts) < 2 or not all(is_str(o) for o in opts):
            rep.err(w, "'options' must be an array of ≥2 strings")
            continue
        if not isinstance(ans, list) or not ans or not all(
                isinstance(a, int) and not isinstance(a, bool) and 0 <= a < len(opts) for a in ans):
            rep.err(w, "'answer' must be a non-empty array of option indices in range")
            continue
        if typ == "single":
            if len(ans) != 1:
                rep.err(w, "single: answer must have exactly one index")
            if len(opts) != 4:
                rep.warn(w, f"single: expected 4 options, has {len(opts)}")
        elif typ == "multi":
            if len(ans) < 2 or ans != sorted(set(ans)):
                rep.err(w, "multi: answer must be ≥2 sorted, unique indices")
            if len(opts) != 5:
                rep.warn(w, f"multi: expected 5 options, has {len(opts)}")
        elif typ == "order":
            if sorted(ans) != list(range(len(opts))):
                rep.err(w, "order: answer must be a permutation of all option indices")
            elif ans == list(range(len(opts))):
                rep.err(w, "order: options are already in order (shuffle them)")
        elif typ == "match":
            prompts = q.get("prompts")
            if not isinstance(prompts, list) or not all(is_str(p) for p in prompts):
                rep.err(w, "match: 'prompts' must be an array of strings")
            elif len(ans) != len(prompts):
                rep.err(w, "match: answer needs one option index per prompt")
            elif not 3 <= len(prompts) <= 5:
                rep.warn(w, f"match: expected 3–5 prompts, has {len(prompts)}")
        else:
            rep.err(w, "type must be single | multi | order | match")
        if typ != "match" and q.get("prompts"):
            rep.err(w, "'prompts' is only for match questions")


def check_plan(d, rep):
    p = os.path.join(d, "plan.md")
    if not os.path.exists(p):
        return
    text = open(p, encoding="utf-8").read()
    m = re.search(r"```mermaid\s*\n(.*?)```", text, re.S)
    if not m:
        return rep.err("plan.md", "no ```mermaid dependency map")
    graph = m.group(1)
    if not re.match(r"\s*flowchart\s+LR\b", graph):
        rep.err("plan.md", "map must be 'flowchart LR'")
    for c in CLASSDEFS:
        if not re.search(rf"^\s*classDef {c} ", graph, re.M):
            rep.err("plan.md", f"missing 'classDef {c}' (use the standard block verbatim)")
    body = "\n".join(l for l in graph.splitlines() if not re.match(r"\s*(classDef|class)\s", l))
    nodes = set(re.findall(r"(?<![\w-])(c\d+|k\d+|goal)(?![\w-])", re.sub(r'"[^"]*"', '""', body)))
    classed = set()
    for line in re.findall(r"^\s*class\s+([\w,]+)\s+\w+", graph, re.M):
        classed |= set(line.split(","))
    for n in sorted(nodes - classed):
        rep.warn("plan.md", f"node {n} has no class line")
    rows = set(re.findall(r"^\|\s*(c\d+)\s*\|", text, re.M))
    for n in sorted(x for x in nodes if x.startswith("c")):
        if n not in rows:
            rep.warn("plan.md", f"chunk {n} has no row in a '#' chunk table")


def check_topic(slug, topics):
    rep = Report(slug)
    if not lp.SLUG_RE.match(slug):
        rep.err("", "not a valid slug")
        return rep
    d = os.path.join(lp.ROOT, slug)
    if not os.path.isdir(d):
        rep.err("", f"folder not found in {lp.ROOT}")
        return rep
    if slug not in topics:
        rep.err("", "not in topics.json (run scripts/topics.py add)")
    for fn in (check_meta, check_cards, check_cheatsheet, check_exercises, check_exam, check_plan):
        fn(d, rep)
    return rep


def main(argv=None):
    p = argparse.ArgumentParser(description="Validate topic study files")
    p.add_argument("slugs", nargs="*")
    p.add_argument("--all", action="store_true", help="every topic in topics.json")
    a = p.parse_args(argv)
    try:
        topics = lp.load_topics()
    except lp.ProgressError as e:
        print(f"validate: error: {e}", file=sys.stderr)
        return 2
    slugs = topics if a.all else a.slugs
    if not slugs:
        p.error("give one or more slugs, or --all")
    errors = warns = 0
    for s in slugs:
        r = check_topic(s, topics)
        errors, warns = errors + r.errors, warns + r.warns
    print(f"{len(slugs)} topic(s): {errors} error(s), {warns} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
