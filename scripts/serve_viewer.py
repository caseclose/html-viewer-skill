#!/usr/bin/env python3
"""Serve a directory of generated HTML over a key-gated loopback HTTP server.

Start:  serve_viewer.py --dir DIR [--page index.html] [--port N]
List:   serve_viewer.py --list
Stop:   serve_viewer.py --stop PORT | --stop all

Binds 127.0.0.1 only. Every request must carry the session key, as `?key=...`
or the cookie the first keyed request sets, so another user on the host cannot
read the directory by guessing the port.

To reach it from another machine, forward the port over SSH:
    ssh -L PORT:127.0.0.1:PORT user@host
Exposing the port on a shared network is the user's call, not this script's.
"""
import sys

if sys.version_info < (3, 8):  # ThreadingHTTPServer, Path.unlink(missing_ok=)
    sys.exit(
        "needs Python 3.8+, got %d.%d - try python3.9 / python3.11 or a venv"
        % sys.version_info[:2]
    )

import argparse  # noqa: E402 - after the version guard, so the error stays readable
import http.cookies
import json
import os
import secrets
import signal
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

STATE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "claude-html-viewer"
PORT_RANGE = range(8800, 8900)
COOKIE_NAME = "viewer_key"


def _state_path(port):
    return STATE_DIR / f"{port}.json"


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _running():
    out = []
    if not STATE_DIR.is_dir():
        return out
    for path in sorted(STATE_DIR.glob("*.json")):
        try:
            state = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            continue
        if _alive(int(state.get("pid", -1))):
            out.append(state)
        else:
            path.unlink(missing_ok=True)  # died without cleaning up
    return out


def _free_port(preferred):
    candidates = [preferred] if preferred else list(PORT_RANGE)
    for port in candidates:
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    if preferred:
        sys.exit(f"port {preferred} is already in use")
    sys.exit(f"no free port in {PORT_RANGE.start}-{PORT_RANGE.stop - 1}")


class KeyedHandler(SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler, but every path needs the session key."""

    key = ""
    protocol_version = "HTTP/1.1"

    def _authorized(self):
        query = parse_qs(urlsplit(self.path).query)
        if secrets.compare_digest(query.get("key", [""])[0], self.key):
            self._set_cookie = True
            return True
        raw = self.headers.get("Cookie", "")
        try:
            cookie = http.cookies.SimpleCookie(raw)
        except http.cookies.CookieError:
            return False
        morsel = cookie.get(COOKIE_NAME)
        return bool(morsel) and secrets.compare_digest(morsel.value, self.key)

    def send_response(self, code, message=None):  # noqa: D102 - hook in the cookie
        super().send_response(code, message)
        if getattr(self, "_set_cookie", False):
            self.send_header(
                "Set-Cookie", f"{COOKIE_NAME}={self.key}; Path=/; HttpOnly; SameSite=Strict"
            )
            self._set_cookie = False

    def _deny(self):
        body = b"403 - append ?key=<session key> to the URL\n"
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._authorized():
            return self._deny()
        super().do_GET()

    def do_HEAD(self):
        if not self._authorized():
            return self._deny()
        super().do_HEAD()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def serve(directory, page, port):
    directory = directory.resolve()
    if not directory.is_dir():
        sys.exit(f"not a directory: {directory}")
    port = _free_port(port)
    key = secrets.token_urlsafe(16)
    handler = partial(type("Handler", (KeyedHandler,), {"key": key}), directory=str(directory))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "pid": os.getpid(),
        "port": port,
        "dir": str(directory),
        "page": page,
        "url": f"http://127.0.0.1:{port}/{page}?key={key}",
    }
    _state_path(port).write_text(json.dumps(state, indent=1))
    _state_path(port).chmod(0o600)

    def cleanup(*_args):
        _state_path(port).unlink(missing_ok=True)
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    print(f"serving {directory}")
    print(f"VIEWER_URL {state['url']}", flush=True)
    print(f"stop with: {sys.argv[0]} --stop {port}", flush=True)
    try:
        httpd.serve_forever()
    finally:
        _state_path(port).unlink(missing_ok=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, help="directory to serve")
    parser.add_argument("--page", default="index.html", help="entry page (default index.html)")
    parser.add_argument("--port", type=int, help="fixed port; default is the first free one")
    parser.add_argument("--list", action="store_true", help="list running viewers")
    parser.add_argument("--stop", metavar="PORT|all", help="stop a running viewer")
    args = parser.parse_args()

    if args.list:
        running = _running()
        if not running:
            print("no viewer running")
        for state in running:
            print(f"port {state['port']}  pid {state['pid']}  {state['dir']}\n  {state['url']}")
        return 0

    if args.stop:
        running = _running()
        if args.stop != "all":
            running = [s for s in running if str(s["port"]) == args.stop]
            if not running:
                print(f"no viewer on port {args.stop}")
                return 1
        for state in running:
            os.kill(int(state["pid"]), signal.SIGTERM)
            _state_path(int(state["port"])).unlink(missing_ok=True)
            print(f"stopped port {state['port']}")
        return 0

    if not args.dir:
        parser.error("--dir is required (or use --list / --stop)")
    return serve(args.dir, args.page, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
