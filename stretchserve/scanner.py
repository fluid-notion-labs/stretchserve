"""Scanner for stretchtext markup in markdown text.

A document is markdown in which ``{{short|long}}`` marks a stretch: the
reader sees ``short``, and opening it puts ``long`` in its place. ``long``
may hold further stretches. Code spans and fences are opaque, so braces in
code never open a stretch.

This is a Python port of cc-stretch's ``hooks/parse.ts``
(https://github.com/pro-vi/cc-stretch), keeping its semantics:

- The long form contains every word of the short form, in order, growing
  around it. The scanner itself doesn't enforce this (see ``validate``);
  the authoring rules do.
- A stretch is keyed ``parent › short-form``, with ``~2``, ``~3`` on
  repeated siblings, so a stretch added elsewhere never shifts another
  stretch's key.
- ``{{abc}}`` with no ``|`` is a stretch with nothing to open: its braces
  vanish and ``abc`` shows as plain text.
- ``{{`` inside a short form is literal text; nesting only happens in
  long forms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

KEY_SEPARATOR = " › "

NEW_WORD_MARK = "stx-new"  # CSS class the browser uses to mark added words


@dataclass
class Stretch:
    key: str = ""
    short: str = ""
    long: list | None = None  # list of Segment; None when no `|` was written
    is_closed: bool = False
    pos: int = 0  # offset of the opening `{{`
    end_pos: int = 0  # offset just past the closing `}}` (len(text) if unclosed)
    siblings: dict = field(default_factory=dict)


Segment = str | Stretch

_BACKTICK_RUN = re.compile(r"`+")
_FENCE_OPEN = re.compile(r"^[ \t]*(`{3,}|~{3,})")


def opening_fence(line: str) -> str | None:
    """The marker `line` opens a code fence with, such as ``` or ~~~."""
    m = _FENCE_OPEN.match(line)
    return m.group(1) if m else None


def closes_fence(line: str, fence: str) -> bool:
    """Whether `line` closes the fence `fence` opened: only that character, repeated."""
    trimmed = line.strip()
    return trimmed.startswith(fence) and trimmed == fence[0] * len(trimmed)


def code_span(text: str, i: int, open_run: str | None = None) -> tuple[int, str | None]:
    """The code span at `i`: where it stops, and its backticks when still open.

    `open_run` carries the backticks of a span opened on an earlier line,
    whose close is then looked for from `i` on.
    """
    if open_run is not None:
        run = open_run
        end = text.find(run, i)
    else:
        m = _BACKTICK_RUN.match(text[i:]) if i < len(text) else None
        run = m.group(0) if m else "`"
        end = text.find(run, i + len(run))
    if end == -1:
        return len(text), open_run
    return end + len(run), None


def _line_end(text: str, frm: int) -> int:
    end = text.find("\n", frm)
    return len(text) if end == -1 else end


def fence_end(text: str, start: int) -> int | None:
    """Where a fence opening at `start` ends (past its closing line), or None."""
    opening = opening_fence(text[start : _line_end(text, start)])
    if opening is None:
        return None
    at = _line_end(text, start) + 1
    while at < len(text):
        le = _line_end(text, at)
        if closes_fence(text[at:le], opening):
            return min(le + 1, len(text))
        at = le + 1
    return len(text)


def parse(text: str) -> list[Segment]:
    """Parse `text` into a tree of Segments (str or Stretch)."""
    root: list[Segment] = []
    stack: list[Stretch] = []
    root_siblings: dict[str, int] = {}

    def append(segments: list, chunk: str) -> None:
        if segments and isinstance(segments[-1], str):
            segments[-1] += chunk
        else:
            segments.append(chunk)

    def write(chunk: str) -> None:
        if stack:
            top = stack[-1]
            if top.long is None:
                top.short += chunk
            else:
                append(top.long, chunk)
        else:
            append(root, chunk)

    i = 0
    n = len(text)
    while i < n:
        frame = stack[-1] if stack else None
        in_short = frame is not None and frame.long is None

        fence_stop = fence_end(text, i) if (i == 0 or text[i - 1] == "\n") else None
        if fence_stop is not None:
            write(text[i:fence_stop])
            i = fence_stop
            continue

        if text[i] == "`":
            stop, _ = code_span(text, i)
            write(text[i:stop])
            i = stop
            continue

        if text.startswith("{{", i) and not in_short:
            stretch = Stretch(pos=i)
            (frame.long if frame is not None else root).append(stretch)
            stack.append(stretch)
            i += 2
            continue

        if in_short and text[i] == "|":
            parent = stack[-2] if len(stack) > 1 else None
            frame.key = key_of(frame.short, parent, root_siblings)
            frame.long = []
            i += 1
            continue

        if frame is not None and text.startswith("}}", i):
            frame.is_closed = True
            frame.end_pos = i + 2
            stack.pop()
            i += 2
            continue

        write(text[i])
        i += 1

    return root


