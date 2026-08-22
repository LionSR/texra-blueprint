"""CLI subcommands that need no texra-blueprint.toml: init and web."""

import sys

from texra_blueprint import web
from texra_blueprint.cli import main
from texra_blueprint.papergaps import SCAFFOLD_FILES


def test_init_scaffolds_the_three_files(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "paper-gaps", "init"]) == 0
    target = tmp_path / "docs" / "paper-gaps"
    for name in SCAFFOLD_FILES:
        assert (target / name).is_file()
    # The verdict machinery ships with the scaffold.
    assert r"\newcommand{\gapnote}[2]" in (target / "command.tex").read_text()
    assert r"\gapnote{<kind>}{<status>}" in (target / "policy.tex").read_text()
    assert r"\gapnote{unfaithful}{open}" in (target / "template.tex").read_text()
    # The scaffold is project-neutral: the reserved self-audit key is generic.
    policy = (target / "policy.tex").read_text()
    assert r"\path{self}" in policy
    assert "TNLean" not in policy


def test_init_keeps_modified_files_without_force(tmp_path, capsys):
    target = tmp_path / "notes"
    assert main(["paper-gaps", "init", "--dir", str(target)]) == 0
    (target / "command.tex").write_text("% local project notation\n")
    assert main(["paper-gaps", "init", "--dir", str(target)]) == 0
    assert (target / "command.tex").read_text() == "% local project notation\n"
    assert "kept existing" in capsys.readouterr().out
    assert main(["paper-gaps", "init", "--dir", str(target), "--force"]) == 0
    assert r"\gapnote" in (target / "command.tex").read_text()


def _stub_web(monkeypatch, *lines, exit_code=0):
    script = "".join(f"print({line!r})\n" for line in lines)
    script += f"raise SystemExit({exit_code})\n"
    monkeypatch.setattr(web, "WEB_COMMAND", (sys.executable, "-c", script))


def test_web_passes_on_clean_output(monkeypatch, capsys):
    _stub_web(monkeypatch, "Parsing document...", "Rendering... done")
    assert main(["web"]) == 0


def test_web_fails_on_unrecognized_environment(monkeypatch, capsys):
    _stub_web(monkeypatch,
              "WARNING: unrecognized environment: tikzcd (in web.tex)")
    assert main(["web"]) != 0
    assert "renderer failure" in capsys.readouterr().err


def test_web_fails_on_default_renderer_and_error_lines(monkeypatch, capsys):
    _stub_web(monkeypatch, "Using default renderer for thmenv")
    assert main(["web"]) != 0
    _stub_web(monkeypatch, "ERROR: could not resolve label lem:foo")
    assert main(["web"]) != 0
    # "ERROR:" is anchored to the line start; a mention mid-line is not a hit.
    _stub_web(monkeypatch, "checking for ERROR: markers... none")
    assert main(["web"]) == 0


def test_web_propagates_subprocess_failure(monkeypatch, capsys):
    _stub_web(monkeypatch, "boom", exit_code=3)
    assert main(["web"]) == 3


def test_web_streams_output_and_passes_args_through(monkeypatch, capsys):
    monkeypatch.setattr(
        web, "WEB_COMMAND",
        (sys.executable, "-c", "import sys; print(' '.join(sys.argv[1:]))"))
    assert main(["web", "--", "--verbose", "2"]) == 0
    assert "--verbose 2" in capsys.readouterr().out
