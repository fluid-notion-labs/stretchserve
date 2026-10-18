"""Tests for the workspace: create/read/edit/delete with path safety."""

import pytest

from stretchserve.workspace import Workspace, WorkspaceError

GOOD = "A {{budget tracks money|budget tracks money {{by month|by month, as payroll and bills land}}}} here.\n"
BAD = "A {{budget tracks money|a plan that drops the original words}}.\n"  # growth-rule violation


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path)


def test_create_and_list(ws):
    assert ws.create("notes/budget.md", GOOD) == []
    docs = ws.documents()
    assert docs[0]["path"] == "notes/budget.md"
    assert docs[0]["stretches"] == 2


def test_create_rejects_hard_errors(ws):
    with pytest.raises(WorkspaceError, match="refusing"):
        ws.create("b.md", BAD)


def test_create_lenient_stores_and_reports(ws):
    issues = ws.create("b.md", BAD, strict=False)
    assert any("growth" in i["message"] for i in issues)
    assert (ws.root / "b.md").exists()


def test_create_no_overwrite(ws):
    ws.create("b.md", GOOD)
    with pytest.raises(WorkspaceError, match="already exists"):
        ws.create("b.md", GOOD)


def test_edit_single_match(ws):
    ws.create("b.md", GOOD)
    ws.edit("b.md", "here.", "there.")
    assert "there." in ws.read("b.md", mode="source")[0]


def test_edit_rejects_ambiguity_and_missing(ws):
    ws.create("b.md", GOOD)
    with pytest.raises(WorkspaceError, match="not found"):
        ws.edit("b.md", "zzz", "y")
    ws.create("c.md", "repeat\n\nrepeat\n")
    with pytest.raises(WorkspaceError, match="2 times"):
        ws.edit("c.md", "repeat", "x")


def test_edit_validates_result(ws):
    ws.create("b.md", GOOD)
    with pytest.raises(WorkspaceError, match="would be invalid"):
        ws.edit("b.md", "budget tracks money {{by month|by month, as payroll and bills land}}", "clean prose")


def test_delete_and_missing(ws):
    ws.create("b.md", GOOD)
    ws.delete("b.md")
    with pytest.raises(WorkspaceError, match="no such document"):
        ws.delete("b.md")
    with pytest.raises(WorkspaceError, match="no such document"):
        ws.read("b.md")


def test_path_safety(ws):
    for bad in ["../outside.md", "/abs.md", "b.txt", ""]:
        with pytest.raises(WorkspaceError):
            ws.create(bad, GOOD)


def test_check_reports_diagrams(ws):
    doc = "text\n\n```mermaid\nflowchart LR\nA-->B\n```\n\n```dot\ndigraph{a->b}\n```\n"
    ws.create("d.md", doc)
    report = ws.check("d.md")
    langs = [d["lang"] for d in report["diagrams"]]
    assert langs == ["mermaid", "dot"]
    assert report["stretches"] == []


def test_check_lists_keys(ws):
    ws.create("b.md", GOOD)
    report = ws.check("b.md")
    keys = [k["key"] for k in report["stretches"]]
    assert "budget tracks money" in keys
    assert "budget tracks money › by month" in keys