def key_of(short: str, parent: Stretch | None, root_siblings: dict) -> str:
    """A stretch's key: its trimmed short form (line breaks as ↵) under its parent's."""
    name = short.strip().replace("\n", "↵")
    siblings = parent.siblings if parent is not None else root_siblings
    seen = siblings.get(name, 0) + 1
    siblings[name] = seen
    own = name if seen == 1 else f"{name}~{seen}"
    return f"{parent.key}{KEY_SEPARATOR}{own}" if parent else own


def stretches(segments: list[Segment]) -> list[Stretch]:
    """Every stretch, outermost first, in document order."""
    out: list[Stretch] = []
    for seg in segments:
        if not isinstance(seg, str):
            out.append(seg)
            out.extend(stretches(seg.long or []))
    return out


def parent_of(key: str) -> str:
    """The key of the stretch holding the one keyed `key`, or '' at top level."""
    parts = key.split(KEY_SEPARATOR)
    return KEY_SEPARATOR.join(parts[:-1])


def _inner_raw(text: str, st: Stretch) -> str:
    if st.is_closed:
        return text[st.pos + 2 : st.end_pos - 2]
    return text[st.pos + 2 : st.end_pos]


def _words(s: str) -> list[str]:
    return re.findall(r"\w+", s.lower())


def _is_subseq(needle: list[str], haystack: list[str]) -> bool:
    it = iter(haystack)
    return all(tok in it for tok in needle)


def validate(text: str, segments: list[Segment] | None = None) -> list[dict]:
    """Structural checks on the stretch markup in `text`.

    Returns a list of issues: dicts with `severity` (error/warning),
    `line`, `key`, and `message`. Checks:

    - error: a `{{` never closed
    - error: a block-level stretch (its long form crosses a blank line)
      that is nested inside another stretch, or starts inside a list,
      quote, table or indentation — block growth is top-level only
    - error: the long form doesn't contain every word of the short form,
      in order (the growth rule)
    - warning: a stretch with no `|`, so there is nothing to open
    """
    if segments is None:
        segments = parse(text)
    issues: list[dict] = []

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    for st in stretches(segments):
        if not st.is_closed:
            issues.append(
                {
                    "severity": "error",
                    "line": line_of(st.pos),
                    "key": st.key or "(unclosed)",
                    "message": "stretch opened but never closed",
                }
            )
            continue
        raw = _inner_raw(text, st)
        if re.search(r"\n[ \t]*\n", raw):
            # Block-level growth. Placement rules: top level only.
            if parent_of(st.key):
                issues.append(
                    {
                        "severity": "error",
                        "line": line_of(st.pos),
                        "key": st.key,
                        "message": "block-level stretch inside another stretch (top level only)",
                    }
                )
            else:
                line_start = text.rfind("\n", 0, st.pos) + 1
                before = text[line_start:st.pos]
                stripped = before.lstrip()
                bad_context = (
                    (len(before) - len(stripped)) > 0
                    or stripped.startswith((">", "|", "-", "*", "+"))
                    or re.match(r"\d+[.)]\s", stripped)
                )
                if bad_context:
                    issues.append(
                        {
                            "severity": "error",
                            "line": line_of(st.pos),
                            "key": st.key,
                            "message": "block-level stretch must start at the top level of a block "
                            "(not in a list, quote, table, or indented)",
                        }
                    )
        if st.long is None:
            issues.append(
                {
                    "severity": "warning",
                    "line": line_of(st.pos),
                    "key": st.key,
                    "message": "stretch has no `|`, so there is nothing to open",
                }
            )
        else:
            long_flat = "".join(
                seg if isinstance(seg, str) else seg.short for seg in (st.long or [])
            )
            short_words = _words(st.short)
            long_words = _words(long_flat)
            if short_words and not _is_subseq(short_words, long_words):
                issues.append(
                    {
                        "severity": "error",
                        "line": line_of(st.pos),
                        "key": st.key,
                        "message": (
                            "long form does not contain the short form's words "
                            "in order (growth rule)"
                        ),
                    }
                )
    return issues
