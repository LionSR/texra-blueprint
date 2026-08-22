"""Paper-gap notes: site index, BibTeX export, and reference checking.

A paper-gap note records a mathematical discrepancy between a cited source
and the formal development.  This module builds the published index of a
project's notes and enforces two invariants in CI: every repository
reference to a note resolves to an existing file (directly or through a
legacy alias), and every note's name is a registered source key followed
by a separator and a topic.

Configuration lives in ``texra-blueprint.toml`` at the repository root::

    [paper_gaps]
    dir        = "docs/paper-gaps"
    site_base  = "https://example.github.io/my-project"
    blob_base  = "https://github.com/example/my-project/blob/main/docs/paper-gaps"
    bib_author = "The {MyProject} contributors"
    institution = "MyProject"
    title      = "MyProject paper-gap notes"
    scan_roots = ["MyProject", "blueprint/src", "blueprint/comments", "docs"]
    skip       = ["command.tex", "template.tex"]  # machinery, not notes

    [paper_gaps.sources]           # the source-key registry
    cpsv16 = "arXiv:1606.00608 (matrix product density operators)"
    wolf   = "Wolf, Quantum Channels & Operations (2012 lecture notes)"
    self   = "internal theorem-surface audit, no single external source"

    [paper_gaps.group_aliases]     # fold a key into another key's index group
    cpgsv21 = "rmp"                # both keys stay registered and accepted

    [paper_gaps.aliases]           # slugs published before the registry
    old_deviation_note = "cpsv16_deviation_note"

``scan_roots`` lists the committed subtrees whose ``*.lean``, ``*.tex``,
and ``*.md`` files are scanned for note references; name built subtrees
individually (``blueprint/src``, ``blueprint/comments``) so local build
output under ``blueprint/web`` or ``blueprint/print`` stays out.  Each
``[paper_gaps.aliases]`` entry maps a slug published before the source-key
registry to the note that holds its content today: ``site`` serves the old
PDF URL as a copy of the target note, and ``check`` accepts references to
the old name while verifying that the target exists.  Keys listed in
``[paper_gaps.group_aliases]`` share their target key's heading on the
index page — one heading per source when two registered keys cite the
same source.

Subcommands (via ``texra-blueprint paper-gaps``): ``site OUT_DIR`` builds
the grouped index, copies the note PDFs, and writes ``paper-gaps.bib``;
``build`` compiles the notes to PDF with latexmk; ``check`` fails when a
referenced note is missing, when a note's name is not a registered source
key followed by a separator and a nonempty topic, when a note name carries
a version suffix (``_v2``/``-v2`` — notes are revised in place), or when a
legacy alias points at a note that does not exist, the way ``leanblueprint
checkdecls`` fails on an unresolved declaration.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import functools
import html
import os
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from texra_blueprint.config import load_table
from texra_blueprint.pages import html_page

# A note is referenced either by its repository path or by the blueprint's
# \gapref{<slug>} macro, which links the published PDF from the prose.
REF_RE = re.compile(
    r"paper-gaps/([A-Za-z0-9_\-]+)\.tex"
    r"|\\gapref\{([A-Za-z0-9_\-]+)\}")

# The verdict marker inside a note: \gapnote{<kind>}{<status>}.  Kind comes
# from the policy's classification; severity is derived from it, never a
# separately maintained field.  Status: open | resolved | historical.
GAPNOTE_RE = re.compile(r"\\gapnote\{([a-z\-]+)\}\{([a-z]+)\}")
KIND_SEVERITY = {
    "unfaithful": "high",
    "false-source": "high",
    "open-gap": "high",
    "scope-restriction": "medium",
    "local-correction": "medium",
    "clarification": "low",
}
SEVERITIES = ("high", "medium", "low")
_SEV_ORDER = {sev: rank for rank, sev in enumerate(SEVERITIES)}
LIVE_STATUSES = ("open", "wip")
SETTLED_STATUSES = ("resolved", "historical")
STATUSES = {*LIVE_STATUSES, *SETTLED_STATUSES}

_DATE_LINE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_VERSION_SUFFIX_RE = re.compile(r"[_-]v\d+$")


def source_key(slug: str, sources: dict[str, str]) -> str | None:
    """The registered source key naming ``slug``, by longest-prefix match.

    A key matches when the slug is the key itself or continues it with an
    underscore or hyphen — so ``cpsv16_ft_gap``, ``issue-1234-divergence``
    (key ``issue``), and a full-stem key all resolve, whatever the
    separator convention.
    """
    return max(
        (key for key in sources
         if slug == key or slug.startswith((key + "_", key + "-"))),
        key=len, default=None)


# --------------------------------------------------------------------------
# Configuration


@dataclass
class Config:
    root: Path
    gaps: Path
    site_base: str
    blob_base: str
    bib_author: str
    institution: str
    title: str
    scan_roots: list[str]
    skip: set[str]
    policy: str
    sources: dict[str, str]
    aliases: dict[str, str]
    group_aliases: dict[str, str]
    require_verdict: bool = False

    @classmethod
    def load(cls, root: Path) -> "Config":
        c = load_table(root, "paper_gaps", required=True)
        return cls(
            root=root,
            gaps=root / c.get("dir", "docs/paper-gaps"),
            site_base=c["site_base"].rstrip("/"),
            blob_base=c["blob_base"].rstrip("/"),
            bib_author=c.get("bib_author", "The contributors"),
            institution=c.get("institution", "the formalization"),
            title=c.get("title", "Paper-gap notes"),
            scan_roots=list(c.get("scan_roots", [])),
            skip=set(c.get("skip", ["command.tex", "template.tex"])),
            policy=c.get("policy", "policy.tex"),
            sources=dict(c.get("sources", {})),
            aliases=dict(c.get("aliases", {})),
            group_aliases=dict(c.get("group_aliases", {})),
            require_verdict=bool(c.get("require_verdict", False)),
        )

    def note_paths(self, include_policy: bool = False) -> list[Path]:
        """The note files, sorted, with the skip list and policy applied."""
        return [
            p for p in sorted(self.gaps.glob("*.tex"))
            if p.name not in self.skip
            and (include_policy or p.name != self.policy)
        ]

    @functools.cached_property
    def _note_dates(self) -> dict[str, str]:
        """Last-commit date per note file name, from one ``git log`` pass.

        ``git log`` lists commits newest first, so the first date printed
        above a file name is the file's last-modified date; ``setdefault``
        keeps that first occurrence.  Names are keyed by basename — the
        notes live in one directory — so the map is independent of where
        the repository root sits relative to ``self.root``.
        """
        out = subprocess.run(
            ["git", "log", "--format=%as", "--name-only", "--", str(self.gaps)],
            cwd=self.root, capture_output=True, text=True,
        ).stdout
        dates: dict[str, str] = {}
        current = ""
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            if _DATE_LINE_RE.fullmatch(line):
                current = line
            elif current:
                dates.setdefault(Path(line).name, current)
        return dates

    def git_date(self, path: Path) -> str:
        return self._note_dates.get(path.name, "n.d.")


# --------------------------------------------------------------------------
# TeX parsing


# One sweep for the font commands whose braced argument is kept; a bare
# ``\mathcal`` (no braces) is stripped by the same pattern with the
# argument group empty.
_FONT_ARG_RE = re.compile(
    r"\\(?:path|texttt|leanid|emph|textit|textbf|textsc)\s*{([^{}]*)}")
_MATH_FONT_ARG_RE = re.compile(
    r"\\(?:text|mathrm|mathbb)\s*{([^{}]*)}|\\mathcal\s*(?:{([^{}]*)})?")
_SIZE_RE = re.compile(r"\\(?:large|Large|small|footnotesize|normalsize)\b\s*")
_STRAY_BRACE_RE = re.compile(r"(?<!\\)[{}$]")
_ACCENTS = tuple(
    (re.compile(r"\\" + re.escape(mark) + r"(?:{\\?([a-zA-Z])}|\\?([a-zA-Z]))"),
     combining)
    for mark, combining in (
        ("'", "\u0301"), ("`", "\u0300"), ('"', "\u0308"),
        ("^", "\u0302"), ("~", "\u0303"),
    ))
# Plain replacements, applied in order: symbols, dashes and ties, escapes.
_SYMBOLS = {
    r"\eta": "\u03b7",
    r"\S": "\u00a7",
    "---": "\u2014",
    "--": "\u2013",
    "~": "\u00a0",
    "\\&": "&",
    "\\_": "_",
    "\\%": "%",
}


def _detex(s: str) -> str:
    """TeX title to plain text."""
    s = s.replace(r"\\", " ")
    s = _FONT_ARG_RE.sub(r"\1", s)
    s = _MATH_FONT_ARG_RE.sub(lambda m: m.group(1) or m.group(2) or "", s)
    for pattern, combining in _ACCENTS:
        s = pattern.sub(
            lambda m, c=combining: (m.group(1) or m.group(2)) + c, s)
    s = _SIZE_RE.sub("", s)
    for tex, plain in _SYMBOLS.items():
        s = s.replace(tex, plain)
    s = _STRAY_BRACE_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def _braced_arg(tex: str, command: str) -> str | None:
    """The (possibly nested-brace) argument of ``\\command{...}``."""
    m = re.search(r"\\" + command + r"\s*{", tex)
    if not m:
        return None
    depth, start = 1, m.end()
    for i in range(start, len(tex)):
        if tex[i] == "{" and tex[i - 1] != "\\":
            depth += 1
        elif tex[i] == "}" and tex[i - 1] != "\\":
            depth -= 1
            if depth == 0:
                return tex[start:i]
    return None


def _bib_escape(s: str) -> str:
    """Escape TeX-special characters for a printable BibTeX field."""
    return re.sub(r"([&%#_])", r"\\\1", s)


class Note:
    """One parsed note.

    ``kind`` and ``status`` hold the raw matched verdict-marker strings;
    validity against :data:`KIND_SEVERITY` and :data:`STATUSES` is judged
    where it matters (``check``), not at parse time.  The date is lazy:
    a note without an explicit ``\\date`` resolves it from the git history
    only when the date is actually read.
    """

    def __init__(self, slug: str, title: str = "", date: str = "",
                 citations: int = 0, kind: str | None = None,
                 status: str | None = None):
        self.slug = slug
        self.title = title
        self.citations = citations
        self.kind = kind
        self.status = status
        self._date = date
        self._date_source = None

    @property
    def date(self) -> str:
        if not self._date and self._date_source is not None:
            self._date = self._date_source()
        return self._date

    @date.setter
    def date(self, value: str) -> None:
        self._date = value

    @property
    def severity(self) -> str | None:
        return KIND_SEVERITY.get(self.kind)

    @property
    def live(self) -> bool:
        """A note that still names unresolved mathematical debt.

        ``open`` and ``wip`` are both live; ``wip`` marks a gap whose
        elimination is actively underway.
        """
        return self.status in LIVE_STATUSES

    @property
    def settled(self) -> bool:
        return self.status in SETTLED_STATUSES

    @property
    def year(self) -> str:
        m = re.match(r"(\d{4})", self.date)
        return m.group(1) if m else str(datetime.date.today().year)

    def bibtex(self, cfg: Config) -> str:
        title = _bib_escape(self.title.replace("\u2013", "--").replace("\u2014", "---"))
        return (
            f"@techreport{{gap:{self.slug},\n"
            f"  author      = {{{cfg.bib_author}}},\n"
            f"  title       = {{{title}}},\n"
            f"  institution = {{{cfg.institution}}},\n"
            f"  type        = {{Paper-gap note}},\n"
            f"  number      = {{{_bib_escape(self.slug)}}},\n"
            f"  year        = {{{self.year}}},\n"
            f"  url         = {{{cfg.site_base}/paper-gaps/{self.slug}.pdf}},\n"
            f"}}"
        )


def parse_note(cfg: Config, path: Path) -> Note:
    tex = path.read_text(encoding="utf-8")
    note = Note(slug=path.stem)
    raw_title = _braced_arg(tex, "title")
    note.title = _detex(raw_title) if raw_title else path.stem.replace("_", " ")
    raw_date = _braced_arg(tex, "date") or ""
    if raw_date and "today" not in raw_date:
        note.date = raw_date.strip()
    else:
        note._date_source = lambda: cfg.git_date(path)
    m = GAPNOTE_RE.search(tex)
    if m:
        note.kind, note.status = m.group(1), m.group(2)
    return note


# --------------------------------------------------------------------------
# Cross-reference scan


def scan_references(cfg: Config) -> tuple[Counter, dict[str, set[str]]]:
    """Reference counts per slug from the scan roots and the notes themselves."""
    counts: Counter = Counter()
    locations: dict[str, set[str]] = {}
    roots = [cfg.root / r for r in cfg.scan_roots] + [cfg.gaps]
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("*.lean", "*.tex", "*.md", "*.tsv"):
            for f in root.rglob(pattern):
                if f in seen or not f.is_file():
                    continue
                seen.add(f)
                try:
                    text = f.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for path_slug, gapref_slug in REF_RE.findall(text):
                    slug = path_slug or gapref_slug
                    if f.stem == slug:
                        continue
                    counts[slug] += 1
                    locations.setdefault(slug, set()).add(
                        str(f.relative_to(cfg.root)))
    return counts, locations


def _verdict_problem(note: Note) -> str | None:
    """Why ``note``'s verdict marker fails, or ``None`` when it is valid."""
    if note.kind is None:
        return "lacks a \\gapnote{kind}{status} verdict marker"
    if note.kind not in KIND_SEVERITY or note.status not in STATUSES:
        return (f"carries a verdict marker with unrecognized kind/status "
                f"\\gapnote{{{note.kind}}}{{{note.status}}}")
    return None


