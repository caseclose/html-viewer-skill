#!/usr/bin/env python3
"""Serve a directory of generated HTML over a local HTTP server.

Start:  serve_viewer.py --dir DIR [--page index.html] [--port N]
                        [--local-only] [--require-key] [--lan-ip IP]
List:   serve_viewer.py --list
Stop:   serve_viewer.py --stop PORT | --stop all

URLs are plain http://host:port/page.html - no session key by default.
Pass --require-key to restore the original ?key=... gate.

By default the server binds 0.0.0.0, so the page is reachable both from this
machine and from other devices on the LAN. It prints a VIEWER_URL (loopback)
and one LAN_URL per LAN IPv4 address that answers 200 from this host. Virtual /
VPN-only addresses that cannot be reached are reported separately and never
handed to the user as working URLs. Pass --local-only to restore loopback-only
binding (no LAN_URL lines).

WARNING: the default mode is unauthenticated AND reachable from the LAN. Anyone
on the same network who can reach the port can read the served directory. Use it
only on a trusted LAN, serve a directory with no secrets, and stop the server
when done. For access from another network, forward the loopback port over SSH:
    ssh -L PORT:127.0.0.1:PORT user@host
"""
import sys

if sys.version_info < (3, 8):  # ThreadingHTTPServer, Path.unlink(missing_ok=)
    sys.exit(
        "needs Python 3.8+, got %d.%d - try python3.9 / python3.11 or a venv"
        % sys.version_info[:2]
    )

import argparse  # noqa: E402 - after the version guard, so the error stays readable
import http.client
import http.cookies
import ipaddress
import json
import os
import re
import secrets
import signal
import socket
import subprocess
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


def _remove_state(path):
    """Delete a state file, tolerating the cleanup/stop race (and strict shims)."""
    try:
        os.unlink(path)
    except OSError:
        pass


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
            _remove_state(path)
            continue
        if _alive(int(state.get("pid", -1))):
            out.append(state)
        else:
            _remove_state(path)  # died without cleaning up
    return out


def _usable_lan_ip(text):
    """True for a plain IPv4 address that is not loopback / link-local / unusable."""
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return False
    return not (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_unspecified
        or addr.is_multicast
        or addr.is_reserved
    )


