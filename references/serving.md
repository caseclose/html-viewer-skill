# Serving and troubleshooting

## Access modes

`serve_viewer.py` serves static files with Python's HTTP server. It has no TLS,
user accounts, upload endpoint, or public hosting integration.

Default: `--dir DIR --page index.html` listens on all IPv4 interfaces, without
a key. Use `--local-only` for loopback access. Add `--require-key` independently
to either mode for a random query key and host-scoped session cookie.

The server follows symlinks and serves hidden files if their paths are requested.
Use a dedicated view directory, inspect its contents and symlink targets, and
avoid serving a whole repository or home directory to expose one report.
Stage/copy only the intended assets when they live elsewhere. A common parent
can work if all its contents are intended to be readable.

## Paths and assets

Pass literal relative filenames to `--page`, quoted for the shell:

```bash
python3 "$SKILL_DIR/scripts/serve_viewer.py" --dir "./views" --page "报告 #1.html"
```

The script encodes the URL; do not pass `%20` for a space. Missing entries,
absolute paths, and `..` entry paths fail before listening. Directory entries
are supported and get a trailing slash.

`viewer_kit.rel()` encodes paths for links and images. Assets must be reachable
under the served directory. If `quick_view --out` moves the page to another
directory, relative links may escape the served root: stage the assets there or
serve an appropriate common parent after checking what it exposes. `--limit`
limits rendered content, not the files readable through the HTTP server.

## Verify keyed assets

A successful entry request sets `viewer_key`. Preserve it when fetching assets:

```bash
curl --fail --silent --show-error -c "$COOKIE_JAR" "$VIEWER_URL" -o /dev/null
curl --fail --silent --show-error -b "$COOKIE_JAR" "$ASSET_URL" -o /dev/null
```

Use a task-local temporary cookie jar; remove it after verification. Cookies are
not port scoped, so two keyed viewers on the same hostname may replace each
other's cookie. Reopen each viewer's keyed entry if an asset returns 403.

## LAN detection

The script probes the default route without sending UDP application data, then
reads interface IPv4 addresses using `ifconfig`, `ip`, or `ipconfig`.
`--lan-ip IP` supplements detection; the IP must belong to this host.
Loopback, link-local, multicast, reserved, unspecified, and IPv6 addresses are
not LAN candidates. IPv6 serving is not supported.

Only HTTP 200 self-probes produce `LAN_URL` lines. A failed self-probe produces
`LAN_URL_UNREACHABLE`; no candidate is still a valid local viewer. A successful
self-probe does not test firewall rules for inbound traffic from another device,
wireless client isolation, VPN reachability, or another device's route. Check
those on the actual client before calling a LAN URL cross-device verified.

## Remote host over SSH

Start with `--local-only`; add `--require-key` when a session key is wanted.
On the browser's machine, forward a local port:

```bash
ssh -N -L <LOCAL_PORT>:127.0.0.1:<SERVER_PORT> user@host
```

Replace only host and port in `VIEWER_URL` with `127.0.0.1:<LOCAL_PORT>`.
Preserve the encoded path and the `?key=...` query if present. The loopback URL
printed on a remote host refers to that remote host until forwarding is set up.
An SSH tunnel does not restrict an existing `0.0.0.0` listener; start the viewer
with `--local-only` if loopback-only access is intended.

## Lifecycle

`--list` reports bind address, authentication and stored URLs, including services
started by the older always-keyed version. Addresses are startup snapshots;
restart a task's viewer after changing networks to refresh them. Do not stop
unrelated services simply to reclaim a preferred port.

`--stop PORT` requests SIGTERM and waits briefly for state cleanup; an unconfirmed
shutdown returns nonzero and retains its state. State is stored under
`${XDG_CACHE_HOME:-~/.cache}/claude-html-viewer/`; keyed URLs are credentials, so
the server writes state atomically with private file permissions. Request logs
redact query keys, but startup output and `--list` intentionally include them.
This is a local development helper, not a hardened multi-user process manager.
