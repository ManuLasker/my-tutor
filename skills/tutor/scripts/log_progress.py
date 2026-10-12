#!/usr/bin/env python3
"""Append one graded-answer event to <topic>/progress.jsonl (stdlib only).

Used by the /tutor skill every time it grades a learner's answer in chat:

    python3 <skill>/scripts/log_progress.py --topic SLUG --task 1.1 \
        --result correct|wrong|dont_know --question "..." \
        [--qid ID] [--attempt 2] [--answer "..."] [--note "..."] \
        [--source chat|probe] [--run ID]

Resume helper (prints the last N events for a topic, oldest first):

    python3 <skill>/scripts/log_progress.py --topic SLUG --last 30 [--json]

Spaced review (what is due today, for one topic or all of them):

    python3 <skill>/scripts/log_progress.py --due [--topic SLUG] [--json]

Data lives in $TUTOR_HOME, else "home" in ~/.config/tutor/config.json, else
~/Documents/learning; never next to this script.

Event schema (one JSON object per line):
    {"ts","topic","source","task","qid"?,"question","result","attempt",
     "answer"?,"note"?,"run"?}
The topic must be listed in topics.json; file paths are never built from
anything else.
"""
import argparse
import datetime as _dt
import json
import os
import re
import sys

try:
    import fcntl
except ImportError:  # Windows: no flock; serve.py still serializes its own writes
    fcntl = None

# Settings: environment variable > ~/.config/tutor/config.json > default.
#   {"home": "~/Documents/learning", "bind": "0.0.0.0"}
CONFIG_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                           "tutor", "config.json")


def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


CONFIG = load_config()


def setting(env, key, default):
    v = os.environ.get(env) or CONFIG.get(key)
    return v if isinstance(v, str) and v.strip() else default


ROOT = os.path.realpath(os.path.expanduser(setting("TUTOR_HOME", "home", "~/Documents/learning")))
TOPICS_FILE = os.path.join(ROOT, "topics.json")
FILENAME = "progress.jsonl"

SOURCES = ("chat", "exam", "probe", "backfill", "flashcard")
CLI_SOURCES = ("chat", "probe")
RESULTS = ("correct", "wrong", "dont_know")
REQUIRED = ("ts", "topic", "source", "task", "question", "result", "attempt")
OPTIONAL = ("qid", "answer", "note", "run")
LIMITS = {"question": 200, "answer": 500, "note": 500,
          "qid": 80, "run": 80, "task": 20}
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
ID_RE = re.compile(r"^[A-Za-z0-9._:#-]+$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


# Spaced review: days until an item is due again, by its streak of correct
# answers at the end of its history (0 = last answer not correct = due now).
INTERVALS = (0, 1, 3, 7, 16, 35)


class ProgressError(ValueError):
    pass


def _lock(f, exclusive):
    if fcntl:
        fcntl.flock(f, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)


def _unlock(f):
    if fcntl:
        fcntl.flock(f, fcntl.LOCK_UN)


def load_topics():
    try:
        with open(TOPICS_FILE, encoding="utf-8") as f:
            topics = json.load(f)
    except (OSError, ValueError) as e:
        raise ProgressError(f"cannot read {TOPICS_FILE}: {e}")
    if not isinstance(topics, list):
        raise ProgressError("topics.json must be a JSON array of slugs")
    return [t for t in topics if isinstance(t, str)]


def strip_markdown(s):
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)   # [text](url) -> text
    s = re.sub(r"`{1,3}", "", s)                         # code ticks
    s = re.sub(r"(\*\*|__|\*|~~)", "", s)                # bold/italic/strike
    s = re.sub(r"(?m)^\s{0,3}(#{1,6}|>|[-+]|\d+\.)\s+", "", s)  # headings/quotes/lists
    return re.sub(r"\s+", " ", s).strip()


def clip(s, n):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def normalize(raw):
    """Clean user-supplied fields (strip markdown, collapse whitespace, truncate)."""
    ev = dict(raw)
    if isinstance(ev.get("question"), str):
        ev["question"] = clip(strip_markdown(ev["question"]), LIMITS["question"])
    for k in ("answer", "note"):
        if isinstance(ev.get(k), str):
            ev[k] = clip(ev[k], LIMITS[k])
            if not ev[k]:
                del ev[k]
    for k in ("qid", "run", "task"):
        if isinstance(ev.get(k), str):
            ev[k] = ev[k].strip()
    for k in ("qid", "run"):
        if k in ev and ev[k] in ("", None):
            del ev[k]
    return ev


