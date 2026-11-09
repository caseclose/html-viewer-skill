"""Observable regressions; stdlib only, synthetic content and private state."""
import http.client
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from html.parser import HTMLParser
from unittest import mock
from urllib.parse import parse_qs, urlsplit, unquote

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import quick_view as qv
import serve_viewer as sv
import viewer_kit as vk


class Elements(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.elements = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def attrs(self, tag):
        return [attrs for name, attrs in self.elements if name == tag]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data with spaces"
        self.data.mkdir()
        self.cache = self.root / "cache"
        self.env = dict(os.environ, XDG_CACHE_HOME=str(self.cache))

    def file(self, name="index.html", content="fixture"):
        path = self.data / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def cli(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                              env=self.env, capture_output=True, text=True, timeout=10)


class ServerTests(Fixture):
    def start(self, page="index.html", flags=(), probe_ips=None):
        log = self.root / f"server-{time.time_ns()}.log"
        output = log.open("w")
        # Real HTTP server and self-probe; replace interface discovery only.
        # Synthetic fixture is the only content accessible during all-interface tests.
        code = "import sys; sys.path.insert(0, %r); import serve_viewer as v; " % str(SCRIPTS)
        if probe_ips is not None:
            code += "v._lan_ips=lambda extra=None:%r; " % probe_ips
        code += "raise SystemExit(v.main())"
        args = [sys.executable, "-u", "-c", code, "--dir", str(self.data), "--page", page]
        process = subprocess.Popen(args + list(flags), env=self.env, stdout=output, stderr=output)
        self.addCleanup(output.close)
        self.addCleanup(self.stop_process, process)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            text = log.read_text()
            if "stop with:" in text:
                state_files = list((self.cache / "claude-html-viewer").glob("*.json"))
                state = next(json.loads(p.read_text()) for p in state_files
                             if json.loads(p.read_text())["pid"] == process.pid)
                return process, state, log
            if process.poll() is not None:
                self.fail(text)
            time.sleep(.03)
        self.fail("server startup timed out: " + log.read_text())

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def fetch(self, url, method="GET", cookie=None):
        parts = urlsplit(url)
        connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=2)
        self.addCleanup(connection.close)
        connection.request(method, parts.path + ("?" + parts.query if parts.query else ""),
                           headers={"Cookie": cookie} if cookie else {})
        response = connection.getresponse()
        return response.status, response.getheader("Set-Cookie"), response.read()

    def test_literal_paths_probe_and_serve_in_both_auth_modes(self):
        for keyed in (False, True):
            for filename in ("中文.html", "my report.html", "nested/报告 #?%25.html"):
                with self.subTest(keyed=keyed, filename=filename):
                    self.file(filename)
                    process, state, _ = self.start(filename,
                        flags=["--require-key"] if keyed else [], probe_ips=["127.0.0.1"])
                    self.assertEqual(self.fetch(state["url"])[0], 200)
                    self.assertEqual(self.fetch(state["lan_urls"][0], method="HEAD")[0], 200)
                    self.assertEqual(unquote(urlsplit(state["url"]).path), "/" + filename)
                    self.stop_process(process)

    def test_four_modes_auth_cookie_and_stop(self):
        self.file()
        self.file("image #1.svg", "<svg/>")
        for local in (False, True):
            for keyed in (False, True):
                with self.subTest(local=local, keyed=keyed):
                    flags = (["--local-only"] if local else []) + (["--require-key"] if keyed else [])
                    process, state, log = self.start(flags=flags, probe_ips=["127.0.0.1"])
                    self.assertEqual(state["bind"], "127.0.0.1" if local else "0.0.0.0")
                    self.assertEqual(bool(state["lan_urls"]), not local)
                    plain = state["url"].split("?")[0]
                    self.assertEqual(self.fetch(plain)[0], 403 if keyed else 200)
                    status, cookie, _ = self.fetch(state["url"])
                    self.assertEqual(status, 200)
                    asset = plain.rsplit("/", 1)[0] + "/image%20%231.svg"
                    self.assertEqual(self.fetch(asset, cookie=cookie)[0], 200)
                    state_path = self.cache / "claude-html-viewer" / f"{state['port']}.json"
                    if os.name != "nt":
                        self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
                    result = self.cli("serve_viewer.py", "--stop", state["port"])
                    self.assertEqual(result.returncode, 0, result.stderr)
                    process.wait(timeout=5)
                    self.assertFalse(state_path.exists())
                    if keyed:
                        key = parse_qs(urlsplit(state["url"]).query)["key"][0]
                        request_logs = [line for line in log.read_text().splitlines() if 'HTTP/1.1"' in line]
                        self.assertTrue(request_logs)
                        self.assertTrue(all(key not in line for line in request_logs))

    def test_directory_entry_probe(self):
        self.file("sub/index.html")
        process, state, _ = self.start("sub", probe_ips=["127.0.0.1"])
        self.assertTrue(state["url"].endswith("/sub/"))
        self.assertEqual(self.fetch(state["lan_urls"][0])[0], 200)

    def test_absent_or_outside_entry_fails_before_listening(self):
        for page in ("absent.html", "../outside.html", str(self.root / "absolute.html")):
            result = self.cli("serve_viewer.py", "--dir", self.data, "--page", page)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(self.cache.exists())

    def test_invalid_network_arguments(self):
        self.file()
        for flag, value in (("--port", "0"), ("--port", "65536"),
                            ("--lan-ip", "2001:4860:4860::8888"), ("--lan-ip", "8.8.8.8")):
            result = self.cli("serve_viewer.py", "--dir", self.data, flag, value)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)

    def test_old_state_still_listed_as_keyed(self):
        state_dir = self.cache / "claude-html-viewer"
        state_dir.mkdir(parents=True)
        state = {"pid": os.getpid(), "port": 8800, "dir": str(self.data),
                 "url": "http://127.0.0.1:8800/index.html?key=fixture"}
        (state_dir / "8800.json").write_text(json.dumps(state))
        result = self.cli("serve_viewer.py", "--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("auth key", result.stdout)

    def test_bad_state_never_signals_process_groups(self):
        state_dir = self.cache / "claude-html-viewer"
        state_dir.mkdir(parents=True)
        for port, state in enumerate(([], {}, {"pid": -1}, {"pid": 0}, {"pid": "broken"}), 8800):
            (state_dir / f"{port}.json").write_text(json.dumps(state))
        with mock.patch.object(sv, "STATE_DIR", state_dir), mock.patch.object(sv.os, "kill") as kill:
            self.assertEqual(sv._running(), [])
            kill.assert_not_called()
        self.assertEqual(list(state_dir.glob("*.json")), [])

    def test_head_denial_does_not_corrupt_keep_alive_connection(self):
        self.file()
        _, state, _ = self.start(flags=["--local-only", "--require-key"])
        parts = urlsplit(state["url"])
        conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=2)
        try:
            conn.request("HEAD", "/index.html")
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            self.assertEqual(response.read(), b"")
            conn.request("GET", parts.path + "?" + parts.query)
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"fixture")
        finally:
            conn.close()

    def test_bound_server_skips_occupied_port(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            busy = occupied.getsockname()[1]
            with mock.patch.object(sv, "PORT_RANGE", [busy, 0]), \
                    mock.patch.object(sv.socket, "getfqdn", side_effect=AssertionError("unexpected getfqdn")):
                server = sv._bind_server(None, "127.0.0.1", sv.ViewerHandler)
                try:
                    self.assertNotEqual(server.server_port, busy)
                finally:
                    server.server_close()

    def test_wildcard_does_not_overlap_reusable_loopback_listener(self):
        with socket.socket() as occupied:
            occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            busy = occupied.getsockname()[1]
            with mock.patch.object(sv, "PORT_RANGE", [busy, 0]):
                server = sv._bind_server(None, "0.0.0.0", sv.ViewerHandler)
                try:
                    self.assertNotEqual(server.server_port, busy)
                finally:
                    server.server_close()

    def test_probe_failure_does_not_break_local_viewer(self):
        self.file()
        _, state, _ = self.start(probe_ips=["127.0.0.2"])
        # 0.0.0.0 can serve this loopback alias on some systems; force failure separately.
        with mock.patch.object(sv.http.client, "HTTPConnection") as factory:
            factory.return_value.request.side_effect = OSError("unreachable")
            self.assertFalse(sv._http_ok("127.0.0.1", state["port"], "/index.html"))
            factory.return_value.close.assert_called_once()
        self.assertEqual(self.fetch(state["url"])[0], 200)


class RenderTests(Fixture):
    def test_asset_urls_preserve_literal_delimiters(self):
        image = self.file("图片 #?%.svg", "<svg/>")
        html = vk.gallery([(image, '<img onerror="bad">')], self.data)
        attrs = Elements(html).attrs("img")[0]
        self.assertEqual(unquote(attrs["src"]), image.name)
        self.assertNotIn("#", attrs["src"])
        self.assertNotIn("?", attrs["src"])
        self.assertEqual(attrs["alt"], '<img onerror="bad">')
        self.assertEqual(len(Elements(html).attrs("img")), 1)

    def test_repeated_tab_labels_have_independent_targets(self):
        panels = [("Details", "one"), ("Raw", "two")]
        html = vk.tabs(panels) + vk.tabs(panels)
        parser = Elements(html)
        ids = [attrs["id"] for attrs in parser.attrs("div") if "id" in attrs]
        targets = [attrs["data-tab"] for attrs in parser.attrs("button")]
        self.assertEqual(len(set(ids)), 4)
        self.assertEqual(set(ids), set(targets))

    def test_directory_limit_applies_within_one_large_folder(self):
        for index in range(12):
            self.file(f"{index}.txt")
        html = qv.dir_page(self.data, self.data, "files", 3, self.data / "view.html")
        self.assertEqual(len(Elements(html).attrs("a")), 3)

    def test_limit_above_2000_not_silently_capped_by_table(self):
        source = self.file("records.json", json.dumps([{"id": i} for i in range(2010)]))
        result = self.cli("quick_view.py", source, "--limit", "2005")
        self.assertEqual(result.returncode, 0, result.stderr)
        parser = Elements(source.with_suffix(".view.html").read_text())
        self.assertEqual(sum("data-row" in attrs for attrs in parser.attrs("tr")), 2005)

    def test_csv_preserves_zero_prefixed_ids(self):
        source = self.file("records.csv", "id,score\n00123,0.5\n")
        html = qv.csv_page(source, self.data, "records", 10)
        self.assertIn("00123", html)
        self.assertIn('data-v="0.5"', html)

    def test_csv_rejects_lossy_or_malformed_columns(self):
        for content in ("a,a\n1,2\n", "a,\n1,2\n", "a,b\n1,2,3\n"):
            source = self.file("bad.csv", content)
            with self.assertRaisesRegex(ValueError, "CSV/TSV"):
                qv.csv_page(source, self.data, "bad", 10)

    def test_log_tail_has_original_line_numbers(self):
        source = self.file("run.log", "\n".join(f"INFO line {i}" for i in range(10)))
        html = qv.log_page(source, self.data, "log", 2)
        self.assertIn("INFO line 9", html)
        self.assertIn("INFO line 8", html)
        self.assertNotIn("INFO line 7", html)
        self.assertEqual(sum("data-row" in a for a in Elements(html).attrs("tr")), 2)

    def test_quick_view_prints_runnable_quoted_command(self):
        source = self.file("中文 #1.json", '[{"id":1}]')
        result = self.cli("quick_view.py", source)
        self.assertEqual(result.returncode, 0, result.stderr)
        command = next(line[len("serve with: "):] for line in result.stdout.splitlines()
                       if line.startswith("serve with: "))
        parts = shlex.split(command)
        self.assertEqual(parts[parts.index("--dir") + 1], str(self.data.resolve()))
        self.assertEqual(parts[parts.index("--page") + 1], "中文 #1.view.html")

    def test_invalid_limits_and_source_overwrite_fail(self):
        source = self.file("source.json", "[]")
        for flags in (("--limit", "0"), ("--limit", "-1"), ("--out", str(source))):
            result = self.cli("quick_view.py", source, *flags)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(source.read_text(), "[]")

    def test_representative_input_formats(self):
        for filename, content in (("flat.json", '[{"id":1,"status":"pass"}]'),
                                  ("nested.jsonl", '{"title":"案例","steps":[1,2]}\n'),
                                  ("table.tsv", "name\tscore\na\t0.5\n"),
                                  ("run.log", "INFO start\nERROR fixture\n"),
                                  ("readme.md", "# text\n<script>fixture</script>"),
                                  ("image.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')):
            with self.subTest(filename=filename):
                source = self.file(filename, content)
                result = self.cli("quick_view.py", source)
                self.assertEqual(result.returncode, 0, result.stderr)
                html = source.with_suffix(".view.html").read_text()
                self.assertIn("<!doctype html>", html)
                self.assertNotIn("<script>fixture</script>", html)


if __name__ == "__main__":
    unittest.main()
