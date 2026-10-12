#!/usr/bin/env python3
"""Stop hook: don't let the tutor finish a turn that graded an answer without logging it.

Contract (https://code.claude.com/docs/en/hooks.md, "Stop"):
  stdin  = JSON with transcript_path, stop_hook_active, last_assistant_message, ...
  stdout = {"decision": "block", "reason": "..."} to keep Claude going; nothing to allow.

"Graded"  = assistant text since the last real user message has a line starting with
            `Grade:` (the /tutor skill mandates this marker).
"Logged"  = a Bash tool call in that same span that runs log_progress.py with --result
            (reads like --due or --last do not count).
Block only when graded and not logged. Never block when stop_hook_active is true, and
never fail the session: every error path exits 0 without output.
"""
import json
import os
import re
import sys
import time

GRADE_RE = re.compile(r"^[ \t]*(?:>[ \t]*)?(?:\*\*|__)?Grade(?:\*\*|__)?[ \t]*:", re.M)
LOG_MARK = "log_progress.py"
# This hook lives in <skill>/hooks/; the logger in <skill>/scripts/.
LOG_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", LOG_MARK)


def is_real_user(entry):
    """A message the human typed (not a tool result, meta/injected text, or a notification)."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return False
    origin = entry.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        types = {b.get("type") for b in content if isinstance(b, dict)}
        return "tool_result" not in types and "text" in types
    return False


def scan_transcript(path):
    """Return (assistant_texts, logged) for the span after the last real user message.

    Returns None if the transcript can't be read.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, TypeError, ValueError):
        return None
    entries = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            entries.append(e)
    if not entries:
        return None  # nothing parseable: can't verify, so don't block
    start = 0
    for i, e in enumerate(entries):
        if is_real_user(e):
            start = i + 1
    texts, logged = [], False
    for e in entries[start:]:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        content = (e.get("message") or {}).get("content")
        if isinstance(content, str):
            texts.append(content)
            continue
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and isinstance(b.get("text"), str):
                texts.append(b["text"])
            elif b.get("type") == "tool_use" and b.get("name") == "Bash":
                cmd = (b.get("input") or {}).get("command")
                if isinstance(cmd, str) and LOG_MARK in cmd and "--result" in cmd:
                    logged = True
    return texts, logged


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return
    if not isinstance(data, dict) or data.get("stop_hook_active") is True:
        return
    last = data.get("last_assistant_message")
    path = data.get("transcript_path")
    if not isinstance(path, str) or not path:
        return  # can't verify logging -> stay out of the way

    scan = scan_transcript(path)
    if scan is None:
        return
    texts, logged = scan
    if isinstance(last, str):
        texts.append(last)
    if not any(GRADE_RE.search(t) for t in texts):
        return
    if not logged:
        time.sleep(0.4)  # the transcript is written asynchronously; give it one more look
        scan = scan_transcript(path)
        if scan is None or scan[1]:
            return
    else:
        return

    reason = (
        "You graded a learner's answer this turn (a line starting with 'Grade:') but did not "
        "run log_progress.py. Before finishing, log every answer you graded this turn, one "
        "call each: python3 " + LOG_SCRIPT + " --topic <slug> --task <task> "
        "--result correct|wrong|dont_know --question \"<question>\" --source chat|probe "
        "[--qid <id> (exam.json id if quizzing from it)] [--attempt N (2+ on a retry)] "
        "[--run <id> (same id for every answer in one quiz/session)] "
        "[--answer \"...\"] [--note \"...\"]. Then end the turn briefly "
        "(don't repeat the lesson). If nothing was actually graded, reply with one short "
        "line saying so."
    )
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # never crash the session
        pass
    sys.exit(0)
