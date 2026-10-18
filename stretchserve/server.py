"""A small directory-and-markdown HTTP server with stretchtext rendering.

- `.md` files render as pages (stretchtext live, mermaid/graphviz for
  fenced ```mermaid and ```dot blocks).
- A directory with an index.md or README.md renders that as its page;
  otherwise you get a file listing.
- Everything else is served raw.
"""

from __future__ import annotations

import argparse
import html
import mimetypes
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

from .render import Renderer

ASSETS_DIR = Path(__file__).parent / "static"

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — stretchserve</title>
<link rel="stylesheet" href="/__assets/stretch.css">
<script type="module">
try {{
  const {{ default: mermaid }} = await import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs');
  mermaid.initialize({{ startOnLoad: false, theme: 'neutral' }});
  window.mermaid = mermaid;
}} catch (e) {{ console.warn('mermaid unavailable', e); }}
try {{
  const {{ Viz }} = await import('https://cdn.jsdelivr.net/npm/@viz-js/viz@3/+esm');
  window.viz = await Viz();
}} catch (e) {{ console.warn('graphviz unavailable', e); }}
window.dispatchEvent(new Event('graphs-ready'));
</script>
<style>{pygments_css}</style>
</head>
<body>
<main>
{warnings}
{body}
</main>
<script src="/__assets/stretch.js" defer></script>
</body>
</html>
"""


def _warnings_html(issues: list[dict]) -> str:
    if not issues:
        return ""
    items = "".join(
        f"<li><code>line {i['line']}</code> — {html.escape(i['message'])}"
        + (f' <code>{html.escape(i["key"])}</code>' if i.get("key") else "")
        + "</li>"
        for i in issues
    )
    return f'<div class="stx-warnings"><strong>markup issues</strong><ul>{items}</ul></div>'


def make_handler(root: Path, renderer: Renderer, pygments_css: str = ""):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quieter default
            pass

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            if path.startswith("/__assets/"):
                self._asset(path[len("/__assets/"):])
                return
            try:
                target = (root / path.lstrip("/")).resolve()
                if not (target == root or target.is_relative_to(root)):
                    self.send_error(403)
                    return
            except OSError:
                self.send_error(400)
                return

            if target.is_dir():
                index = next(
                    (target / name for name in ("index.md", "README.md") if (target / name).is_file()),
                    None,
                )
                if index is not None:
                    self._page(index)
                else:
                    self._listing(target, path)
            elif target.is_file() and target.suffix == ".md":
                self._page(target)
            elif target.is_file():
                self._raw(target)
            else:
                self.send_error(404)

        def _asset(self, name: str):
            file = (ASSETS_DIR / name).resolve()
            if not file.is_relative_to(ASSETS_DIR) or not file.is_file():
                self.send_error(404)
                return
            self._send_bytes(file.read_bytes(), mimetypes.guess_type(name)[0] or "text/plain")

        def _raw(self, file: Path):
            mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            self._send_bytes(file.read_bytes(), mime)

        def _page(self, file: Path):
            text = file.read_text(encoding="utf-8", errors="replace")
            result = renderer.render(text)
            title = file.stem
            rel = None
            try:
                rel = file.parent.relative_to(root)
            except ValueError:
                rel = "."
            up = "" if rel == Path(".") else '<nav><a href="../">← up</a></nav>'
            page = _PAGE.format(
                title=html.escape(title),
                warnings=_warnings_html(result.issues),
                body=up + result.html,
                pygments_css=pygments_css,
            )
            self._send_bytes(page.encode(), "text/html; charset=utf-8")

        def _listing(self, dir: Path, path: str):
            entries = sorted(dir.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            rows = []
            for entry in entries:
                name = entry.name + ("/" if entry.is_dir() else "")
                href = f"{path.rstrip('/')}/{entry.name}" + ("/" if entry.is_dir() else "")
                rows.append(f'<li><a href="{html.escape(href, quote=True)}">{html.escape(name)}</a></li>')
            body = f"<h1>{html.escape(path or '/')}</h1><ul>{''.join(rows)}</ul>"
            page = _PAGE.format(
                title=html.escape(path or "/"),
                warnings="",
                body=body,
                pygments_css=pygments_css,
            )
            self._send_bytes(page.encode(), "text/html; charset=utf-8")

        def _send_bytes(self, payload: bytes, mime: str):
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def _interface_ip(ifname: str) -> str | None:
    """IPv4 address of a network interface, or None if it has none."""
    import fcntl
    import socket
    import struct

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        addr = fcntl.ioctl(
            sock.fileno(),
            0x8915,  # SIOCGIFADDR
            struct.pack("256s", ifname[:15].encode()),
        )[20:24]
        return socket.inet_ntoa(addr)
    except OSError:
        return None
    finally:
        sock.close()


def pick_host() -> str:
    """LAN address: ethernet if plugged in, else wifi, else localhost."""
    import os

    try:
        names = os.listdir("/sys/class/net")
    except OSError:
        return "127.0.0.1"
    ethernet = [n for n in names if n.startswith(("en", "eth"))]
    wifi = [n for n in names if n.startswith(("wl", "wlan"))]
    for ifname in ethernet + wifi:
        ip = _interface_ip(ifname)
        if ip:
            return ip
    return "127.0.0.1"


def serve(directory: Path, host: str, port: int) -> None:
    root = directory.resolve()
    renderer = Renderer()
    handler = make_handler(root, renderer, "")
    httpd = HTTPServer((host, port), handler)
    shown = host if host != "0.0.0.0" else "localhost"
    print(f"stretchserve serving {root} at http://{shown}:{port}/  (Ctrl-C to stop)")
    if host not in ("127.0.0.1", "localhost"):
        print(f"  reachable on the network at http://{shown}:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="stretchserve", description=__doc__)
    parser.add_argument("directory", nargs="?", default=".", type=Path)
    parser.add_argument(
        "--host",
        default=None,
        help="bind address; default: ethernet if plugged in, else wifi "
        "(--host 127.0.0.1 for local only)",
    )
    parser.add_argument("--port", type=int, default=8377)
    args = parser.parse_args(argv)
    host = args.host if args.host is not None else pick_host()
    serve(args.directory, host, args.port)


if __name__ == "__main__":
    main()