def validate(ev, topics):
    """Raise ProgressError if ev does not follow the shared schema exactly."""
    if not isinstance(ev, dict):
        raise ProgressError("event must be a JSON object")
    missing = [k for k in REQUIRED if k not in ev]
    if missing:
        raise ProgressError(f"missing required field(s): {', '.join(missing)}")
    extra = [k for k in ev if k not in REQUIRED + OPTIONAL]
    if extra:
        raise ProgressError(f"unknown field(s): {', '.join(extra)}")
    for k in REQUIRED + OPTIONAL:
        if k in ev and k != "attempt" and not isinstance(ev[k], str):
            raise ProgressError(f"{k} must be a string")
    if not TS_RE.match(ev["ts"]):
        raise ProgressError("ts must look like 2026-09-30T23:40:00")
    try:
        _dt.datetime.strptime(ev["ts"], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        raise ProgressError("ts is not a valid date/time")
    if ev["topic"] not in topics or not SLUG_RE.match(ev["topic"]):
        raise ProgressError(f"unknown topic {ev['topic']!r} (not in topics.json)")
    if ev["source"] not in SOURCES:
        raise ProgressError(f"source must be one of {', '.join(SOURCES)}")
    if ev["result"] not in RESULTS:
        raise ProgressError(f"result must be one of {', '.join(RESULTS)}")
    a = ev["attempt"]
    if isinstance(a, bool) or not isinstance(a, int) or a < 1:
        raise ProgressError("attempt must be an integer >= 1")
    if not ev["question"].strip():
        raise ProgressError("question must not be empty")
    for k, n in LIMITS.items():
        if k in ev and len(ev[k]) > n:
            raise ProgressError(f"{k} longer than {n} chars")
    if "\n" in ev["task"] or (ev["task"] and not ID_RE.match(ev["task"])):
        raise ProgressError("task must be like '1.1' (letters, digits, . _ : # -) or empty")
    for k in ("qid", "run"):
        if k in ev and not ID_RE.match(ev[k]):
            raise ProgressError(f"{k} may only contain letters, digits and . _ : # -")
    return ev


def progress_path(topic, topics):
    if topic not in topics or not SLUG_RE.match(topic):
        raise ProgressError(f"unknown topic {topic!r} (not in topics.json)")
    d = os.path.join(ROOT, topic)
    if not os.path.isdir(d):
        raise ProgressError(f"topic folder missing: {d}")
    return os.path.join(d, FILENAME)


def append_events(topic, events, topics):
    """Validate every event, then append them all under one exclusive lock."""
    path = progress_path(topic, topics)
    lines = []
    for ev in events:
        validate(ev, topics)
        if ev["topic"] != topic:
            raise ProgressError("event topic does not match target file")
        lines.append(json.dumps(ev, ensure_ascii=False, separators=(",", ":")))
    with open(path, "a", encoding="utf-8") as f:
        _lock(f, True)
        try:
            # make sure we start on a fresh line even if a writer crashed mid-line
            if f.tell() > 0:
                with open(path, "rb") as r:
                    r.seek(-1, os.SEEK_END)
                    if r.read(1) != b"\n":
                        f.write("\n")
            f.write("".join(l + "\n" for l in lines))
            f.flush()
            os.fsync(f.fileno())
        finally:
            _unlock(f)
    return path


def read_events(topic, topics):
    path = progress_path(topic, topics)
    if not os.path.exists(path):
        return [], 0
    events, bad = [], 0
    with open(path, encoding="utf-8") as f:
        _lock(f, False)
        try:
            for line in f:
                if not line.strip():
                    continue
                try:
                    events.append(validate(json.loads(line), topics))
                except (ValueError, ProgressError):
                    bad += 1
        finally:
            _unlock(f)
    return events, bad


MARK = {"correct": "✅", "wrong": "❌", "dont_know": "\U0001F937"}


def print_last(topic, n, as_json, topics):
    events, bad = read_events(topic, topics)
    tail = events[-n:] if n > 0 else []
    if bad:
        print(f"warning: skipped {bad} invalid line(s)", file=sys.stderr)
    if not tail:
        print(f"no progress events for {topic}")
        return
    for ev in tail:
        if as_json:
            print(json.dumps(ev, ensure_ascii=False))
            continue
        bits = [ev["ts"], ev["source"], ev["task"] or "-", MARK[ev["result"]],
                ev["result"], f"a{ev['attempt']}"]
        if ev.get("qid"):
            bits.append(ev["qid"])
        line = " ".join(bits) + " | " + ev["question"]
        if ev.get("note"):
            line += f"  [note: {ev['note']}]"
        print(line)
    if not as_json:
        tally = {}
        for ev in tail:
            t = tally.setdefault(ev["task"] or "-", {r: 0 for r in RESULTS})
            t[ev["result"]] += 1
        parts = [f"{k}: {v['correct']}✓ {v['wrong']}✗ {v['dont_know']}?"
                 for k, v in sorted(tally.items())]
        print(f"tally (last {len(tail)}): " + " · ".join(parts))


def item_key(ev):
    """One review item = one qid, else one normalized question text."""
    return f"id:{ev['qid']}" if ev.get("qid") else "q:" + ev["question"].strip().lower()


def due_items(topic, topics, now, flashcards=False):
    """Items whose next spaced review is due, most overdue first.

    History per item is ordered by ts. streak = correct answers at the end of
    it; the next review is INTERVALS[streak] days after the last answer.
    """
    events, _ = read_events(topic, topics)
    if not flashcards:
        # self-rated card marks are drilled in the viewer, not re-asked in chat
        events = [e for e in events if e["source"] != "flashcard"]
    hist = {}
    for i, ev in sorted(enumerate(events), key=lambda p: (p[1]["ts"], p[0])):
        hist.setdefault(item_key(ev), []).append(ev)
    out = []
    for evs in hist.values():
        streak = 0
        for ev in reversed(evs):
            if ev["result"] != "correct":
                break
            streak += 1
        last = evs[-1]
        days = INTERVALS[min(streak, len(INTERVALS) - 1)]
        due = _dt.datetime.strptime(last["ts"], "%Y-%m-%dT%H:%M:%S") + _dt.timedelta(days=days)
        if due <= now:
            out.append({"topic": topic, "source": last["source"], "task": last["task"], "qid": last.get("qid", ""),
                        "question": last["question"], "last_result": last["result"],
                        "last_ts": last["ts"], "streak": streak,
                        "due": due.strftime("%Y-%m-%dT%H:%M:%S"),
                        "overdue_days": (now - due).days})
    # not-correct items first, then the longest overdue
    out.sort(key=lambda d: (d["streak"] > 0, -(now - _dt.datetime.strptime(d["due"], "%Y-%m-%dT%H:%M:%S")).total_seconds()))
    return out


def print_due(topic, as_json, topics, flashcards=False, limit=0):
    now = _dt.datetime.now().replace(microsecond=0)
    slugs = [topic] if topic else sorted(t for t in topics if SLUG_RE.match(t))
    rows = []
    for t in slugs:
        try:
            rows += due_items(t, topics, now, flashcards)
        except ProgressError:
            if topic:
                raise  # an explicit topic must exist; skip broken ones in the all-topics view
    total = len(rows)
    if limit > 0:
        rows = rows[:limit]
    if as_json:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
        return
    if not rows:
        print("nothing due" + (f" for {topic}" if topic else ""))
        return
    for r in rows:
        when = "now" if r["streak"] == 0 else f"{r['overdue_days']}d overdue"
        bits = [r["topic"], r["source"], r["task"] or "-", MARK[r["last_result"]], f"streak {r['streak']}", when]
        if r["qid"]:
            bits.append(r["qid"])
        print(" ".join(bits) + " | " + r["question"])
    per = {}
    for r in rows:
        per[r["topic"]] = per.get(r["topic"], 0) + 1
    print("due: " + " · ".join(f"{k} {v}" for k, v in per.items())
          + (f" (showing {len(rows)} of {total})" if total > len(rows) else ""))


def main(argv=None):
    p = argparse.ArgumentParser(description="Log a graded answer to <topic>/progress.jsonl")
    p.add_argument("--topic", help="slug listed in topics.json (optional with --due: all topics)")
    p.add_argument("--due", action="store_true",
                   help="print items due for spaced review (wrong/don't know first) and exit")
    p.add_argument("--last", type=int, metavar="N", help="print the last N events and exit")
    p.add_argument("--json", action="store_true", help="with --last / --due: print JSON lines")
    p.add_argument("--flashcards", action="store_true", help="with --due: include self-rated flashcard marks")
    p.add_argument("--limit", type=int, default=0, metavar="N", help="with --due: show at most N items")
    p.add_argument("--task", help="exam task id like 1.1 (may be empty string)")
    p.add_argument("--result", help="correct | wrong | dont_know")
    p.add_argument("--question", help="question text (markdown is stripped, max 200 chars)")
    p.add_argument("--qid", help="question id, e.g. an exam.json id")
    p.add_argument("--attempt", type=int, default=1, help="attempt number (>=1)")
    p.add_argument("--answer", help="learner's answer (max 500 chars)")
    p.add_argument("--note", help="learner's note (max 500 chars)")
    p.add_argument("--source", default="chat", help="chat | probe")
    p.add_argument("--run", help="id grouping one session / quiz")
    a = p.parse_args(argv)

    try:
        topics = load_topics()
        if a.due:
            print_due(a.topic, a.json, topics, a.flashcards, a.limit)
            return 0
        if not a.topic:
            raise ProgressError("--topic is required")
        if a.last is not None:
            if a.last < 1:
                raise ProgressError("--last must be >= 1")
            print_last(a.topic, a.last, a.json, topics)
            return 0
        missing = [f"--{k}" for k in ("task", "result", "question") if getattr(a, k) is None]
        if missing:
            raise ProgressError(f"missing {', '.join(missing)}")
        if a.source not in CLI_SOURCES:
            raise ProgressError(f"--source must be one of {', '.join(CLI_SOURCES)}")
        ev = {
            "ts": _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "topic": a.topic, "source": a.source, "task": a.task,
            "qid": a.qid, "question": a.question, "result": a.result,
            "attempt": a.attempt, "answer": a.answer, "note": a.note, "run": a.run,
        }
        ev = normalize({k: v for k, v in ev.items() if v is not None})
        append_events(a.topic, [ev], topics)
    except ProgressError as e:
        print(f"log_progress: error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"log_progress: I/O error: {e}", file=sys.stderr)
        return 1
    print(f"logged: {ev['topic']} {ev['task'] or '-'} {ev['result']} (attempt {ev['attempt']})"
          + (f" {ev['qid']}" if ev.get("qid") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
