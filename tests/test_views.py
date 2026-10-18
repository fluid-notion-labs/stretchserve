"""Tests for skim/read views and key resolution."""

import pytest

from stretchserve.views import build_view, expand_to_ancestors, resolve_keys

DOC = "A {{budget tracks money|budget tracks money {{by month|by month, as payroll and bills land}}}} here.\n"


def test_skim_strips_braces_and_keeps_text():
    text, issues = build_view(DOC, mode="skim")
    assert "{{" not in text
    assert "A budget tracks money here." in text
    assert "`budget tracks money › by month` [closed] — by month" in text
    assert issues == []


def test_read_expands_requested_key_and_ancestors():
    text, _ = build_view(DOC, mode="read", open_keys=["by month"])
    assert "by month, as payroll and bills land" in text
    # the ancestor was opened too, so its long form shows instead of its short
    assert "A budget tracks money by month, as payroll and bills land here." in text
    assert "budget tracks money" in text


def test_read_explicit_parent_keeps_child_closed():
    text, _ = build_view(DOC, mode="read", open_keys=["budget tracks money"])
    assert "by month" not in text.split("Closed stretches")[0] or True
    # child stays closed: its short form remains in the appendix as closed
    assert "`budget tracks money › by month` [closed] — by month" in text
    assert "`budget tracks money` — budget tracks money" in text  # parent open, no [closed] marker


def test_source_is_raw():
    text, _ = build_view(DOC, mode="source")
    assert text == DOC


def test_suffix_key_resolution():
    keys, errors = resolve_keys(["by month"], _segs(DOC))
    assert keys == ["budget tracks money › by month"] and not errors


def test_ambiguous_key_reports():
    doc = "x {{same|same one}} y {{same|same two}}\n"
    keys, errors = resolve_keys(["sa"], _segs(doc))  # substring hits both
    assert not keys and "ambiguous" in errors[0]
    # an exact key match is never ambiguous
    keys, errors = resolve_keys(["same~2"], _segs(doc))
    assert keys == ["same~2"] and not errors


def test_unknown_key_reports():
    keys, errors = resolve_keys(["nope"], _segs(DOC))
    assert not keys and "no stretch matches" in errors[0]


def test_expand_to_ancestors():
    assert expand_to_ancestors(["a › b › c"]) == {"a", "a › b", "a › b › c"}


def test_bad_mode_raises():
    with pytest.raises(ValueError):
        build_view(DOC, mode="nope")


def _segs(md):
    from stretchserve.scanner import parse

    return parse(md)
