"""MCP server for a stretchable-markdown workspace.

Run with `stretchserve mcp [dir]` (stdio transport). Tools:

- list_documents: files with title, stretch counts, issue counts
- read_document(path, mode, open_keys): source | skim | read views
- create_document / write_document / edit_document / delete_document
- check_document: issues, stretch key map, diagram blocks

Mermaid and graphviz diagrams are authored as fenced blocks
(```mermaid, ```dot); check_document reports them and `stretchserve
serve` renders them in the browser.
"""

from __future__ import annotations

from pathlib import Path

from .workspace import Workspace, WorkspaceError

_DEFAULT_ROOT = "."


def _fmt_issues(issues: list[dict]) -> str:
    if not issues:
        return ""
    lines = [f"- {i['severity']}: line {i['line']}: {i['message']}" + (f" [{i['key']}]" if i.get("key") else "") for i in issues]
    return "Issues:\n" + "\n".join(lines) + "\n"


def make_mcp(root: Path = Path(_DEFAULT_ROOT)):
    """Build the FastMCP server bound to a workspace root."""
    from mcp.server.mcpserver import MCPServer

    ws = Workspace(Path(root))
    mcp = MCPServer(name="stretchserve", instructions=(
        "Workspace of stretchable markdown documents. A stretch is written "
        "{{short|long}}: the reader sees short; opening it grows the long form "
        "in place. Rules: the short form answers on its own; the long form keeps "
        "every word of the short form in order, growing around it; stretches nest; "
        "keep the short form on one line; never put a stretch in code, tables or "
        "headings. Diagrams: fenced ```mermaid and ```dot blocks render in the "
        "browser via `stretchserve serve`."
    ))

    @mcp.tool()
    def list_documents() -> str:
        """List workspace documents: path, title, stretch counts, issue counts."""
        docs = ws.documents()
        if not docs:
            return "(workspace is empty)"
        lines = []
        for d in docs:
            extra = f", {d['issues']} errors" if d["issues"] else ""
            lines.append(f"- {d['path']} — {d['title']} — {d['stretches']} stretches ({d['openable']} openable{extra})")
        return "\n".join(lines)

    @mcp.tool()
    def read_document(path: str, mode: str = "skim", open_keys: list[str] | None = None) -> str:
        """Read a document. mode: 'source' (raw markdown), 'skim' (all stretches
        closed, braces stripped — the default, complete prose), or 'read'
        (grow the stretches named in open_keys; opening a key opens its
        ancestors). The appendix lists closed stretches with their keys.
        """
        text, issues = ws.read(path, mode=mode, open_keys=open_keys)
        if mode == "source":
            return text
        return text if not issues else text + "\n\n" + _fmt_issues(issues)

    @mcp.tool()
    def check_document(path: str) -> str:
        """Validate a document: issues, stretch keys (for read_document open_keys),
        and diagram blocks (mermaid/dot) that will render in the browser."""
        report = ws.check(path)
        out = _fmt_issues(report["issues"])
        keys = [k["key"] for k in report["stretches"] if k["openable"]]
        if keys:
            out += "Stretch keys:\n" + "\n".join(f"- {k}" for k in keys) + "\n"
        if report["diagrams"]:
            out += "Diagrams (rendered in browser): " + ", ".join(
                f"{d['lang']} (line {d['line']})" for d in report["diagrams"]) + "\n"
        return out or "no issues, no stretches, no diagrams"

    @mcp.tool()
    def create_document(path: str, content: str, strict: bool = True) -> str:
        """Create a new document. The content is stretch markup validated on
        write; with strict=true (default) hard errors refuse the write, with
        strict=false it is stored and the issues returned. Warnings never refuse.
        """
        try:
            issues = ws.create(path, content, strict=strict)
        except WorkspaceError as e:
            return f"error: {e}"
        return f"created {path}" + ("\n" + _fmt_issues(issues) if issues else " (no issues)")

    @mcp.tool()
    def write_document(path: str, content: str, strict: bool = True) -> str:
        """Create or overwrite a document with new content (same validation as
        create_document)."""
        try:
            issues = ws.write(path, content, strict=strict)
        except WorkspaceError as e:
            return f"error: {e}"
        return f"wrote {path}" + ("\n" + _fmt_issues(issues) if issues else " (no issues)")

    @mcp.tool()
    def edit_document(path: str, find: str, replace: str) -> str:
        """Replace the single occurrence of `find` with `replace` in a document.
        The result must stay valid (growth rule etc.); `find` must match exactly once.
        """
        try:
            issues = ws.edit(path, find, replace)
        except WorkspaceError as e:
            return f"error: {e}"
        return f"edited {path}" + ("\n" + _fmt_issues(issues) if issues else " (no issues)")

    @mcp.tool()
    def delete_document(path: str) -> str:
        """Delete a document from the workspace."""
        try:
            ws.delete(path)
        except WorkspaceError as e:
            return f"error: {e}"
        return f"deleted {path}"

    return mcp


def run(root: Path = Path(_DEFAULT_ROOT)) -> None:
    make_mcp(root).run()  # stdio transport
