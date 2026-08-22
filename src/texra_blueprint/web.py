"""Strict ``leanblueprint web``: fail the build on renderer fallbacks.

plasTeX exits zero even when it silently degrades — an unrecognized command
or environment, a node rendered by the default renderer, or a logged error
all produce a "successful" build whose pages are wrong.  ``texra-blueprint
web`` runs ``leanblueprint web``, streams its combined output, and exits
nonzero when any line matches the failure vocabulary below, so CI gates on
renderer health instead of duplicating a grep pipeline per workflow.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Sequence

# The canonical renderer-failure vocabulary for a blueprint web build.
# Consumers' workflows gate on this list via `texra-blueprint web` instead
# of carrying their own (already diverged) grep patterns.  Each pattern is
# matched against a single output line.
RENDER_FAILURE_PATTERNS = (
    r"WARNING: unrecognized (command|environment)",
    r"Using default renderer",
    r"^ERROR:",
)

_FAILURE_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in RENDER_FAILURE_PATTERNS))

# The invocation wrapped by run_web; module-level so tests can substitute a
# stub that emits canned output.
WEB_COMMAND = ("leanblueprint", "web")


def run_web(extra_args: Sequence[str] = ()) -> int:
    """Run ``leanblueprint web`` and gate on the failure vocabulary.

    Streams the combined stdout/stderr while capturing it.  Returns the
    subprocess's exit code if nonzero; otherwise 1 when any output line
    matches ``RENDER_FAILURE_PATTERNS``, else 0.
    """
    process = subprocess.Popen(
        [*WEB_COMMAND, *extra_args],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace")
    assert process.stdout is not None
    failures: list[str] = []
    for line in process.stdout:
        sys.stdout.write(line)
        if _FAILURE_RE.search(line):
            failures.append(line.rstrip("\n"))
    returncode = process.wait()
    if returncode != 0:
        print(f"texra-blueprint web: leanblueprint web exited {returncode}",
              file=sys.stderr)
        return returncode
    if failures:
        print(f"texra-blueprint web: {len(failures)} renderer failure(s):",
              file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1
    return 0