def check(cfg: Config) -> int:
    counts, locations = scan_references(cfg)
    existing = {p.stem for p in cfg.gaps.glob("*.tex")}
    # A reference to a legacy alias resolves through its target note.
    resolved = existing | {o for o, n in cfg.aliases.items() if n in existing}
    failures = 0
    for slug in sorted(set(counts) - resolved):
        where = ", ".join(sorted(locations.get(slug, []))[:3])
        print(f"::error::paper-gap note '{slug}.tex' is referenced "
              f"but does not exist ({where})")
        failures += 1

    # One pass over the notes: naming, version-suffix, and verdict rules.
    for p in cfg.note_paths():
        note = parse_note(cfg, p)
        key = source_key(p.stem, cfg.sources)
        if key is None or len(p.stem) <= len(key) + 1:
            print(f"::error::paper-gap note '{p.name}' is not named "
                  f"<key>_<topic>.tex with a registered source key and a "
                  f"nonempty topic (see [paper_gaps.sources] in "
                  f"texra-blueprint.toml)")
            failures += 1
        elif _VERSION_SUFFIX_RE.search(p.stem):
            print(f"::error::paper-gap note '{p.name}' carries a version "
                  f"suffix; notes are revised in place")
            failures += 1
        problem = _verdict_problem(note)
        if problem is not None:
            if cfg.require_verdict:
                print(f"::error::paper-gap note '{p.name}' {problem}")
                failures += 1
            else:
                print(f"::warning::paper-gap note '{p.name}' {problem}")

    # Configuration cross-references: alias targets must exist, and group
    # aliases must relate registered source keys.
    for old, new in sorted(cfg.aliases.items()):
        if new not in existing:
            print(f"::error::legacy alias '{old}' points at '{new}.tex', "
                  f"which does not exist")
            failures += 1
    for alias, target in sorted(cfg.group_aliases.items()):
        if alias not in cfg.sources:
            print(f"::error::group alias key '{alias}' is not a registered "
                  f"source key (see [paper_gaps.sources])")
            failures += 1
        if target not in cfg.sources:
            print(f"::error::group alias '{alias}' points at '{target}', "
                  f"which is not a registered source key")
            failures += 1

    if not failures:
        print(f"paper-gaps check: {len(counts)} referenced slugs resolve, "
              f"all note names carry registered source keys")
    return 1 if failures else 0


