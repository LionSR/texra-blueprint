from pathlib import Path

from texra_blueprint.papergaps import Config, build_site, check, parse_note

FIXTURE = Path(__file__).parent.parent / "fixture"


def test_check_passes_on_fixture(capsys):
    cfg = Config.load(FIXTURE)
    assert check(cfg) == 0
    assert "1 referenced slugs resolve" in capsys.readouterr().out


def test_check_fails_on_unregistered_key(tmp_path, capsys):
    import shutil
    shutil.copytree(FIXTURE, tmp_path / "repo")
    bad = tmp_path / "repo" / "docs" / "paper-gaps" / "unknownkey_note.tex"
    bad.write_text("\\title{Bad}\n")
    assert check(Config.load(tmp_path / "repo")) == 1
    assert "registered source key" in capsys.readouterr().out


def test_check_fails_on_dangling_reference(tmp_path, capsys):
    import shutil
    shutil.copytree(FIXTURE, tmp_path / "repo")
    tex = tmp_path / "repo" / "blueprint" / "src" / "web.tex"
    tex.write_text(tex.read_text() + "\n% docs/paper-gaps/demo_missing_note.tex\n")
    assert check(Config.load(tmp_path / "repo")) == 1
    assert "does not exist" in capsys.readouterr().out


def test_site_and_bib(tmp_path):
    cfg = Config.load(FIXTURE)
    build_site(cfg, tmp_path / "out")
    index = (tmp_path / "out" / "index.html").read_text()
    assert "A Model Scope Restriction" in index
    assert "demo · arXiv:0000.00000" in index
    bib = (tmp_path / "out" / "paper-gaps.bib").read_text()
    assert "@techreport{gap:demo_scope_restriction," in bib
    assert "url         = {https://example.github.io/fixture/paper-gaps/demo_scope_restriction.pdf}" in bib


def test_title_detex():
    cfg = Config.load(FIXTURE)
    note = parse_note(cfg, cfg.gaps / "demo_scope_restriction.tex")
    assert note.title == "A Model Scope Restriction"
    assert note.date == "2026-08-22"


def test_source_key_separator_agnostic():
    from texra_blueprint.papergaps import source_key
    sources = {"issue": "", "naimark": "", "cpsv16": "", "truncation-combinatorics": ""}
    assert source_key("issue-1234-divergence", sources) == "issue"
    assert source_key("naimark", sources) == "naimark"
    assert source_key("cpsv16_ft_gap", sources) == "cpsv16"
    assert source_key("truncation-combinatorics-f-nonneg", sources) == "truncation-combinatorics"
    assert source_key("unregistered_note", sources) is None
