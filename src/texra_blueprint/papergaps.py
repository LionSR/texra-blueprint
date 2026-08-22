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

import datetime
import html
import re
import shutil
import subprocess
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REF_RE = re.compile(r"paper-gaps/([A-Za-z0-9_\-]+)\.tex")

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
STATUSES = {"open", "resolved", "historical"}


def source_key(slug: str, sources: dict[str, str]) -> str | None:
    """The registered source key naming ``slug``, by longest-prefix match.

    A key matches when the slug is the key itself or continues it with an
    underscore or hyphen — so ``cpsv16_ft_gap``, ``issue-1234-divergence``
    (key ``issue``), and a full-stem key all resolve, whatever the
    separator convention.
    """
    best = None
    for key in sources:
        if slug == key or slug.startswith(key + "_") or slug.startswith(key + "-"):
            if best is None or len(key) > len(best):
                best = key
    return best


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
        path = root / "texra-blueprint.toml"
        if not path.exists():
            raise SystemExit(f"texra-blueprint.toml not found at {root}")
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        try:
            c = data["paper_gaps"]
        except KeyError:
            raise SystemExit("texra-blueprint.toml has no [paper_gaps] table")
        return cls(
            root=root,
            gaps=root / c.get("dir", "docs/paper-gaps"),
            site_base=c["site_base"].rstrip("/"),
            blob_base=c["blob_base"].rstrip("/"),
            bib_author=c.get("bib_author", "The contributors"),
            institution=c.get("institution", "the formalization"),
            title=c.get("title", "Paper-gap notes"),
            scan_roots=list(c.get("scan_roots", [])),
            skip=set(c.get("skip", ["command.tex", "template.tex"]))
            | {"references.bib"},
            policy=c.get("policy", "policy.tex"),
            sources=dict(c.get("sources", {})),
            require_verdict=bool(c.get("require_verdict", False)),
            aliases=dict(c.get("aliases", {})),
            group_aliases=dict(c.get("group_aliases", {})),
        )


# --------------------------------------------------------------------------
# TeX parsing


def _detex(s: str) -> str:
    """TeX title to plain text."""
    s = s.replace(r"\\", " ")
    s = re.sub(r"\\(?:path|texttt|leanid|emph|textit|textbf|textsc)\s*{([^{}]*)}", r"\1", s)
    s = re.sub(r"\\(?:text|mathrm|mathcal|mathbb)\s*{([^{}]*)}", r"\1", s)
    accents = {"'": "\u0301", "`": "\u0300", '"': "\u0308", "^": "\u0302", "~": "\u0303"}
    for mark, combining in accents.items():
        s = re.sub(
            r"\\" + re.escape(mark) + r"(?:{\\?([a-zA-Z])}|\\?([a-zA-Z]))",
            lambda m, c=combining: (m.group(1) or m.group(2)) + c, s)
    s = re.sub(r"\\(?:large|Large|small|footnotesize|normalsize)\b\s*", "", s)
    s = re.sub(r"\\mathcal\s*", "", s)
    s = s.replace(r"\eta", "\u03b7").replace(r"\S", "\u00a7")
    s = s.replace("---", "\u2014").replace("--", "\u2013").replace("~", "\u00a0")
    s = s.replace("\\&", "&").replace("\\_", "_").replace("\\%", "%")
    s = re.sub(r"(?<!\\)[{}$]", "", s)
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


def _git_date(cfg: Config, path: Path) -> str:
    out = subprocess.run(
        ["git", "log", "-1", "--format=%as", "--", str(path)],
        cwd=cfg.root, capture_output=True, text=True,
    ).stdout.strip()
    return out or "n.d."


@dataclass
class Note:
    slug: str
    title: str = ""
    date: str = ""
    citations: int = 0
    kind: str | None = None
    status: str | None = None

    @property
    def severity(self) -> str | None:
        return KIND_SEVERITY.get(self.kind or "")

    @property
    def live(self) -> bool:
        """A note that still names unresolved mathematical debt."""
        return self.status == "open"

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
    note.date = (
        _git_date(cfg, path) if "today" in raw_date or not raw_date
        else raw_date.strip()
    )
    m = GAPNOTE_RE.search(tex)
    if m:
        kind, status = m.group(1), m.group(2)
        if kind in KIND_SEVERITY:
            note.kind = kind
        if status in STATUSES:
            note.status = status
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
        for f in sorted(root.rglob("*")):
            if f.suffix not in {".lean", ".tex", ".md"} or f in seen or not f.is_file():
                continue
            seen.add(f)
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for slug in REF_RE.findall(text):
                if f.stem == slug:
                    continue
                counts[slug] += 1
                locations.setdefault(slug, set()).add(str(f.relative_to(cfg.root)))
    return counts, locations


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
    for p in sorted(cfg.gaps.glob("*.tex")):
        if p.name in cfg.skip or p.name == cfg.policy:
            continue
        key = source_key(p.stem, cfg.sources)
        if key is None or len(p.stem) <= len(key) + 1:
            print(f"::error::paper-gap note '{p.name}' is not named "
                  f"<key>_<topic>.tex with a registered source key and a "
                  f"nonempty topic (see [paper_gaps.sources] in "
                  f"texra-blueprint.toml)")
            failures += 1
        elif re.search(r"[_-]v\d+$", p.stem):
            print(f"::error::paper-gap note '{p.name}' carries a version "
                  f"suffix; notes are revised in place")
            failures += 1
    for old, new in sorted(cfg.aliases.items()):
        if new not in existing:
            print(f"::error::legacy alias '{old}' points at '{new}.tex', "
                  f"which does not exist")
            failures += 1
    untagged = []
    for p in sorted(cfg.gaps.glob("*.tex")):
        if p.name in cfg.skip or p.name == cfg.policy:
            continue
        note = parse_note(cfg, p)
        if note.kind is None or note.status is None:
            untagged.append(p.name)
    if untagged:
        msg = (f"{len(untagged)} notes lack a valid "
               f"\\gapnote{{kind}}{{status}} verdict marker")
        if cfg.require_verdict:
            print(f"::error::{msg}: " + ", ".join(untagged[:5])
                  + ("..." if len(untagged) > 5 else ""))
            failures += len(untagged)
        else:
            print(f"::warning::{msg}")
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


