"""Read-only gzero source: the atom store and workflow doc as virtual documents.

gzero already owns its mutations (the gzero CLI and gzero-mcp). This
source only *serves* gzero content as stretchable markdown, so agents can
skim it and open depth on demand:

- `gzero/ws/<name>.md`  — workflow sections of the project scope
- `gzero/items/<id>.md` — work items with design, acceptance, notes
- `gzero/atoms/<scope>.md` — atom-store brief, grouped by node

Data paths: sections and items come from the `gzero` CLI's JSON modes
(`ws list/show --json`, `item list/show --json`, run with the project
directory as cwd so repo-identity scoping applies); atoms come straight
from the SQLite store (`CX_DB`, default `~/.pi/agent/context.db`).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

from .workspace import WorkspaceError

DEFAULT_DB = Path.home() / ".pi" / "agent" / "context.db"


def render_section(section: dict) -> str:
    title = section.get("title") or section.get("name", "section")
    kind = section.get("kind", "md")
    body = section.get("body", "")
    head = f"# {title}"
    if kind != "md":
        head += f" ({kind})"
    return f"{head}\n\n{body}".rstrip() + "\n"


def render_item(item: dict) -> str:
    lines = [f"# {item.get('title', item.get('id', 'item'))}", ""]
    meta = [f"`{item.get('id', '')}`", f"status: {item.get('status', '?')}"]
    if item.get("priority") is not None:
        meta.append(f"priority: {item['priority']}")
    if item.get("labels"):
        meta.append("labels: " + ", ".join(item["labels"]))
    if item.get("assignee"):
        meta.append(f"assignee: {item['assignee']}")
    lines.append(" · ".join(meta))
    for key, heading in (("design", "Design"), ("acceptance", "Acceptance")):
        if item.get(key):
            lines += ["", f"## {heading}", "", str(item[key]).rstrip()]
    notes = item.get("notes") or {}
    if notes:
        lines += ["", "## Notes", ""]
        lines += [f"- ({nid}) {text}" for nid, text in notes.items()]
    return "\n".join(lines).rstrip() + "\n"


def render_atom_scope(scope: str, atoms: list[dict]) -> str:
    lines = [f"# atoms: {scope}", ""]
    by_node: dict[str, list[dict]] = {}
    for a in atoms:
        by_node.setdefault(a.get("node") or "notes", []).append(a)
    for node in sorted(by_node):
        lines += [f"## {node}", ""]
        for a in by_node[node]:
            tags = a.get("tags") or []
            suffix = f"  ({' '.join('#' + t for t in tags)})" if tags else ""
            lines.append(f"- {str(a['text']).strip()}{suffix}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class GzeroSource:
    """Reads gzero stores; `documents()`/`read()`/`check()` mirror the Workspace API."""

    def __init__(self, project_dir: Path | None = None, db_path: Path | None = None):
        self.project_dir = Path(project_dir) if project_dir else Path.cwd()
        self.db_path = Path(db_path or os.environ.get("CX_DB") or DEFAULT_DB)

    # -- gzero CLI ----------------------------------------------------------

    def _run(self, *args: str) -> str:
        try:
            proc = subprocess.run(
                ["gzero", *args],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError as e:
            raise WorkspaceError("gzero CLI not found on PATH") from e
        except subprocess.TimeoutExpired as e:
            raise WorkspaceError(f"gzero {' '.join(args)} timed out") from e
        if proc.returncode != 0:
            raise WorkspaceError(f"gzero {' '.join(args)}: {proc.stderr.strip()}")
        return proc.stdout

    def _run_json(self, *args: str):
        return json.loads(self._run(*args))

    def scope(self) -> str:
        return self._run("scope").strip()

    def sections(self) -> list[dict]:
        names = self._run_json("ws", "list", "--json")
        out = []
        for meta in names:
            section = self._run_json("ws", "show", meta["name"], "--json")
            out.append(section if isinstance(section, dict) else meta)
        return out

    def items(self) -> list[dict]:
        return list(self._run_json("item", "list", "--json"))

    def atoms(self) -> list[dict]:
        if not self.db_path.exists():
            return []
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            tombstoned = {r[0] for r in con.execute("SELECT text FROM tombstones")}
            rows = con.execute("SELECT text, scope, node, tags FROM atoms").fetchall()
        finally:
            con.close()
        alive = []
        for text, scope, node, tags in rows:
            if text in tombstoned:
                continue
            try:
                tag_list = json.loads(tags) if tags else []
            except json.JSONDecodeError:
                tag_list = []
            alive.append({"text": text, "scope": scope, "node": node, "tags": tag_list})
        return alive

    # -- document surface ---------------------------------------------------

    def documents(self) -> list[dict]:
        docs = []
        try:
            for s in self.sections():
                docs.append(self._doc(f"gzero/ws/{s.get('name', 'section')}.md", render_section(s)))
            for it in self.items():
                docs.append(self._doc(f"gzero/items/{it.get('id', 'item')}.md", render_item(it)))
            by_scope: dict[str, list[dict]] = {}
            for a in self.atoms():
                by_scope.setdefault(a["scope"], []).append(a)
            for scope, atoms in sorted(by_scope.items()):
                slug = scope.replace("/", "-")
                docs.append(self._doc(f"gzero/atoms/{slug}.md", render_atom_scope(scope, atoms)))
        except WorkspaceError:
            pass  # surface what we could read; an unreachable store is not fatal for listing
        return docs

    @staticmethod
    def _doc(path: str, text: str) -> dict:
        from .scanner import parse, stretches, validate

        segs = parse(text)
        issues = validate(text, segs)
        title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("# ")), path)
        return {
            "path": path,
            "title": title,
            "stretches": len(stretches(segs)),
            "openable": sum(1 for s in stretches(segs) if s.long is not None),
            "issues": len([i for i in issues if i["severity"] == "error"]),
        }

    def read(self, path: str, mode: str = "skim", open_keys=None) -> tuple[str, list]:
        for doc in self.documents():
            if doc["path"] == path:
                text = self._render_path(path)
                from .views import build_view

                return build_view(text, mode=mode, open_keys=open_keys)
        raise WorkspaceError(f"no such gzero document: {path}")

    def _render_path(self, path: str) -> str:
        if path.startswith("gzero/ws/"):
            name = path[len("gzero/ws/"):-3]
            return render_section(self._run_json("ws", "show", name, "--json"))
        if path.startswith("gzero/items/"):
            item_id = path[len("gzero/items/"):-3]
            return render_item(self._run_json("item", "show", item_id, "--json"))
        if path.startswith("gzero/atoms/"):
            slug = path[len("gzero/atoms/"):-3]
            by_scope: dict[str, list[dict]] = {}
            for a in self.atoms():
                by_scope.setdefault(a["scope"], []).append(a)
            for scope, atoms in sorted(by_scope.items()):
                if scope.replace("/", "-") == slug:
                    return render_atom_scope(scope, atoms)
        raise WorkspaceError(f"no such gzero document: {path}")

    def check(self, path: str) -> dict:
        for doc in self.documents():
            if doc["path"] == path:
                text = self._render_path(path)
                from .views import build_view

                _, issues = build_view(text, mode="source")
                return {"issues": issues, "stretches": [], "diagrams": []}
        raise WorkspaceError(f"no such gzero document: {path}")
