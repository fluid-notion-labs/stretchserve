"""Tests for the stretch-aware markdown renderer."""

import re

from stretchserve.render import Renderer

r = Renderer()


def strip_ws(html):
    return re.sub(r"\s+", " ", html)


def test_basic_stretch_html():
    out = r.render("A {{build fails|build fails, about one run in five}} here.")
    assert out.html.count('class="stx"') == 1
    assert "stx-short" in out.html and "stx-long" in out.html
    assert "data-key=" in out.html
    assert out.issues == []


def test_braces_vanish_without_pipe():
    out = r.render("hello {{world}}!")
    assert "{{" not in out.html and "}}" not in out.html
    assert "world" in out.html


def test_code_protection():
    md = "use `{{short|long}}` and\n\n```\n{{a|b}}\n```\n"
    out = r.render(md)
    assert "{{short|long}}" in out.html  # code span untouched
    assert "{{a|b}}" in out.html  # fence untouched
    assert out.html.count('class="stx"') == 0


def test_list_item_structure_preserved():
    md = "- before {{item one|item one, with more detail}}\n- after {{item two|item two, with more detail}}\n"
    out = r.render(md)
    assert out.html.count("<li>") == 2
    assert out.html.count('class="stx"') == 2


def test_nesting_renders_recursively():
    md = "{{a b|a b, {{c|c d}} e}}"
    out = r.render(md)
    assert out.html.count('class="stx"') == 2
    # the nested key is namespaced under the parent
    parent_key = re.search(r'data-key="([^"]+)"', out.html).group(1)
    assert parent_key == "a b"


def test_markdown_inside_long_form():
    out = r.render("{{One thing|One thing, **bold** and `code` and [x](https://e.com)}}")
    assert "<strong>bold</strong>" in out.html
    assert "<code>code</code>" in out.html
    assert '<a href="https://e.com">x</a>' in out.html


def test_mermaid_fence_passthrough():
    out = r.render("```mermaid\nflowchart LR\n  A --> B\n```\n")
    assert "language-mermaid" in out.html


def test_tables_still_work():
    md = "| a |\n| - |\n| {{x|x y}} |\n"
    out = r.render(md)
    assert "<table>" in out.html
    assert out.html.count('class="stx"') == 1


def test_warning_box_issues():
    out = r.render("bad {{unclosed")
    assert any("never closed" in i["message"] for i in out.issues)


def test_heading_warning():
    out = r.render("# Title {{with|with a stretch}}")
    assert any("heading" in i["message"] for i in out.issues)


def test_deterministic_output():
    md = "A {{x|x y}} B {{z|z w}}"
    assert r.render(md).html == r.render(md).html