def _default_route_ip():
    """Local IP the OS would use for outbound traffic; UDP connect sends nothing."""
    for target in (("223.5.5.5", 80), ("8.8.8.8", 80), ("10.255.255.255", 1)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(0.3)
                sock.connect(target)
                ip = sock.getsockname()[0]
                if _usable_lan_ip(ip):
                    return ip
        except OSError:
            continue
    return None


def _interface_ips():
    """All IPv4 addresses on local interfaces, via whichever OS tool exists."""
    found = []
    commands = (
        (["ifconfig", "-a"], r"^\s*inet(?:\s+addr)?[: ]\s*(\d+\.\d+\.\d+\.\d+)"),
        (["ip", "-4", "-o", "addr", "show"], r"inet\s+(\d+\.\d+\.\d+\.\d+)/"),
        (["ipconfig"], r"(?:IPv4 Address|IPv4 地址)[^:\r\n]*:?\s*(\d+\.\d+\.\d+\.\d+)"),
    )
    for cmd, pattern in commands:
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=3, check=False
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        found.extend(re.findall(pattern, out, re.M))
        if found:  # one tool is enough; avoid duplicate addresses from different tools
            break
    return found


def _lan_ips(extra=None):
    """LAN IPv4s, default-route address first, then the rest of the interfaces."""
    ordered = []
    primary = _default_route_ip()
    if primary:
        ordered.append(primary)
    for ip in list(_interface_ips()) + list(extra or []):
        if _usable_lan_ip(ip) and ip not in ordered:
            ordered.append(ip)
    return ordered


def _http_ok(host, port, path):
    """Probe a candidate LAN URL through the running server; only 200 counts."""
    try:
        conn = http.client.HTTPConnection(host, port, timeout=1.5)
        conn.request("HEAD", path)
        ok = conn.getresponse().status == 200
        conn.close()
        return ok
    except (OSError, http.client.HTTPException):
        return False


def _free_port(preferred, bind_host):
    candidates = [preferred] if preferred else list(PORT_RANGE)
    for port in candidates:
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((bind_host, port))
            except OSError:
                continue
        return port
    if preferred:
        sys.exit(f"port {preferred} is already in use")
    sys.exit(f"no free port in {PORT_RANGE.start}-{PORT_RANGE.stop - 1}")


class ViewerHandler(SimpleHTTPRequestHandler):
    """Static files, optionally gated behind a per-session key."""

    key = ""
    require_key = False
    protocol_version = "HTTP/1.1"

    def _authorized(self):
        if not self.require_key:
            return True
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


def serve(directory, page, port, local_only=False, lan_ip_extra=None, require_key=False):
    directory = directory.resolve()
    if not directory.is_dir():
        sys.exit(f"not a directory: {directory}")
    bind_host = "127.0.0.1" if local_only else "0.0.0.0"
    port = _free_port(port, bind_host)
    key = secrets.token_urlsafe(16) if require_key else ""
    handler = partial(
        type("Handler", (ViewerHandler,), {"key": key, "require_key": require_key}),
        directory=str(directory),
    )
    httpd = ThreadingHTTPServer((bind_host, port), handler)
    httpd.daemon_threads = True
    server_thread = threading.Thread(target=httpd.serve_forever, name="viewer-httpd", daemon=True)
    server_thread.start()

    path = f"/{page}" + (f"?key={key}" if key else "")
    lan_urls, unreachable = [], []
    if not local_only:
        for ip in _lan_ips(lan_ip_extra):
            if _http_ok(ip, port, path):
                lan_urls.append(f"http://{ip}:{port}{path}")
            else:
                unreachable.append(ip)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "pid": os.getpid(),
        "port": port,
        "dir": str(directory),
        "page": page,
        "bind": bind_host,
        "require_key": require_key,
        "url": f"http://127.0.0.1:{port}{path}",
        "lan_urls": lan_urls,
        "unreachable_lan_ips": unreachable,
    }
    _state_path(port).write_text(json.dumps(state, indent=1))
    _state_path(port).chmod(0o600)

    def cleanup(*_args):
        _remove_state(_state_path(port))
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    auth = "key" if require_key else "none"
    print(f"serving {directory} (bind {bind_host}, auth {auth})")
    print(f"VIEWER_URL {state['url']}", flush=True)
    for url in lan_urls:
        print(f"LAN_URL    {url}", flush=True)
    for ip in unreachable:
        print(
            f"LAN_URL_UNREACHABLE {ip} (detected but not reachable; omitted from handover)",
            flush=True,
        )
    if local_only:
        print("LAN_URL    disabled (--local-only): server is loopback only", flush=True)
    elif not lan_urls:
        print(
            "LAN_URL    none reachable - check the OS firewall, or add an address "
            "with --lan-ip IP",
            flush=True,
        )
    if require_key:
        print(
            "note: URLs carry the session key; HTTP is plaintext, do not share the "
            "keyed URL publicly.",
            flush=True,
        )
    else:
        print(
            "note: NO AUTHENTICATION - anyone who can reach this port can read the "
            "served directory. Trusted LAN only; stop with --stop when done.",
            flush=True,
        )
    print(f"stop with: {sys.argv[0]} --stop {port}", flush=True)
    try:
        server_thread.join()
    finally:
        _remove_state(_state_path(port))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, help="directory to serve")
    parser.add_argument("--page", default="index.html", help="entry page (default index.html)")
    parser.add_argument("--port", type=int, help="fixed port; default is the first free one")
    parser.add_argument("--local-only", action="store_true",
                        help="bind 127.0.0.1 only; no LAN URLs")
    parser.add_argument("--require-key", action="store_true",
                        help="gate every request behind a random ?key=... session key")
    parser.add_argument("--lan-ip", action="append", metavar="IP",
                        help="extra LAN IP to probe as a LAN_URL (repeatable)")
    parser.add_argument("--list", action="store_true", help="list running viewers")
    parser.add_argument("--stop", metavar="PORT|all", help="stop a running viewer")
    args = parser.parse_args()

    if args.list:
        running = _running()
        if not running:
            print("no viewer running")
        for state in running:
            auth = "key" if state.get("require_key") else "none"
            print(f"port {state['port']}  pid {state['pid']}  "
                  f"bind {state.get('bind', '127.0.0.1')}  auth {auth}  {state['dir']}")
            print(f"  {state['url']}")
            for url in state.get("lan_urls", []):
                print(f"  {url}")
        return 0

    if args.stop:
        running = _running()
        if args.stop != "all":
            running = [s for s in running if str(s["port"]) == args.stop]
            if not running:
                print(f"no viewer on port {args.stop}")
                return 1
        for state in running:
            pid, stopped_port = int(state["pid"]), int(state["port"])
            _remove_state(_state_path(stopped_port))  # remove before the child cleans up
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            print(f"stopped port {stopped_port}")
        return 0

    if not args.dir:
        parser.error("--dir is required (or use --list / --stop)")
    return serve(args.dir, args.page, args.port, args.local_only,
                 args.lan_ip, args.require_key)


if __name__ == "__main__":
    raise SystemExit(main())
