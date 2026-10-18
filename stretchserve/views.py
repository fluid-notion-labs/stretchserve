"""Markdown views over a stretchable document.

- `skim`: every stretch closed, braces stripped — the document reads
  complete, with openable spots invisible except in the key appendix.
- `read`: the stretches named by `open_keys` grown (their long forms in
  place, nested stretches closed unless also opened). Opening a key
  implicitly opens its ancestors.
- `source`: the file as written.

The key appendix lists every closed stretch with its key, so an agent
reading the skim can decide what to open next — the same feedback loop
cc-stretch gives a model by reporting which stretches were opened.
"""

from __future__ import annotations
from .scanner import KEY_SEPARATOR, Stretch, parse, stretches, validate


def resolve_keys(queries, doc_segments):
    """Resolve user key queries to canonical stretch keys.

    A query matches a stretch whose key equals it, ends with `sep + query`,
    or (uniquely) contains it. Returns (keys, errors).
    """
    all_st = stretches(doc_segments)
    keys = []
    errors = []
    for q in queries or []:
        q = q.strip()
        if not q:
            continue
        exact = [s.key for s in all_st if s.key == q]
        suffix = [s.key for s in all_st if s.key.endswith(KEY_SEPARATOR + q)]
        matches = exact or suffix or [s.key for s in all_st if q in s.key]
        if not matches:
            errors.append(f"no stretch matches key {q!r}")
        elif len(matches) > 1:
            errors.append(f"ambiguous key {q!r}: matches {', '.join(repr(m) for m in matches)}")
        else:
            keys.append(matches[0])
    return keys, errors


def expand_to_ancestors(keys):
    """Add every ancestor key so a child can be opened directly."""
    out = set()
    for key in keys:
        parts = key.split(KEY_SEPARATOR)
        for i in range(1, len(parts) + 1):
            out.add(KEY_SEPARATOR.join(parts[:i]))
    return out


def _active(stretch: Stretch, open_set: set) -> bool:
    return stretch.long is not None and stretch.key in open_set


def _render_segments(segments, open_set) -> str:
    out = []
    for seg in segments:
        if isinstance(seg, str):
            out.append(seg)
        elif _active(seg, open_set):
            out.append(_render_segments(seg.long, open_set))
        else:
            # closed stretch: braces vanish, the short form is plain text
            out.append(seg.short)
    return "".join(out)


def _appendix(doc_segments, open_set) -> str:
    lines = []
    for st in stretches(doc_segments):
        if st.long is None or not st.is_closed:
            continue
        depth = "  " * st.key.count(KEY_SEPARATOR)
        marker = "" if st.key in open_set else " [closed]"
        short = st.short.strip().replace("\n", " ")
        lines.append(f"- {depth}`{st.key}`{marker} — {short}")
    if not lines:
        return ""
    return "Closed stretches (pass a key as open_keys to read_document to grow it):\n" + "\n".join(lines)


def build_view(md_text: str, mode: str = "skim", open_keys=None) -> tuple[str, list]:
    """Return (view text, issues). mode: source | skim | read."""
    issues = [{"severity": i["severity"], "message": i["message"], "line": i["line"], "key": i.get("key", "")}
              for i in validate(md_text)]
    if mode == "source":
        return md_text, issues

    segments = parse(md_text)
    if mode not in ("skim", "read"):
        raise ValueError(f"unknown mode {mode!r}")

    resolved, errors = resolve_keys(open_keys or [], segments)
    for e in errors:
        issues.append({"severity": "error", "message": e, "line": 0, "key": ""})
    open_set = expand_to_ancestors(resolved) if mode == "read" else set()

    body = _render_segments(segments, open_set).rstrip()
    appendix = _appendix(segments, open_set)
    if appendix:
        body += "\n\n---\n\n" + appendix
    return body + "\n", issues

