#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///
"""Study viewer server: static files + a small progress-logging endpoint.

Serves two folders as one site, like `python3 -m http.server`:
  - the viewer app (study.html/css/js, favicon.svg, vendor/) from this skill's
    assets/viewer/, so updating the skill updates the viewer;
  - everything else (topics.json, <topic>/...) from $TUTOR_HOME
    (default ~/Documents/learning), including <topic>/interactive/ demos.
Hidden paths (any segment starting with ".", e.g. .git/) are never served.
It also accepts `POST /api/progress` so the Exam and Flashcards modes can
append answers to `<topic>/progress.jsonl`.

Usage:
    uv run serve.py [--port 8080] [--bind 127.0.0.1]
If the port is busy and --port wasn't given, the next free one (up to +10) is used.
To always serve to the LAN, set "bind": "0.0.0.0" in ~/.config/tutor/config.json
(or TUTOR_BIND=0.0.0.0).

Request body:  {"events": [ {...}, ... ]}   (1-200 events, all same topic)
Event schema: exactly the one defined in log_progress.py (normalize() +
validate() are imported from there, so CLI and viewer can never drift apart).
Unknown keys and null values are dropped; a missing or non-conforming `ts` is
converted to local "YYYY-MM-DDTHH:MM:SS" (or set to now if unparseable).
Responses: 201 {"ok":true,"saved":n}; 400/404/413 {"ok":false,"error":...}.
"""

import argparse
import functools
import ipaddress
import json
import os
import posixpath
import socket
import sys
import threading
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.realpath(os.path.join(HERE, "..", "assets", "viewer"))
APP_FILES = {"study.html", "study.css", "study.js", "favicon.svg"}

# Single source of truth for the progress schema and the data folder.
sys.dont_write_bytecode = True
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import log_progress as lp  # noqa: E402

ROOT = lp.ROOT

MAX_BODY = 256 * 1024
MAX_EVENTS = 200
KNOWN_FIELDS = lp.REQUIRED + lp.OPTIONAL
FIELD_ORDER = ["ts", "topic", "source", "task", "qid", "question", "result",
               "attempt", "answer", "note", "run"]

_write_lock = threading.Lock()