# --------------------------------------------------------------------------
# Site


STYLE = """
body { margin:2.5rem auto; max-width:46rem; padding:0 1rem; color:#222;
  font:16px/1.55 Georgia, "Times New Roman", serif; }
h1 { font-size:1.6rem; margin-bottom:.2rem; }
h2 { font-size:1.15rem; margin-top:2.2rem; border-bottom:1px solid #ddd;
  padding-bottom:.2rem; }
h2 small { font-weight:400; color:#777; font-size:.8rem; }
a { color:#1a5276; text-decoration:none; } a:hover { text-decoration:underline; }
p.lede, td.date, span.n { color:#777; }
table { border-collapse:collapse; width:100%; font-size:.95rem; }
td { padding:.3rem .5rem .3rem 0; vertical-align:top; }
td.date { white-space:nowrap; width:6.5rem; font-size:.85rem; }
span.n { font-size:.8rem; white-space:nowrap; }
span.chip { font-size:.72rem; border:1px solid #ccc; border-radius:.6rem;
  padding:0 .4rem; margin-left:.3rem; white-space:nowrap; color:#555; }
span.chip.high { color:#a33; border-color:#a33; }
span.chip.medium { color:#a60; border-color:#a60; }
tr.settled td, tr.settled a { opacity:.55; }
"""


def _note_sort_key(n: Note):
    return (0 if n.live or n.status is None else 1,
            _SEV_ORDER.get(n.severity, len(SEVERITIES)), n.slug)


def _chips(n: Note) -> str:
    out = ""
    if n.kind:
        sev = n.severity or ""
        out += f' <span class="chip {sev}">{n.kind}</span>'
    if n.status and n.status != "open":
        out += f' <span class="chip">{n.status}</span>'
    return out


def _group_table(cfg: Config, notes: dict[str, Note]) -> dict[str, tuple[str, list[Note]]]:
    """Group key -> (heading text, member notes), built in one pass.

    A slug is grouped under its registered source key (falling back to the
    slug itself for an unregistered name, which ``check`` reports), folded
    through ``group_aliases``; the heading lists the key with every alias
    folded into it, then the registered source description.
    """
    reverse_aliases: dict[str, list[str]] = {}
    for alias, target in cfg.group_aliases.items():
        reverse_aliases.setdefault(target, []).append(alias)
    groups: dict[str, tuple[str, list[Note]]] = {}
    for n in notes.values():
        key = source_key(n.slug, cfg.sources) or n.slug
        key = cfg.group_aliases.get(key, key)
        if key not in groups:
            keys = ", ".join([key] + sorted(reverse_aliases.get(key, [])))
            heading = (f"{keys} \u00b7 {cfg.sources[key]}"
                       if key in cfg.sources else keys)
            groups[key] = (heading, [])
        groups[key][1].append(n)
    return groups


