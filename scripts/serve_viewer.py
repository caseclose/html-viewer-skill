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
and one LAN_URL per local IPv4 address that answers 200 from this host.
This self-probe does not verify access from another device (routing/firewalls).
Failed probes are reported separately. Pass --local-only to restore loopback-only
binding (no LAN_URL lines).

WARNING: the default mode is unauthenticated AND reachable from the LAN. Anyone
who can reach the port can read the served directory. Binding 0.0.0.0 includes
VPN/public IPv4 interfaces if present. Use it
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
import errno
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
import tempfile
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

STATE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "claude-html-viewer"
PORT_RANGE = range(8800, 8900)
COOKIE_NAME = "viewer_key"


def _state_path(port):
    return STATE_DIR / f"{port}.json"


def _remove_state(path):
    """Delete a state file, tolerating the cleanup/stop race (and strict shims)."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _alive(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
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
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("invalid state")
            pid, port = state.get("pid"), state.get("port")
            if (not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0
                    or not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535
                    or path.name != f"{port}.json"
                    or not all(isinstance(state.get(k), str) for k in ("dir", "url"))):
                raise ValueError("invalid state")
        except (OSError, ValueError):
            _remove_state(path)
            continue
        if _alive(state["pid"]):
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
    return isinstance(addr, ipaddress.IPv4Address) and not (
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
    """A local HEAD probe; this cannot verify access from a different device."""
    conn = http.client.HTTPConnection(host, port, timeout=1.5)
    try:
        conn.request("HEAD", path)
        response = conn.getresponse()
        return response.status == 200
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conn.close()


class ViewerServer(ThreadingHTTPServer):
    # On macOS, SO_REUSEADDR can let a wildcard listener overlap a loopback
    # listener. Probes then reach the other server, and state/stop target the
    # wrong viewer. Each port must have a single owner across bind addresses.
    allow_reuse_address = False
    allow_reuse_port = False


def _bind_server(preferred, bind_host, handler):
    # Bind the actual server, avoiding a check-then-bind race with other viewers.
    candidates = [preferred] if preferred is not None else PORT_RANGE
    for port in candidates:
        try:
            return ViewerServer((bind_host, port), handler)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
    if preferred is not None:
        sys.exit(f"port {preferred} is already in use")
    sys.exit(f"no free port in {PORT_RANGE.start}-{PORT_RANGE.stop - 1}")


def _page_path(directory, page):
    """Treat --page as a literal relative filename, not an already encoded URL."""
    entry = Path(page)
    if entry.is_absolute() or ".." in entry.parts:
        raise ValueError("--page must be a relative path inside --dir")
    target = directory / entry
    if not target.exists():
        raise ValueError(f"entry page not found: {target}")
    path = "/" + quote(entry.as_posix(), safe="/")
    if target.is_dir() and not path.endswith("/"):
        path += "/"
    return path


def _write_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # The temporary file is private from creation; replace publishes complete JSON.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=STATE_DIR,
                                     prefix=".viewer-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(state, stream, indent=1)
            stream.close()
            os.replace(temporary, _state_path(state["port"]))
        finally:
            _remove_state(temporary)


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
        if self.command != "HEAD":
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
        # Keyed URLs are credentials; keep them out of request logs.
        message = re.sub(r"\?[^\s\"]*", "?[redacted]", fmt % args)
        message = "".join(c if c >= " " and c != "\x7f" else "?" for c in message)
        sys.stderr.write("%s %s\n" % (self.address_string(), message))


def serve(directory, page, port, local_only=False, lan_ip_extra=None, require_key=False):
    directory = directory.expanduser().resolve()
    if not directory.is_dir():
        sys.exit(f"not a directory: {directory}")
    try:
        path = _page_path(directory, page)
    except ValueError as exc:
        sys.exit(str(exc))
    bind_host = "127.0.0.1" if local_only else "0.0.0.0"
    key = secrets.token_urlsafe(16) if require_key else ""
    if key:
        path += f"?key={key}"
    handler = partial(
        type("Handler", (ViewerHandler,), {"key": key, "require_key": require_key}),
        directory=str(directory),
    )
    httpd = _bind_server(port, bind_host, handler)
    port = httpd.server_port
    httpd.daemon_threads = True
    server_thread = threading.Thread(target=httpd.serve_forever, name="viewer-httpd", daemon=True)
    stopping = threading.Event()

    def cleanup(*_args):
        if not stopping.is_set():
            stopping.set()
            threading.Thread(target=httpd.shutdown, daemon=True).start()

    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    server_thread.start()
    for sig in previous_handlers:
        signal.signal(sig, cleanup)
    try:
        lan_urls, unreachable = [], []
        if not local_only:
            for ip in _lan_ips(lan_ip_extra):
                if stopping.is_set():
                    return 0
                if _http_ok(ip, port, path):
                    lan_urls.append(f"http://{ip}:{port}{path}")
                else:
                    unreachable.append(ip)
        if stopping.is_set():
            return 0
        state = {
            "version": 2,
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
        _write_state(state)
        auth = "key" if require_key else "none"
        print(f"serving {directory} (bind {bind_host}, auth {auth})")
        print(f"VIEWER_URL {state['url']}", flush=True)
        for url in lan_urls:
            print(f"LAN_URL {url}", flush=True)
        for ip in unreachable:
            print(f"LAN_URL_UNREACHABLE {ip} (local probe failed)", flush=True)
        if local_only:
            print("note: loopback only (--local-only).", flush=True)
        elif lan_urls:
            print("note: LAN URLs passed a probe on this host; access from another device "
                  "depends on routing and the inbound firewall.", flush=True)
        else:
            print("note: no LAN URL passed the local probe; check interfaces/firewall "
                  "or add a local IPv4 with --lan-ip IP.", flush=True)
        if require_key:
            print("note: URLs carry the session key; HTTP is plaintext.", flush=True)
        else:
            print("note: NO AUTHENTICATION - anyone who can reach this port can read "
                  "the served directory.", flush=True)
        if not local_only:
            print("note: 0.0.0.0 listens on ALL IPv4 interfaces, including VPN/public "
                  "interfaces if present. Trusted networks only.", flush=True)
        print(f"stop with: {sys.argv[0]} --stop {port}", flush=True)
        server_thread.join()
    finally:
        httpd.shutdown()
        server_thread.join()
        httpd.server_close()
        _remove_state(_state_path(port))
        for sig, previous in previous_handlers.items():
            signal.signal(sig, previous)
    return 0


def _port_number(text):
    try:
        port = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be an integer in 1-65535")
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be in 1-65535")
    return port


def _local_ipv4(text):
    if not _usable_lan_ip(text):
        raise argparse.ArgumentTypeError("--lan-ip needs a non-loopback unicast IPv4 address")
    # Never send a session key to an arbitrary remote host during a probe.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((text, 0))
    except OSError:
        raise argparse.ArgumentTypeError("--lan-ip must be assigned to this host")
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, help="directory to serve")
    parser.add_argument("--page", default="index.html", help="entry page (default index.html)")
    parser.add_argument("--port", type=_port_number, help="fixed port; default is the first free one")
    parser.add_argument("--local-only", action="store_true",
                        help="bind 127.0.0.1 only; no LAN URLs")
    parser.add_argument("--require-key", action="store_true",
                        help="gate every request behind a random ?key=... session key")
    parser.add_argument("--lan-ip", action="append", type=_local_ipv4, metavar="IP",
                        help="extra LAN IP to probe as a LAN_URL (repeatable)")
    parser.add_argument("--list", action="store_true", help="list running viewers")
    parser.add_argument("--stop", metavar="PORT|all", help="stop a running viewer")
    args = parser.parse_args()

    if args.list:
        running = _running()
        if not running:
            print("no viewer running")
        for state in running:
            auth = "key" if state.get("require_key", True) else "none"
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
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                _remove_state(_state_path(stopped_port))
            deadline = time.monotonic() + 3
            while _state_path(stopped_port).exists() and _alive(pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            if _state_path(stopped_port).exists() and _alive(pid):
                print(f"stop requested for port {stopped_port}; shutdown not confirmed", file=sys.stderr)
                return 1
            _remove_state(_state_path(stopped_port))
            print(f"stopped port {stopped_port}")
        return 0

    if args.local_only and args.lan_ip:
        parser.error("--lan-ip cannot be combined with --local-only")
    if not args.dir:
        parser.error("--dir is required (or use --list / --stop)")
    return serve(args.dir, args.page, args.port, args.local_only,
                 args.lan_ip, args.require_key)


if __name__ == "__main__":
    raise SystemExit(main())