class BadRequest(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def load_topics():
    """Read topics.json fresh on every request (the tutor may add topics)."""
    try:
        return set(lp.load_topics())
    except lp.ProgressError:
        return set()


def safe_topic_dir(topic):
    """Return the absolute topic directory, refusing anything that escapes ROOT."""
    if not topic or "/" in topic or "\\" in topic or topic in (".", "..") or "\0" in topic:
        raise BadRequest(400, "invalid topic")
    path = os.path.realpath(os.path.join(ROOT, topic))
    if os.path.dirname(path) != os.path.realpath(ROOT) or not os.path.isdir(path):
        raise BadRequest(404, f"topic folder not found: {topic}")
    return path


def local_ts(value):
    """Return `value` as local "YYYY-MM-DDTHH:MM:SS" (log_progress's format).

    Already-conforming values pass through; other ISO-8601 date-times
    (fractions, offsets, "Z") are converted to local time; anything else,
    including a bare date, becomes the current local time.
    """
    fmt = "%Y-%m-%dT%H:%M:%S"
    if isinstance(value, str) and lp.TS_RE.match(value):
        try:
            datetime.strptime(value, fmt)
            return value
        except ValueError:
            pass
    if isinstance(value, str) and len(value) <= 40 and ("T" in value or " " in value.strip()):
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt.strftime(fmt)
        except ValueError:
            pass
    return datetime.now().strftime(fmt)


def not_future(ts):
    """Clamp a client timestamp to now: a future ts would hide an item from --due."""
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return min(ts, now)


def host_allowed(host_header):
    """Allow IP literals, localhost and this machine's own name (DNS-rebinding guard)."""
    host = (host_header or "").strip().lower()
    if host.startswith("["):                       # [ipv6]:port
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    name = socket.gethostname().lower()
    return host in ("localhost", name, name.split(".")[0], name.split(".")[0] + ".local")


def clean_event(raw, i, topics):
    """Normalize + validate one event with log_progress's rules; return it in schema order."""
    if not isinstance(raw, dict):
        raise BadRequest(400, f"event {i}: not an object")
    ev = {k: v for k, v in raw.items() if k in KNOWN_FIELDS and v is not None}
    ev["ts"] = not_future(local_ts(ev.get("ts")))
    ev = lp.normalize(ev)
    try:
        lp.validate(ev, topics)
    except lp.ProgressError as e:
        raise BadRequest(400, f"event {i}: {e}")
    return {k: ev[k] for k in FIELD_ORDER if k in ev}


def append_events(topic, events, topics):
    """Append via log_progress (flock + fresh-line guard), serialized per process too."""
    with _write_lock:
        try:
            lp.append_events(topic, events, topics)
        except lp.ProgressError as e:
            raise BadRequest(400, str(e))
        except OSError as e:
            raise BadRequest(500, f"could not write progress: {e}")


class Handler(SimpleHTTPRequestHandler):
    # Don't trust the OS MIME table: on Windows it comes from the registry and can
    # map .js/.css to text/plain, which browsers then refuse to apply.
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html", ".css": "text/css", ".js": "text/javascript",
        ".mjs": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml",
        ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8",
        ".jsonl": "application/x-ndjson",
    }

    def route(self):
        """Return (base_dir, parts) for the request path, or None if refused.

        Refused: hidden segments (.git, .claude), "..", and anything a Windows
        path could reinterpret (backslash, drive colon, NUL); the result must
        also stay inside its base folder.
        """
        path = posixpath.normpath(unquote(urlsplit(self.path).path))
        parts = [p for p in path.split("/") if p]
        if any(p.startswith(".") or "\\" in p or ":" in p or "\0" in p for p in parts):
            return None
        base = APP_DIR if ((len(parts) == 1 and parts[0] in APP_FILES) or parts[:1] == ["vendor"]) else ROOT
        full = os.path.realpath(os.path.join(base, *parts))
        if full != base and not full.startswith(base + os.sep):
            return None
        return base, parts

    def translate_path(self, path):
        r = self.route()
        if r is None:
            return os.path.join(ROOT, ".refused")  # never served -> 404
        base, parts = r
        return os.path.join(base, *parts)

    def guard(self):
        """403 unless the Host is ours; for writes also require a same-origin Origin."""
        host = self.headers.get("Host", "")
        if not host_allowed(host):
            self.send_json(403, {"ok": False, "error": "host not allowed"})
            return False
        origin = self.headers.get("Origin")
        if self.command == "POST" and origin is not None and urlsplit(origin).netloc.lower() != host.lower():
            self.send_json(403, {"ok": False, "error": "cross-origin write refused"})
            return False
        return True

    def do_GET(self):
        if not self.guard():
            return
        if urlsplit(self.path).path == "/api/ping":
            self.send_json(200, {"tutor": True, "home": ROOT, "bind": self.server.server_address[0]})
            return
        if urlsplit(self.path).path in ("", "/"):
            self.send_response(302)
            self.send_header("Location", "/study.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.route() is None:
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        if not self.guard():
            return
        if self.route() is None:
            self.send_error(404)
            return
        super().do_HEAD()

    def list_directory(self, path):
        # Listings only for exercise inputs (Exercises mode reads them); nowhere
        # else, since the data folder may be a git repo.
        r = self.route()
        if r and r[0] == ROOT and len(r[1]) >= 2 and r[1][1] == "exercises":
            return super().list_directory(path)
        self.send_error(404)
        return None

    def send_json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.guard():
            self.close_connection = True
            return
        if urlsplit(self.path).path != "/api/progress":
            self.close_connection = True
            self.send_json(404, {"ok": False, "error": "not found"})
            return
        try:
            saved = self.handle_progress()
        except BadRequest as e:
            self.close_connection = True
            self.send_json(e.status, {"ok": False, "error": e.message})
            return
        self.send_json(201, {"ok": True, "saved": saved})

    def handle_progress(self):
        length = self.headers.get("Content-Length")
        if length is None or not length.strip().isdigit():
            raise BadRequest(400, "Content-Length required")
        length = int(length)
        if length > MAX_BODY:
            raise BadRequest(413, f"body too large (max {MAX_BODY} bytes)")
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise BadRequest(400, "body is not valid JSON")

        events = body.get("events") if isinstance(body, dict) else None
        if not isinstance(events, list) or not (1 <= len(events) <= MAX_EVENTS):
            raise BadRequest(400, f"'events' must be a list of 1-{MAX_EVENTS} events")

        if not all(isinstance(e, dict) for e in events):
            raise BadRequest(400, "every event must be a JSON object")
        if not all(isinstance(e.get("topic"), str) for e in events):
            raise BadRequest(400, "'topic' must be a string")
        names = {e["topic"] for e in events}
        if len(names) != 1:
            raise BadRequest(400, "all events in one request must share the same topic")
        topic = names.pop()
        topics = load_topics()
        if topic not in topics:
            raise BadRequest(404, f"unknown topic: {topic}")
        safe_topic_dir(topic)

        cleaned = [clean_event(e, i, topics) for i, e in enumerate(events)]
        append_events(topic, cleaned, topics)
        return len(cleaned)


def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packets are sent for UDP connect
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def already_running(bind):
    """If a tutor server for this ROOT already listens on 8080-8090, print its URL."""
    for port in range(8080, 8091):
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=0.3) as r:
                info = json.loads(r.read().decode("utf-8"))
        except (URLError, OSError, ValueError):
            continue
        if isinstance(info, dict) and info.get("tutor") and info.get("home") == ROOT:
            print(f"Already running: http://127.0.0.1:{port}/study.html (bound to {info.get('bind')})")
            if info.get("bind") != bind:
                print(f"  It is bound to {info.get('bind')}, not {bind}: stop it (Ctrl+C in its terminal, "
                      f"or kill the process on port {port}) and start again to rebind.")
            elif bind in ("0.0.0.0", ""):
                for ip in lan_ips():
                    print(f"  http://{ip}:{port}/study.html   (LAN)")
            return True
    return False


