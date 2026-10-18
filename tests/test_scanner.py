"""Tests for the stretchtext scanner (ported from cc-stretch's parse.ts)."""

from stretchserve.scanner import KEY_SEPARATOR, parse, stretches, validate


def short_texts(segments):
    return [s.short for s in stretches(segments)]


def test_simple_stretch():
    segs = parse("A {{build fails|build fails, about one run in five}} here.")
    assert segs == ["A ", segs[1], " here."]
    (st,) = stretches(segs)
    assert st.short == "build fails"
    assert st.is_closed
    assert [x for x in st.long if isinstance(x, str)] == ["build fails, about one run in five"]


def test_no_pipe_is_plain_text():
    segs = parse("hello {{world}}!")
    (st,) = stretches(segs)
    assert st.long is None
    assert st.short == "world"


def test_nesting():
    segs = parse("{{a b|a b {{c|c d}} e}}")
    outer = next(s for s in segs if not isinstance(s, str))
    assert outer.short == "a b"
    (child,) = [s for s in outer.long if not isinstance(s, str)]
    assert child.short == "c"
    assert child.key == f"{outer.key}{KEY_SEPARATOR}c"
    assert stretches(segs) == [outer, child]


def test_code_span_is_opaque():
    segs = parse("use `{{short|long}}` sparingly")
    assert stretches(segs) == []
    assert "".join(map(str, segs)) == "use `{{short|long}}` sparingly"


def test_fence_is_opaque():
    md = "text\n\n```\n{{a|b}}\n```\n\nmore {{c|c d}}\n"
    segs = parse(md)
    assert [s.short for s in stretches(segs)] == ["c"]


def test_tilde_fence():
    md = "~~~\n{{a|b}}\n~~~\n{{x|x y}}"
    assert [s.short for s in stretches(parse(md))] == ["x"]


def test_keys_stable_under_sibling_insertion():
    a = parse("{{first|first one}}")
    b = parse("{{zeroth|zeroth one}} {{first|first one}}")
    assert stretches(a)[0].key == stretches(b)[1].key == "first"


def test_sibling_repeats_get_ordinal():
    segs = parse("{{same|same here}} and {{same|same there}}")
    k1, k2 = (s.key for s in stretches(segs))
    assert k1 == "same" and k2 == "same~2"


def test_closing_braces_close_even_in_short_form():
    # Matching cc-stretch exactly: `{{` is literal inside a short form (written
    # char by char), but `}}` always closes, so the `|c}}` after it is plain text.
    segs = parse("{{outer {{x}} |outer text}} more")
    (st,) = stretches(segs)
    assert st.short == "outer {{x"
    assert st.long is None


def test_unclosed_stretch():
    issues = validate("hello {{world")
    assert any(i["severity"] == "error" and "never closed" in i["message"] for i in issues)


def test_block_stretch_top_level_is_fine():
    issues = validate("intro\n\n{{short|short, said once\n\nand then again}}\n\noutro")
    assert issues == []


def test_block_stretch_nested_rejected():
    issues = validate("{{outer|outer {{inner|inner one\n\ninner two}} text}}")
    assert any("inside another stretch" in i["message"] for i in issues)


def test_block_stretch_in_list_rejected():
    issues = validate("- item {{short|long one\n\nlong two}}")
    assert any("top level of a block" in i["message"] for i in issues)


def test_block_stretch_in_quote_or_indent_rejected():
    for md in ("> {{s|l one\n\nl two}}", "    {{s|l one\n\nl two}}"):
        assert any("top level of a block" in i["message"] for i in validate(md))


def test_containment_enforced():
    ok = validate("{{The build fails.|The CI build fails, about one run in five.}}")
    assert not any("growth" in i["message"] for i in ok)
    bad = validate("{{The build fails.|The CI build broke, about one run in five.}}")
    assert any(i["severity"] == "error" and "growth rule" in i["message"] for i in bad)


def test_no_pipe_warns():
    issues = validate("plain {{text}}")
    assert any(i["severity"] == "warning" and "nothing to open" in i["message"] for i in issues)


def test_open_braces_in_short_are_literal():
    segs = parse("{{a {{b}} tail")
    (st,) = stretches(segs)
    assert st.short == "a {{b"
    assert st.is_closed
