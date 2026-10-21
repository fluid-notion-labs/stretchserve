"""Build a static site from a directory of stretchable markdown.

Renders every `.md` file to a full HTML page at build time — the same
renderer the server runs per request — mirrors the directory structure,
copies other files verbatim, and writes the browser assets. The output
is plain static files: deploy it to Cloudflare Pages, R2, S3, GitHub
Pages, or any web server.

Mapping:

- `a/b.md`          -> `a/b.html` (rendered page)
- `a/index.md`      -> `a/index.html` (also `a/README.md` -> `a/index.html`)
- `a/b/` with no index -> `a/b/index.html` (generated listing page)
- everything else   -> copied verbatim
- browser assets    -> `__assets/`

Links ending in `.md` are rewritten to `.html`, so authoring links stay
the same as for the live server.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
from pathlib import Path

from .render import Renderer
from .server import ASSETS_DIR, _PAGE, _warnings_html

_INDEX_NAMES = ("index.md", "README.md")

# href="doc.md", href="doc.md#anchor" -> .html; excludes "://", "mailto:"
_MD_HREF = re.compile(r'(href=")([^":]+?)\.md')


def build(source: Path, dest: Path) -> Path:
    source, dest = source.resolve(), dest.resolve()
    if dest == source or source in dest.parents:
        raise ValueError(f"output directory {dest} would be built into the source {source}")
    if dest.exists():
        shutil.rmtree(dest)
    renderer = Renderer()
    md_files = sorted(p for p in source.rglob("*.md") if dest not in p.parents)

    for file in md_files:
        rel = file.relative_to(source)
        text = file.read_text(encoding="utf-8", errors="replace")
        result = renderer.render(text)
        page = _rewrite_md_hrefs(
            _PAGE.format(
                title=html.escape(file.stem),
                warnings=_warnings_html(result.issues),
                body=result.html,
                pygments_css="",
            )
        )
        out = dest / rel.with_suffix(".html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        if file.name in _INDEX_NAMES:
            (dest / rel.parent / "index.html").write_text(page, encoding="utf-8")

    for directory in sorted(source.rglob("*")):
        if not directory.is_dir() or dest in directory.parents:
            continue
        rel_dir = directory.relative_to(source)
        if not any((directory / name).is_file() for name in _INDEX_NAMES):
            out = dest / rel_dir / "index.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_listing(directory, rel_dir), encoding="utf-8")

    for file in source.rglob("*"):
        if file.is_file() and file.suffix != ".md" and dest not in file.parents:
            rel = file.relative_to(source)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)

    assets = dest / "__assets"
    assets.mkdir(exist_ok=True)
    for asset in ASSETS_DIR.iterdir():
        if asset.is_file():
            shutil.copy2(asset, assets / asset.name)

    return dest


def _rewrite_md_hrefs(page: str) -> str:
    return _MD_HREF.sub(r"\g<1>\g<2>.html", page)


def _listing(directory: Path, rel_dir: Path) -> str:
    entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    rows = []
    for entry in entries:
        if entry.suffix == ".md":
            href = entry.name[:-3] + ".html"
        elif entry.is_dir():
            href = entry.name + "/index.html"
        else:
            href = entry.name
        name = entry.name + ("/" if entry.is_dir() else "")
        rows.append(f'<li><a href="{html.escape(href, quote=True)}">{html.escape(name)}</a></li>')
    path = "/" + str(rel_dir) if str(rel_dir) != "." else "/"
    body = f"<h1>{html.escape(path)}</h1><ul>{''.join(rows)}</ul>"
    return _PAGE.format(
        title=html.escape(str(rel_dir)),
        warnings="",
        body=body,
        pygments_css="",
    )
