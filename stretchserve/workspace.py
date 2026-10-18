"""A workspace: a directory of stretchable markdown documents.

The MCP tools and the `check` command both operate on a Workspace. All
paths are workspace-relative, must name a `.md` file, and are confined
to the root (no traversal, no symlinks escaping it).
"""

from __future__ import annotations

import re
from pathlib import Path

from .scanner import parse, stretches, validate
from .views import build_view


class WorkspaceError(Exception):
    """A request the workspace refuses (bad path, missing file, invalid content)."""


def _resolve(root: Path, path: str) -> Path:
    if not path or path.startswith("/"):
        raise WorkspaceError(f"path must be workspace-relative, got {path!r}")
    target = (root / path).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and not target.is_relative_to(root_resolved):
        raise WorkspaceError(f"path escapes the workspace: {path!r}")
    if target.suffix != ".md":
        raise WorkspaceError(f"only .md documents are managed, got {path!r}")
    return target


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()

    # -- inspection ---------------------------------------------------------

    def documents(self) -> list[dict]:
        docs = []
        for file in sorted(self.root.rglob("*.md")):
            rel = file.relative_to(self.root).as_posix()
            text = file.read_text(encoding="utf-8", errors="replace")
            segs = parse(text)
            st = stretches(segs)
            issues = validate(text, segs)
            title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("# ")), file.stem)
            docs.append(
                {
                    "path": rel,
                    "title": title,
                    "stretches": len(st),
                    "openable": sum(1 for s in st if s.long is not None),
                    "issues": len([i for i in issues if i["severity"] == "error"]),
                }
            )
        return docs

    def read(self, path: str, mode: str = "skim", open_keys=None) -> tuple[str, list]:
        """Return (text, issues) for a document in the given view mode."""
        file = _resolve(self.root, path)
        if not file.is_file():
            raise WorkspaceError(f"no such document: {path}")
        text = file.read_text(encoding="utf-8", errors="replace")
        return build_view(text, mode=mode, open_keys=open_keys)

    def check(self, path: str) -> dict:
        file = _resolve(self.root, path)
        if not file.is_file():
            raise WorkspaceError(f"no such document: {path}")
        text = file.read_text(encoding="utf-8", errors="replace")
        segs = parse(text)
        issues = validate(text, segs)
        diagrams = []
        # Diagrams live in fences, which the scanner treats as opaque text.
        for m in re.finditer(r"^(?P<fence>`{3,}|~{3,})(?P<lang>\w+)", text, re.M):
            if m.group("lang") in ("mermaid", "dot", "graphviz"):
                diagrams.append({"line": text[: m.start()].count("\n") + 1, "lang": m.group("lang")})
        keys = [
            {"key": s.key, "short": s.short.strip(), "depth": s.key.count(" › "), "openable": s.long is not None}
            for s in stretches(segs)
        ]
        return {"issues": issues, "stretches": keys, "diagrams": diagrams}

    # -- mutation -----------------------------------------------------------

    def _validate_content(self, text: str) -> list[dict]:
        return validate(text)

    def write(self, path: str, content: str, strict: bool = True, overwrite: bool = True) -> list[dict]:
        """Create or overwrite a document. Returns the issues found.

        With strict=True, hard errors (unclosed stretches, growth-rule
        violations, stretches crossing blank lines) refuse the write;
        warnings never do.
        """
        file = _resolve(self.root, path)
        if file.exists() and not overwrite:
            raise WorkspaceError(f"{path} already exists (use edit_document or overwrite=true)")
        issues = self._validate_content(content)
        if strict and any(i["severity"] == "error" for i in issues):
            raise WorkspaceError(
                "refusing to write: "
                + "; ".join(f"line {i['line']}: {i['message']}" for i in issues if i["severity"] == "error")
            )
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
        return issues

    def create(self, path: str, content: str, strict: bool = True) -> list[dict]:
        return self.write(path, content, strict=strict, overwrite=False)

    def edit(self, path: str, find: str, replace: str, strict: bool = True) -> list[dict]:
        """Replace the single occurrence of `find` with `replace`."""
        file = _resolve(self.root, path)
        if not file.is_file():
            raise WorkspaceError(f"no such document: {path}")
        text = file.read_text(encoding="utf-8", errors="replace")
        count = text.count(find)
        if count == 0:
            raise WorkspaceError(f"find text not found in {path}")
        if count > 1:
            raise WorkspaceError(f"find text occurs {count} times in {path}; make it unique")
        new_text = text.replace(find, replace)
        issues = self._validate_content(new_text)
        if strict and any(i["severity"] == "error" for i in issues):
            raise WorkspaceError(
                "edit refused (document would be invalid): "
                + "; ".join(f"line {i['line']}: {i['message']}" for i in issues if i["severity"] == "error")
            )
        file.write_text(new_text, encoding="utf-8")
        return issues

    def delete(self, path: str) -> None:
        file = _resolve(self.root, path)
        if not file.is_file():
            raise WorkspaceError(f"no such document: {path}")
        file.unlink()
