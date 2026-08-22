"""The HTML page skeleton shared by every generated texra-blueprint page.

The paper-gaps index and the dependency-graph chooser each carry their own
style; the doctype, charset, viewport, and title plumbing they share lives
here once.
"""

from __future__ import annotations

import html


def html_page(title: str, style: str, body: str) -> str:
    """A complete HTML page around ``body``.

    ``title`` is escaped here; ``style`` and ``body`` are emitted as given,
    so any text inside ``body`` must arrive already escaped.
    """
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{style}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )
