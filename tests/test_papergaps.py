import shutil
import subprocess
from pathlib import Path

import pytest

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


# --------------------------------------------------------------------------
# Review-hardening behaviors ported from TNLean #6879 (commit 3fdec4404)


def _copy_fixture(tmp_path):
    import shutil
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    return root


def _append_toml(root, text):
    toml = root / "texra-blueprint.toml"
    toml.write_text(toml.read_text() + text)


def test_bibtex_escapes_tex_specials(tmp_path):
    root = _copy_fixture(tmp_path)
    note = root / "docs" / "paper-gaps" / "demo_rank_bounds.tex"
    note.write_text(
        "\\title{Trace \\& #4 of 5\\% rank\\_bounds}\n\\date{2026-08-22}\n")
    cfg = Config.load(root)
    entry = parse_note(cfg, note).bibtex(cfg)
    assert "title       = {Trace \\& \\#4 of 5\\% rank\\_bounds}" in entry
    assert "number      = {demo\\_rank\\_bounds}" in entry
    # URLs stay unescaped so the link keeps resolving.
    assert "url         = {https://example.github.io/fixture/paper-gaps/demo_rank_bounds.pdf}" in entry


def _build_unicode_note_site(tmp_path):
    """A fixture copy with a Greek-and-accents note, site built into out/."""
    root = _copy_fixture(tmp_path)
    note = root / "docs" / "paper-gaps" / "demo_eta_threshold.tex"
    note.write_text(
        "\\title{Top index of $T_\\eta$ \\`a la Schr\\\"odinger, \\S3}\n"
        "\\date{2026-08-22}\n")
    out = tmp_path / "out"
    build_site(Config.load(root), out)
    return out


def test_bib_unicode_folds_back_to_tex(tmp_path):
    # Regression for issue #1: _detex expands \eta, \S, and accent commands
    # to raw Unicode, which must not reach the emitted .bib fields.
    out = _build_unicode_note_site(tmp_path)
    bib = (out / "paper-gaps.bib").read_text()
    assert bib.isascii(), "generated .bib contains raw non-ASCII"
    assert "T\\_{\\ensuremath{\\eta}}" in bib
    assert "{\\`{a}}" in bib
    assert '{\\"{o}}' in bib
    assert "{\\S}3" in bib


def test_bib_roundtrips_through_classic_bibtex(tmp_path):
    if shutil.which("bibtex") is None:
        pytest.skip("bibtex not installed; ASCII-safety still covered by "
                    "test_bib_unicode_folds_back_to_tex")
    out = _build_unicode_note_site(tmp_path)
    (out / "cite.aux").write_text(
        "\\citation{gap:demo_eta_threshold}\n"
        "\\bibstyle{alpha}\n"
        "\\bibdata{paper-gaps}\n")
    proc = subprocess.run(
        ["bibtex", "cite"], cwd=out, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    bbl = (out / "cite.bbl").read_text()
    assert "\\ensuremath{\\eta}" in bbl


def test_year_falls_back_to_build_date():
    import datetime
    from texra_blueprint.papergaps import Note
    assert Note(slug="x", date="n.d.").year == str(datetime.date.today().year)
    assert Note(slug="x", date="2024-01-05").year == "2024"


def test_site_serves_legacy_alias_pdfs(tmp_path):
    root = _copy_fixture(tmp_path)
    _append_toml(root, '\n[paper_gaps.aliases]\nold_local_fix = "demo_local_fix"\n')
    (root / "docs" / "paper-gaps" / "demo_local_fix.pdf").write_bytes(b"%PDF-fake")
    build_site(Config.load(root), tmp_path / "out")
    assert (tmp_path / "out" / "old_local_fix.pdf").read_bytes() == b"%PDF-fake"


def test_check_accepts_alias_references(tmp_path, capsys):
    root = _copy_fixture(tmp_path)
    _append_toml(root, '\n[paper_gaps.aliases]\nold_local_fix = "demo_local_fix"\n')
    tex = root / "blueprint" / "src" / "web.tex"
    tex.write_text(tex.read_text() + "\n% docs/paper-gaps/old_local_fix.tex\n")
    assert check(Config.load(root)) == 0
    assert "referenced slugs resolve" in capsys.readouterr().out


def test_check_fails_on_dangling_alias_target(tmp_path, capsys):
    root = _copy_fixture(tmp_path)
    _append_toml(root, '\n[paper_gaps.aliases]\nold_gone = "demo_never_written"\n')
    assert check(Config.load(root)) == 1
    out = capsys.readouterr().out
    assert "legacy alias 'old_gone' points at 'demo_never_written.tex'" in out


def test_scan_covers_markdown_docs(tmp_path):
    from texra_blueprint.papergaps import scan_references
    root = _copy_fixture(tmp_path)
    toml = root / "texra-blueprint.toml"
    toml.write_text(toml.read_text().replace(
        'scan_roots = ["blueprint/src"]',
        'scan_roots = ["blueprint/src", "docs"]'))
    (root / "docs" / "ledger.md").write_text(
        "The deviation is recorded in docs/paper-gaps/demo_local_fix.tex.\n")
    counts, locations = scan_references(Config.load(root))
    assert counts["demo_local_fix"] == 1
    assert locations["demo_local_fix"] == {"docs/ledger.md"}
    assert check(Config.load(root)) == 0


def test_singleton_group_keeps_registry_heading(tmp_path):
    root = _copy_fixture(tmp_path)
    (root / "docs" / "paper-gaps" / "self_audit_surface.tex").write_text(
        "\\title{An Audit Surface}\n\\date{2026-08-22}\n")
    build_site(Config.load(root), tmp_path / "out")
    index = (tmp_path / "out" / "index.html").read_text()
    assert "self · internal theorem-surface audit" in index
    assert "Miscellaneous" not in index


def test_group_alias_merges_headings(tmp_path):
    root = _copy_fixture(tmp_path)
    _append_toml(root, '''
[paper_gaps.group_aliases]
demo2 = "demo"
''')
    toml = root / "texra-blueprint.toml"
    toml.write_text(toml.read_text().replace(
        '[paper_gaps.sources]\ndemo = "arXiv:0000.00000 (a model source)"',
        '[paper_gaps.sources]\ndemo = "arXiv:0000.00000 (a model source)"\n'
        'demo2 = "arXiv:0000.00000 (a model source)"'))
    (root / "docs" / "paper-gaps" / "demo2_extra_gap.tex").write_text(
        "\\title{An Extra Gap}\n\\date{2026-08-22}\n")
    build_site(Config.load(root), tmp_path / "out")
    index = (tmp_path / "out" / "index.html").read_text()
    assert "demo, demo2 · arXiv:0000.00000 (a model source)" in index
    assert "<h2>demo2" not in index
    assert "An Extra Gap" in index
    assert check(Config.load(root)) == 0


def test_check_rejects_bare_key_name(tmp_path, capsys):
    root = _copy_fixture(tmp_path)
    (root / "docs" / "paper-gaps" / "demo.tex").write_text("\\title{Bare}\n")
    assert check(Config.load(root)) == 1
    assert "nonempty topic" in capsys.readouterr().out


def test_check_rejects_version_suffix(tmp_path, capsys):
    root = _copy_fixture(tmp_path)
    gaps = root / "docs" / "paper-gaps"
    (gaps / "demo_extra_note_v2.tex").write_text("\\title{V2}\n")
    (gaps / "demo_other-v3.tex").write_text("\\title{V3}\n")
    assert check(Config.load(root)) == 1
    out = capsys.readouterr().out
    assert out.count("carries a version suffix") == 2


def test_gapnote_verdict_parsing():
    cfg = Config.load(FIXTURE)
    open_note = parse_note(cfg, cfg.gaps / "demo_scope_restriction.tex")
    assert (open_note.kind, open_note.status, open_note.severity) == (
        "scope-restriction", "open", "medium")
    assert open_note.live
    resolved = parse_note(cfg, cfg.gaps / "demo_local_fix.tex")
    assert resolved.status == "resolved" and not resolved.live


def test_index_shows_severity_and_summary(tmp_path):
    cfg = Config.load(FIXTURE)
    build_site(cfg, tmp_path / "out")
    index = (tmp_path / "out" / "index.html").read_text()
    assert "1 open" in index and "1 resolved or historical" in index
    assert 'class="chip medium">scope-restriction' in index
    assert 'class="settled"' in index


def test_check_require_verdict(tmp_path, capsys):
    import shutil
    from texra_blueprint.papergaps import check
    shutil.copytree(FIXTURE, tmp_path / "repo")
    toml = tmp_path / "repo" / "texra-blueprint.toml"
    toml.write_text(toml.read_text().replace(
        "[paper_gaps]", "[paper_gaps]\nrequire_verdict = true"))
    untagged = tmp_path / "repo" / "docs" / "paper-gaps" / "demo_untagged_note.tex"
    untagged.write_text("\\title{Untagged}\n\\date{2026-08-22}\n")
    assert check(Config.load(tmp_path / "repo")) == 1
    assert "verdict marker" in capsys.readouterr().out


def test_wip_status_is_live():
    from texra_blueprint.papergaps import Note
    n = Note("demo_x", kind="open-gap", status="wip")
    assert n.live and not n.settled


def test_index_shows_git_modified_date(tmp_path):
    cfg = Config.load(FIXTURE)
    build_site(cfg, tmp_path / "out")
    index = (tmp_path / "out" / "index.html").read_text()
    # the fixture notes' authored \date is 2026-08-22; the git-modified date
    # of the scope-restriction note (last touched when its verdict marker
    # landed) is what the column shows
    expected = cfg.git_date(cfg.gaps / "demo_scope_restriction.tex")
    assert expected != "n.d." and expected in index


def test_gapref_references_are_scanned(tmp_path):
    import shutil
    from texra_blueprint.papergaps import check, scan_references
    shutil.copytree(FIXTURE, tmp_path / "repo")
    ch = tmp_path / "repo" / "blueprint" / "src" / "web.tex"
    text = ch.read_text().replace(
        "\\path{docs/paper-gaps/demo_scope_restriction.tex}",
        "\\gapref{demo_scope_restriction}")
    ch.write_text(text)
    cfg = Config.load(tmp_path / "repo")
    counts, _ = scan_references(cfg)
    assert counts["demo_scope_restriction"] >= 1
    assert check(cfg) == 0
    # a gapref to a missing note fails check
    ch.write_text(text + "\n% \\gapref{demo_missing_note}\n")
    assert check(cfg) == 1