_SEV_ORDER = {"high": 0, "medium": 1, "low": 2, None: 3}


def _note_sort_key(n: Note):
    return (0 if n.live or n.status is None else 1,
            _SEV_ORDER.get(n.severity, 3), n.slug)


def _chips(n: Note) -> str:
    out = ""
    if n.kind:
        sev = n.severity or ""
        out += f' <span class="chip {sev}">{n.kind}</span>'
    if n.status and n.status != "open":
        out += f' <span class="chip">{n.status}</span>'
    return out


def build_site(cfg: Config, out: Path) -> None:
    notes = {
        p.stem: parse_note(cfg, p)
        for p in sorted(cfg.gaps.glob("*.tex"))
        if p.name not in cfg.skip and p.name != cfg.policy
    }
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
    (out / "paper-gaps.bib").write_text(
        "\n\n".join(notes[s].bibtex(cfg) for s in sorted(notes)) + "\n",
        encoding="utf-8")

    groups: dict[str, list[Note]] = {}
    for n in notes.values():
        key = source_key(n.slug, cfg.sources) or n.slug.split("_", 1)[0]
        groups.setdefault(cfg.group_aliases.get(key, key), []).append(n)
    ordered = sorted(groups, key=lambda g: (-len(groups[g]), g))

    rows = []
    for g in ordered:
        members = sorted(groups[g], key=_note_sort_key)
        keys = ", ".join(
            [g] + sorted(k for k, v in cfg.group_aliases.items() if v == g))
        heading = f"{keys} \u00b7 {cfg.sources[g]}" if g in cfg.sources else keys
        rows.append(f"<h2>{html.escape(heading)} <small>{len(members)}</small></h2>")
        rows.append("<table>")
        for n in members:
            cited = (f' <span class="n">\u00b7 cited \u00d7{n.citations}</span>'
                     if n.citations else "")
            row_class = (' class="settled"'
                         if n.status in ("resolved", "historical") else "")
            rows.append(
                f'<tr{row_class}><td class="date">{html.escape(n.date)}</td>'
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
    settled = [n for n in notes.values() if n.status in ("resolved", "historical")]
    untagged = [n for n in notes.values() if n.kind is None]
    summary = (f"{len(notes)} notes: {len(live)} open"
               + (f" ({len(high)} high-severity)" if high else "")
               + f", {len(settled)} resolved or historical"
               + (f", {len(untagged)} untagged" if untagged else "") + ".")
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(cfg.title)}</title>
<style>{STYLE}</style>
</head>
<body>
<h1>{html.escape(cfg.title)}</h1>
<p class="lede">Mathematical notes recording each discrepancy between a cited
source and the <a href="../">formal development</a>: missing hypotheses,
scalar corrections, scope restrictions, and replacement proof routes.
{html.escape(summary)} Grouped by source. {policy_line}Cite a note by its
permanent URL <code>{cfg.site_base}/paper-gaps/&lt;name&gt;.pdf</code> or via
<a href="paper-gaps.bib">paper-gaps.bib</a>.</p>
{''.join(rows)}
</body>
</html>
"""
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"paper-gaps site: {len(notes)} notes, {copied} PDFs, "
          f"{sum(n.citations for n in notes.values())} citations resolved")


def build_pdfs(cfg: Config) -> int:
    """Compile every note to PDF with latexmk (ex build-paper-gaps.sh)."""
    failures = 0
    for tex in sorted(cfg.gaps.glob("*.tex")):
        if tex.name in cfg.skip:
            continue
        result = subprocess.run(
            ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error",
             tex.name],
            cwd=cfg.gaps)
        if result.returncode != 0:
            print(f"::error::latexmk failed for {tex.name}")
            failures += 1
        subprocess.run(["latexmk", "-c", tex.name], cwd=cfg.gaps,
                       capture_output=True)
    return 1 if failures else 0
