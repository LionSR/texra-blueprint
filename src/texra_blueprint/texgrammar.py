"""TeX-grammar helpers shared by the texra-blueprint plasTeX packages.

This module keeps no plasTeX import of its own, so a generated-page
regression can read the row-break rule below without loading -- and thereby
patching -- the renderer it is meant to be checking.
"""

from __future__ import annotations

import re
from typing import Any


# The named lengths a row break may be given.  A control word outside this
# list is a mathematical symbol, not a dimension: \alpha and \sum open a row,
# they do not measure the gap above it.
_NAMED_LENGTHS = (
    "jot",
    "baselineskip",
    "lineskip",
    "parskip",
    "smallskipamount",
    "medskipamount",
    "bigskipamount",
    "abovedisplayskip",
    "belowdisplayskip",
    "abovedisplayshortskip",
    "belowdisplayshortskip",
    "topsep",
    "arraycolsep",
    "tabcolsep",
    "arrayrulewidth",
    "doublerulesep",
    "textwidth",
    "textheight",
    "linewidth",
    "columnwidth",
    "parindent",
    "fboxsep",
    "fboxrule",
    "extrarowheight",
)

# The spelling of a decimal number, and the optional sign and numeric factor
# that may precede a length.  The number's groups are capturing so downstream
# group numbers stay put: ``CONTROL_WORD.match(...).group(4)`` is the control
# word's name.
_NUMBER = r"(\d+(\.\d*)?|\.\d+)"
_SIGN = r"\s*[-+]?\s*"
_FACTOR = r"(" + _NUMBER + r"\s*)?"

# What may stand in brackets after a row break and mean the gap to the next
# row: a number with a unit, or one of the named lengths with an optional
# factor in front of it.  Anything else there is mathematics, and reading it
# as a gap turns the row into an error box.
ROW_BREAK_LENGTH = re.compile(
    _SIGN + r"""(
          """ + _NUMBER + r"""\s*(pt|pc|in|bp|cm|mm|dd|cc|sp|ex|em|mu)
        | """ + _FACTOR + r"""\\(""" + "|".join(_NAMED_LENGTHS) + r""")
        )\s*$""",
    re.VERBOSE,
)

# A dimension a document declares for itself carries no telling spelling, so
# a lone control word is left to the renderer, which asks the document what
# the name means.  Everything with structure in it -- a subscript, a comma, a
# pair of parentheses, a second symbol -- is mathematics either way.
CONTROL_WORD = re.compile(_SIGN + _FACTOR + r"\\([A-Za-z@]+)\s*$")

# Arithmetic on dimensions has its own primitives, and they appear nowhere
# else, so a gap computed rather than written is recognised by them.
DIMENSION_EXPRESSION = re.compile(r"\\(dimexpr|numexpr|glueexpr)\b")


def stringify_tex_item(obj: Any) -> str:
    """Extract a stable string from a plasTeX token/list item."""

    return getattr(obj, "source", getattr(obj, "textContent", str(obj))).strip()