def build_site(cfg: Config, out: Path) -> None:
    notes = {p.stem: parse_note(cfg, p) for p in cfg.note_paths()}
    counts, _ = scan_references(cfg)
    for slug, n in notes.items():
        n.citations = counts[slug]

    out.mkdir(parents=True, exist_ok=True)
    copied = 0
    policy_stem = Path(cfg.policy).stem
    for pdf in cfg.gaps.glob("*.pdf"):
        if pdf.stem in notes or pdf.stem == policy_stem:
            shutil.copy2(pdf, out / pdf.name)
            copied += 1
    # Old published URLs keep resolving: serve each pre-registry slug as a
    # copy of the note that holds its content today.
    for old, new in cfg.aliases.items():
        src = cfg.gaps / f"{new}.pdf"
        if src.exists():
            shutil.copy2(src, out / f"{old}.pdf")
            copied += 1
    (out / "paper-gaps.bib").write_text(
        "\n\n".join(notes[s].bibtex(cfg) for s in sorted(notes)) + "\n",
        encoding="utf-8")

    groups = _group_table(cfg, notes)
    ordered = sorted(groups, key=lambda g: (-len(groups[g][1]), g))

    rows = []
    for g in ordered:
        heading, members = groups[g]
        members = sorted(members, key=_note_sort_key)
        rows.append(f"<h2>{html.escape(heading)} <small>{len(members)}</small></h2>")
        rows.append("<table>")
        for n in members:
            cited = (f' <span class="n">\u00b7 cited \u00d7{n.citations}</span>'
                     if n.citations else "")
            row_class = ' class="settled"' if n.settled else ""
            # The date column shows the note's last git modification — the
            # staleness signal — while the authored \date feeds the BibTeX year.
            shown_date = cfg.git_date(cfg.gaps / f"{n.slug}.tex")
            if shown_date == "n.d.":
                shown_date = n.date
            rows.append(
                f'<tr{row_class}><td class="date">{html.escape(shown_date)}</td>'
                f'<td><a href="{n.slug}.pdf">{html.escape(n.title)}</a>{_chips(n)}{cited} '
                f'<span class="n">(<a href="{cfg.blob_base}/{n.slug}.tex">tex</a>)</span>'
                f"</td></tr>")
        rows.append("</table>")

    policy_line = ""
    if (cfg.gaps / cfg.policy).exists():
        policy_line = (
            f'The conventions are stated in the '
            f'<a href="{policy_stem}.pdf">policy note</a>. ')
    live = [n for n in notes.values() if n.live]
    high = [n for n in live if n.severity == "high"]
    wip = [n for n in live if n.status == "wip"]
    settled = [n for n in notes.values() if n.settled]
    untagged = [n for n in notes.values() if n.kind is None]
    summary = (f"{len(notes)} notes: {len(live)} open"
               + (f" ({len(high)} high-severity)" if high else "")
               + (f", {len(wip)} in progress" if wip else "")
               + f", {len(settled)} resolved or historical"
               + (f", {len(untagged)} untagged" if untagged else "") + ".")
    body = f"""<h1>{html.escape(cfg.title)}</h1>
<p class="lede">Mathematical notes recording each discrepancy between a cited
source and the <a href="../">formal development</a>: missing hypotheses,
scalar corrections, scope restrictions, and replacement proof routes.
{html.escape(summary)} Grouped by source. {policy_line}Cite a note by its
permanent URL <code>{cfg.site_base}/paper-gaps/&lt;name&gt;.pdf</code> or via
<a href="paper-gaps.bib">paper-gaps.bib</a>.</p>
{''.join(rows)}"""
    (out / "index.html").write_text(html_page(cfg.title, STYLE, body),
                                    encoding="utf-8")
    print(f"paper-gaps site: {len(notes)} notes, {copied} PDFs, "
          f"{sum(n.citations for n in notes.values())} citations resolved")


def build_pdfs(cfg: Config) -> int:
    """Compile every note to PDF with latexmk (ex build-paper-gaps.sh)."""
    # include_policy: the policy note is compiled and published like a note.
    texs = cfg.note_paths(include_policy=True)

    def compile_one(tex: Path) -> int:
        return subprocess.run(
            ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error",
             tex.name],
            cwd=cfg.gaps).returncode

    # latexmk is subprocess-bound: run the notes in parallel.
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=os.cpu_count()) as pool:
        returncodes = list(pool.map(compile_one, texs))
    failures = 0
    for tex, returncode in zip(texs, returncodes):
        if returncode != 0:
            print(f"::error::latexmk failed for {tex.name}")
            failures += 1
    if texs:
        subprocess.run(["latexmk", "-c", *[tex.name for tex in texs]],
                       cwd=cfg.gaps, capture_output=True)
    return 1 if failures else 0
