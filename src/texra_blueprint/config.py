"""Configuration discovery for texra-blueprint.

Every subsystem reads its table from one ``texra-blueprint.toml`` at the
repository root.  This module owns the two halves of that lookup: finding
the root (:func:`find_root`, an upward search from a starting directory)
and reading one table out of the file (:func:`load_table`).  Whether a
missing file or table is an error is the caller's choice, made explicit
through ``required``: the paper-gaps command line refuses to run without
its table, while the plasTeX packages treat an absent table as "feature
not configured".

The parse is cached per resolved path, so the packages and the command
line reading the same file within one process parse it once.
"""

from __future__ import annotations

import functools
import tomllib
from pathlib import Path

CONFIG_NAME = "texra-blueprint.toml"


@functools.lru_cache(maxsize=None)
def _parse(path: Path, mtime_ns: int) -> dict:
    """The parsed TOML document at ``path`` (a resolved path), cached.

    The modification time takes part in the key so a rewritten file is
    reparsed rather than served stale within one process.
    """
    return tomllib.loads(path.read_text(encoding="utf-8"))


def find_root(start: Path | None = None) -> Path | None:
    """The nearest directory at or above ``start`` holding the config file.

    ``start`` defaults to the current working directory.  Returns ``None``
    when no ``texra-blueprint.toml`` is found on the way up.
    """
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / CONFIG_NAME).exists():
            return candidate
    return None


def load_table(root: Path, dotted_key: str, *, required: bool) -> dict:
    """The table under ``dotted_key`` in ``root``'s ``texra-blueprint.toml``.

    With ``required``, a missing file or table is a :class:`SystemExit`;
    without it, both yield ``{}``.
    """
    path = root / CONFIG_NAME
    if not path.exists():
        if required:
            raise SystemExit(f"{CONFIG_NAME} not found at {root}")
        return {}
    resolved = path.resolve()
    table = _parse(resolved, resolved.stat().st_mtime_ns)
    for part in dotted_key.split("."):
        table = table.get(part) if isinstance(table, dict) else None
        if table is None:
            if required:
                raise SystemExit(f"{CONFIG_NAME} has no [{dotted_key}] table")
            return {}
    return table
