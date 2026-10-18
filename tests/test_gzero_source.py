"""Tests for the read-only gzero source."""

import json
import sqlite3

import pytest

from stretchserve.gzero_source import GzeroSource, render_atom_scope, render_item, render_section
from stretchserve.workspace import WorkspaceError


def test_render_section():
    text = render_section({"name": "vision", "title": "Vision", "kind": "md", "body": "Be brief.\n"})
    assert text.startswith("# Vision\n\nBe brief.")


def test_render_section_checklist_kind_shows_kind():
    text = render_section({"name": "ship", "title": "", "kind": "checklist", "body": "- [ ] one\n"})
    assert text.startswith("# ship (checklist)")


def test_render_item_full():
    text = render_item(
        {
            "id": "a1b2",
            "title": "Serve gzero",
            "status": "in_progress",
            "priority": 1,
            "labels": ["mcp"],
            "assignee": "sess1",
            "design": "Use the CLI JSON modes.",
            "acceptance": "Agents can skim.",
            "notes": {"f00d": "did the thing"},
        }
    )
    assert "# Serve gzero" in text
    assert "`a1b2` · status: in_progress · priority: 1 · labels: mcp · assignee: sess1" in text
    assert "## Design\n\nUse the CLI JSON modes." in text
    assert "- (f00d) did the thing" in text


def test_render_item_minimal():
    text = render_item({"id": "x", "title": "T", "status": "open"})
    assert text == "# T\n\n`x` · status: open\n"


def test_render_atom_scope_groups_by_node():
    text = render_atom_scope(
        "p/gzero",
        [
            {"text": "be terse", "scope": "p/gzero", "node": "notes", "tags": ["style"]},
            {"text": "y-up", "scope": "p/gzero", "node": "3d", "tags": []},
        ],
    )
    assert "# atoms: p/gzero" in text
    assert "## 3d\n\n- y-up" in text
    assert "- be terse  (#style)" in text


def test_atoms_read_from_sqlite(tmp_path):
    db = tmp_path / "context.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE atoms (text TEXT NOT NULL, source TEXT NOT NULL, scope TEXT NOT NULL,
                            node TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]', PRIMARY KEY (text, source));
        CREATE TABLE tombstones (text TEXT PRIMARY KEY, atom TEXT NOT NULL);
        INSERT INTO atoms VALUES ('alive one', 's', 'p/g', 'notes', '["a"]');
        INSERT INTO atoms VALUES ('dead one', 's', 'p/g', 'notes', '[]');
        INSERT INTO tombstones VALUES ('dead one', '{}');
        """
    )
    con.close()
    src = GzeroSource(project_dir=tmp_path, db_path=db)
    atoms = src.atoms()
    assert [a["text"] for a in atoms] == ["alive one"]
    assert atoms[0]["tags"] == ["a"]


def test_documents_and_read_via_fake_cli(tmp_path, monkeypatch):
    calls = []

    def fake_run(self, *args):
        calls.append(args)
        joined = " ".join(args)
        if joined == "scope":
            return "p/gzero\n"
        if joined == "ws list --json":
            return json.dumps([{"name": "vision", "kind": "md", "title": "Vision", "order": 1}])
        if joined == "ws show vision --json":
            return json.dumps({"name": "vision", "title": "Vision", "kind": "md", "body": "Be {{brief|brief, and stay terse}}."})
        if joined == "item list --json":
            return json.dumps([{"id": "a1b2", "title": "Serve gzero", "status": "open"}])
        if joined == "item show a1b2 --json":
            return json.dumps({"id": "a1b2", "title": "Serve gzero", "status": "open"})
        raise AssertionError(joined)

    monkeypatch.setattr(GzeroSource, "_run", fake_run)
    src = GzeroSource(project_dir=tmp_path)
    docs = src.documents()
    paths = [d["path"] for d in docs]
    assert "gzero/ws/vision.md" in paths and "gzero/items/a1b2.md" in paths
    text, _ = src.read("gzero/ws/vision.md", mode="skim")
    assert "{{" not in text and "Be brief." in text
    text, _ = src.read("gzero/ws/vision.md", mode="read", open_keys=["brief"])
    assert "brief, and stay terse" in text
    with pytest.raises(WorkspaceError):
        src.read("gzero/ws/nope.md")


def test_check_reports_issues(tmp_path, monkeypatch):
    def fake_run(self, *args):
        joined = " ".join(args)
        if joined == "scope":
            return "p/g\n"
        if joined == "ws list --json":
            return "[]"
        if joined == "item list --json":
            return "[]"
        if joined == "ws show bad --json":
            return json.dumps({"name": "bad", "title": "Bad", "kind": "md", "body": "{{unclosed"})
        raise AssertionError(joined)

    monkeypatch.setattr(GzeroSource, "_run", fake_run)
    # no atoms db -> no atom docs; inject a section with broken markup
    def fake_sections(self):
        return [{"name": "bad", "title": "Bad", "kind": "md", "body": "{{unclosed"}]
    monkeypatch.setattr(GzeroSource, "sections", fake_sections)
    src = GzeroSource(project_dir=tmp_path)
    report = src.check("gzero/ws/bad.md")
    assert any("never closed" in i["message"] for i in report["issues"])
