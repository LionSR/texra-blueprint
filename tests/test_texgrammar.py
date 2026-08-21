from texra_blueprint.texgrammar import (
    CONTROL_WORD, DIMENSION_EXPRESSION, ROW_BREAK_LENGTH, stringify_tex_item)


def test_row_break_lengths():
    for good in ("2pt", "-1.5em", r"\jot", r"2\baselineskip", r"0.5 \parskip"):
        assert ROW_BREAK_LENGTH.match(good), good
    for bad in (r"A, B", r"\alpha", r"P, Q", "2", r"\sum_i"):
        assert not ROW_BREAK_LENGTH.match(bad), bad


def test_control_word():
    m = CONTROL_WORD.match(r"2\mylength")
    assert m and m.group(4) == "mylength"
    assert CONTROL_WORD.match(r"\alpha")
    assert not CONTROL_WORD.match(r"\alpha_i")


def test_dimension_expression():
    assert DIMENSION_EXPRESSION.search(r"\dimexpr 2pt + 1pt")
    assert not DIMENSION_EXPRESSION.search(r"[A, B]")


def test_stringify():
    class Tok:
        source = " x "
    assert stringify_tex_item(Tok()) == "x"
    assert stringify_tex_item("plain ") == "plain"