def main():
    p = argparse.ArgumentParser(
        description="Serve the study viewer (static files) plus POST /api/progress, "
                    "which appends exam answers to <topic>/progress.jsonl.",
        epilog="WARNING: --bind 0.0.0.0 exposes this whole folder AND the progress "
               "write endpoint to everyone on your LAN. The default (127.0.0.1) is local-only.",
    )
    p.add_argument("--port", type=int, help="port to listen on (default: first free from 8080)")
    p.add_argument("--bind", default=lp.setting("TUTOR_BIND", "bind", "127.0.0.1"),
                   help="address to bind (default: $TUTOR_BIND, else \"bind\" in ~/.config/tutor/config.json, "
                        "else 127.0.0.1; 0.0.0.0 = whole LAN, see warning)")
    args = p.parse_args()

    if not os.path.isdir(APP_DIR):
        print(f"Viewer assets missing: {APP_DIR}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(lp.TOPICS_FILE):
        print(f"No topics.json in {ROOT}; run scripts/topics.py init first", file=sys.stderr)
        sys.exit(1)
    if not args.port and already_running(args.bind):
        return
    handler = functools.partial(Handler, directory=ROOT)
    ports = [args.port] if args.port else range(8080, 8091)
    for port in ports:
        try:
            httpd = ThreadingHTTPServer((args.bind, port), handler)
            args.port = port
            break
        except OSError as e:
            err = e
    else:
        print(f"Cannot listen on {args.bind}:{ports[-1] if args.port is None else args.port}: {err}",
              file=sys.stderr)
        sys.exit(1)

    host = "127.0.0.1" if args.bind in ("0.0.0.0", "") else args.bind
    print(f"Serving {ROOT} (viewer from {APP_DIR})")
    print(f"  http://{host}:{args.port}/study.html")
    if args.bind in ("0.0.0.0", ""):
        for ip in lan_ips():
            print(f"  http://{ip}:{args.port}/study.html   (LAN)")
        print("  WARNING: your notes and the progress endpoint are reachable from your LAN.")
    print("Ctrl+C to stop.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    lp.utf8_stdio()
    main()
