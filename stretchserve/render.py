"""Render stretchtext markdown to HTML.

Pipeline (server-side, so the browser only toggles and decorates):

1. Scan the markdown into a stretch tree (`scanner.parse`).
2. Replace every stretch with a unique alphanumeric token; keep a registry
   mapping token -> stretch (with the stretch's own short/long fragments
   carrying tokens for their nested stretches).
3. Convert the tokenized document with python-markdown once, so list,
   table and heading structure around and inside stretches is preserved.
4. Convert each stretch's short and long fragments separately and
   substitute them back in, resolving nested tokens recursively.

Code spans, fences and headings never hold tokens (the scanner keeps code
opaque; a heading check runs on the final HTML).
"""

from __future__ import annotations

import html
import re
import secrets
from dataclasses import dataclass, field
from html.parser import HTMLParser

import markdown as md_lib

from .scanner import Segment, Stretch, parse, validate

# No codehilite: it mangles ```mermaid source and drops the language-* class
# the browser needs. Fenced blocks stay verbatim; mermaid/viz render them.
_DEFAULT_EXTENSIONS = ["fenced_code", "tables", "sane_lists"]
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


@dataclass
class RenderResult:
    html: str
    issues: list[dict] = field(default_factory=list)


class Renderer:
    def __init__(self, extensions: list[str] | None = None):
        self.extensions = list(extensions) if extensions is not None else _DEFAULT_EXTENSIONS

    def convert(self, text: str) -> str:
        return md_lib.markdown(text, extensions=self.extensions)

    def render(self, md_text: str) -> RenderResult:
        segments = parse(md_text)
        issues = validate(md_text, segments)
        registry: dict[str, dict] = {}
        flat = self._flatten(segments, registry, md_text)
        flat = self._place_block_tokens(flat, registry)
        html_out = self.convert(flat)
        html_out = self._substitute(html_out, registry)
        html_out, in_heading = self._check_headings(html_out, registry)
        for key in in_heading:
            issues.append(
                {
                    "severity": "warning",
                    "line": 0,
                    "key": key,
                    "message": "stretch inside a heading (authoring rule: don't)",
                }
            )
        return RenderResult(html=html_out, issues=issues)

    # -- flattening ---------------------------------------------------------

    def _alloc_token(self, registry: dict, doc_text: str) -> str:
        salt = secrets.token_hex(3)
        for n in range(1, 1000):
            tok = f"stx{salt}{n}z"
            if tok not in doc_text and tok not in registry:
                return tok
        raise RuntimeError("could not allocate a unique placeholder token")

    def _flatten(self, segments: list[Segment], registry: dict, doc_text: str) -> str:
        """Replace every stretch in `segments` with a token, registering it."""
        parts: list[str] = []
        for seg in segments:
            if isinstance(seg, str):
                parts.append(seg)
                continue
            tok = self._alloc_token(registry, doc_text)
            entry = {"stretch": seg}
            if seg.long is not None:
                long_flat = self._flatten(seg.long, registry, doc_text)
                entry["long_flat"] = long_flat
                # A long form that crosses a blank line grows at block level.
                entry["block"] = bool(_BLANK_LINE.search(long_flat))
            registry[tok] = entry
            parts.append(tok)
        return "".join(parts)

    def _place_block_tokens(self, flat: str, registry: dict) -> str:
        """Give each block-level token a paragraph of its own.

        A block stretch's token replaces the whole `{{short|long}}` span;
        any text sharing its line is broken off into its own paragraphs, so
        markdown renders the token as a standalone block.
        """
        positions = []
        for tok, entry in registry.items():
            if entry.get("block"):
                i = flat.find(tok)
                if i != -1:
                    positions.append((i, tok))
        positions.sort(reverse=True)  # insert from the end; earlier indices stay valid
        for i, tok in positions:
            end = i + len(tok)
            line_end = flat.find("\n", end)
            if line_end == -1:
                line_end = len(flat)
            if flat[end:line_end].strip():
                flat = flat[:end] + "\n\n" + flat[end:]
            line_start = flat.rfind("\n", 0, i) + 1
            if flat[line_start:i].strip():
                flat = flat[:i] + "\n\n" + flat[i:]
        return flat

    # -- substitution -------------------------------------------------------

    def _substitute(self, html_out: str, registry: dict) -> str:
        for _ in range(200):
            changed = False
            for tok, entry in registry.items():
                if entry.get("block") and tok in html_out:
                    # The token should own its paragraph: replace `<p>TOKEN</p>` whole.
                    block_html = self._token_html(entry, registry, block=True)
                    html_out, n = re.subn(rf"<p>\s*{tok}\s*</p>", lambda m: block_html, html_out)
                    if n:
                        changed = True
                if tok in html_out:
                    html_out = html_out.replace(tok, self._token_html(entry, registry))
                    changed = True
            if not changed:
                return html_out
        raise RuntimeError("placeholder substitution did not settle")

    def _token_html(self, entry: dict, registry: dict, block: bool = False) -> str:
        st: Stretch = entry["stretch"]
        if st.long is None:
            # Nothing to open: the braces vanish, the short form is plain text.
            return self._convert_inline(st.short)
        short_html = self._convert_inline(st.short)
        long_flat = entry.get("long_flat", "")
        long_html = self._substitute(self.convert(long_flat) if block else self._convert_inline(long_flat), registry)
        key = html.escape(st.key, quote=True)
        if block:
            return (
                f'<div class="stx stx-block" data-key="{key}">'
                f'<span class="stx-short">{short_html}</span>'
                f'<div class="stx-long">{long_html}</div>'
                f"</div>"
            )
        return (
            f'<span class="stx" data-key="{key}">'
            f'<span class="stx-short">{short_html}</span>'
            f'<span class="stx-long">{long_html}</span>'
            f"</span>"
        )

    def _convert_inline(self, fragment: str) -> str:
        """Convert an inline markdown fragment, stripping its <p> wrapper."""
        html_out = self.convert(fragment).strip()
        if html_out.startswith("<p>") and html_out.endswith("</p>") and html_out.count("<p>") == 1:
            return html_out[3:-4]
        return html_out

    # -- checks on the final HTML ------------------------------------------

    def _check_headings(self, html_out: str, registry: dict) -> tuple[str, list[str]]:
        """Return (html, keys of stretches that landed inside a heading)."""
        token_to_key = {
            tok: entry["stretch"].key
            for tok, entry in registry.items()
            if entry["stretch"].long is not None
        }
        found: list[str] = []

        class P(HTMLParser):
            depth = 0

            def handle_starttag(self, tag, attrs):
                if tag in _HEADING_TAGS:
                    self.depth += 1
                elif tag == "span" and self.depth > 0:
                    a = dict(attrs)
                    if a.get("data-key"):
                        found.append(a["data-key"])

            def handle_endtag(self, tag):
                if tag in _HEADING_TAGS:
                    self.depth = max(0, self.depth - 1)

        p = P(convert_charrefs=True)
        p.feed(html_out)
        # Token strings that survived conversion but map to real stretches
        # mean markdown mangled them (e.g. inside a table the token still
        # substitutes fine; a truly lost token is reported here).
        for tok, key in token_to_key.items():
            if tok in html_out:
                found.append(key)
        # de-duplicate, keep order
        seen: set[str] = set()
        unique = [k for k in found if not (k in seen or seen.add(k))]
        return html_out, unique
