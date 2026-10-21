"""Tests for the static site builder."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from stretchserve.build import build


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    (src / "sub" / "loose").mkdir(parents=True)
    (src / "index.md").write_text("# Home\n\nSee {{the guide|the guide, which explains everything}} and [demo](demo.md).\n")
    (src / "demo.md").write_text("# Demo\n\nBack to [home](index.md), or [the README](sub/README.md).\n")
    (src / "sub" / "README.md").write_text("# Sub\n\nUp to [demo](../demo.md).\n")
    (src / "sub" / "loose" / "note.md").write_text("# Note\n\nNo index here: [sub](../README.md).\n")
    (src / "img.png").write_bytes(b"png")
    return src


def test_pages_rendered_and_structure_mirrored(source: Path, tmp_path: Path):
    dest = build(source, tmp_path / "dist")
    assert (dest / "index.html").is_file()
    assert (dest / "demo.html").is_file()
    assert (dest / "sub" / "README.html").is_file()
    assert (dest / "sub" / "index.html").is_file()
    # loose dir has no index.md: a listing is generated
    assert (dest / "sub" / "loose" / "index.html").is_file()
    # non-md files copied verbatim
    assert (dest / "img.png").read_bytes() == b"png"
    # browser assets
    assert (dest / "__assets" / "stretch.js").is_file()
    assert (dest / "__assets" / "stretch.css").is_file()


def test_md_links_rewritten(source: Path, tmp_path: Path):
    dest = build(source, tmp_path / "dist")
    demo = (dest / "demo.html").read_text()
    assert 'href="index.html"' in demo
    assert 'href="sub/README.html"' in demo
    assert ".md\"" not in demo
    note = (dest / "sub" / "loose" / "note.html").read_text()
    assert 'href="../README.html"' in note


def test_stretch_markup_survives(source: Path, tmp_path: Path):
    dest = build(source, tmp_path / "dist")
    home = (dest / "index.html").read_text()
    assert 'class="stx"' in home
    assert "stx-short" in home and "stx-long" in home


def test_listing_lists_entries(source: Path, tmp_path: Path):
    dest = build(source, tmp_path / "dist")
    listing = (dest / "sub" / "loose" / "index.html").read_text()
    assert "note.html" in listing
    assert "/sub/loose" in listing


def test_refuses_to_build_into_source(source: Path):
    with pytest.raises(ValueError):
        build(source, source / "dist")
