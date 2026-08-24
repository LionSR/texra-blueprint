"""The bbl subcommand: byte-compatibility with the per-repo script it replaces.

The acceptance test runs the ported code and the original
``scripts/blueprint_bibtex.py`` (TNLean's canonical copy) against the same
real input — TNLean's ``references.bib`` plus a minimal blueprint citing
normal and paper-gap entries — and asserts identical output.  It is skipped
where the TNLean checkout is not available (CI of this repo).
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from texra_blueprint.cli import main

TNLEAN_ROOT = Path(__file__).resolve().parents[2] / "TNLean"
ORIGINAL_SCRIPT = TNLEAN_ROOT / "scripts" / "blueprint_bibtex.py"
REFERENCES_BIB = TNLEAN_ROOT / "blueprint" / "src" / "references.bib"

WEB_TEX = r"""
\documentclass{report}
\begin{document}
\input{chapter/intro}
\cite{Cirac2021Matrix} and \cite{PerezGarcia2007Matrix,Fannes1992Finitely}.
Gap notes: \cite{gap:cpgsv17_bicf_block_separation}
and \cite{gap:cpgsv17_vertical_cf_grouping}.
\bibliography{references}
\end{document}
"""

INTRO_TEX = r"""
A citation reached through \input: \cite{Wolf2012Quantum}.
% A commented-out citation must not be collected: \cite{Fannes1992Finitely,unknown}
"""


def _make_blueprint(tmp_path: Path) -> Path:
    src = tmp_path / "blueprint" / "src"
    (src / "chapter").mkdir(parents=True)
    shutil.copy(REFERENCES_BIB, src / "references.bib")
    (src / "web.tex").write_text(WEB_TEX, encoding="utf-8")
    (src / "chapter" / "intro.tex").write_text(INTRO_TEX, encoding="utf-8")
    return src


@pytest.fixture()
def blueprint_src(tmp_path):
    if not (ORIGINAL_SCRIPT.exists() and REFERENCES_BIB.exists()):
        pytest.skip("TNLean checkout with the original script not available")
    return _make_blueprint(tmp_path)


def test_bbl_matches_the_original_script_byte_for_byte(blueprint_src, capsys):
    bbl_path = blueprint_src / "web.bbl"

    proc = subprocess.run(
        [sys.executable, str(ORIGINAL_SCRIPT), "--src-dir", str(blueprint_src)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    original = bbl_path.read_bytes()
    bbl_path.unlink()

    root = blueprint_src.parents[1]
    assert main(["--root", str(root), "bbl"]) == 0
    assert bbl_path.read_bytes() == original


def test_bbl_labels_paper_gap_notes_by_slug(blueprint_src, capsys):
    root = blueprint_src.parents[1]
    assert main(["--root", str(root), "bbl"]) == 0
    bbl = (blueprint_src / "web.bbl").read_text(encoding="utf-8")
    # Gap entries carry their entry-key slug (underscores TeX-escaped) ...
    assert r"cpgsv17\_bicf\_block\_separation" in bbl
    assert r"cpgsv17\_vertical\_cf\_grouping" in bbl
    # ... not the degenerate contributor/year alpha label.
    assert "con26" not in bbl
    # Cited normal entries are present, including one reached through \input;
    # the commented-out citation contributed nothing.
    for key in ("Cirac2021Matrix", "PerezGarcia2007Matrix",
                "Fannes1992Finitely", "Wolf2012Quantum"):
        assert key in bbl
