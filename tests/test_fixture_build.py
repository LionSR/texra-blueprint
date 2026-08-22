"""End-to-end: plastex renders the fixture blueprint through the plugin."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixture"


@pytest.fixture(scope="module")
def built_site(tmp_path_factory):
    work = tmp_path_factory.mktemp("fixture-build")
    shutil.copytree(FIXTURE / "blueprint", work / "blueprint")
    shutil.copy2(FIXTURE / "texra-blueprint.toml", work / "texra-blueprint.toml")
    src = work / "blueprint" / "src"
    # Invoke plasTeX through the running interpreter so the build sees the
    # same environment the tests import texra_blueprint from (a bare
    # ``plastex`` on PATH may live in an unrelated pipx venv).
    result = subprocess.run(
        [sys.executable, "-c",
         "from plasTeX.client import plastex; plastex()",
         "--config", "plastex.cfg", "web.tex"],
        cwd=src, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    web = src.parent / "web"
    assert (web / "index.html").exists()
    text = "\n".join(p.read_text() for p in sorted(web.glob("*.html")))
    return web, text, result.stdout + result.stderr


def test_no_unrecognized_commands(built_site):
    _, _, log = built_site
    assert "unrecognized command/environment" not in log


def test_underscore_label_survives(built_site):
    _, text, _ = built_site
    assert "eq:comm_bracket" in text          # crossref catcode patch
    assert "??" not in text                    # every reference resolved


def test_path_and_lean_decls(built_site):
    web, text, _ = built_site
    assert 'class="path"' in text              # \path template
    assert "Fixture/Basic_file.lean" in text
    decls = (web.parent / "lean_decls").read_text().split()
    # duplicate \lean tag deduplicated by the leanblueprint digest patch
    assert decls == ["Fixture.baseResult", "Fixture.dependentResult"]


def test_commutator_row_not_a_length(built_site):
    _, text, _ = built_site
    assert "[P, Q]" in text.replace("&amp;", "&")


def test_unresolved_citation_fallback(built_site):
    _, text, _ = built_site
    # no web.bbl in the fixture: the natbib fallback patch renders the key
    # instead of empty parentheses
    assert "Model2020" in text


def test_chapter_and_subset_graphs(built_site):
    web, _, _ = built_site
    chapter = (web / "dep_graph_chapter_1.html")
    cone = (web / "dep_graph_subset_base_cone.html")
    assert chapter.exists() and cone.exists()
    cone_text = cone.read_text()
    assert "thm:base_result" in cone_text and "thm:dependent_result" in cone_text
    # the chooser page lists every graph with node counts, and the TOC links it
    chooser = (web / "dep_graphs.html").read_text()
    assert "Dependent-result cone" in chooser
    assert "Chapter 1" in chooser and "nodes)" in chooser
    assert "Dependency graphs" in (web / "index.html").read_text()
    # each graph page carries the injected selector
    assert "<select" in cone_text and "all graphs" in cone_text
