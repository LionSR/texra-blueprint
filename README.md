# texra-blueprint

Shared plasTeX plugin and site tooling for Lean 4 blueprint projects.
One installable home for the fixes and machinery that every
[leanblueprint](https://github.com/PatrickMassot/leanblueprint) project in the
family would otherwise carry as copies.

## What it provides

**A plasTeX plugin** (`texra_patches`) carrying the monkey patches a Lean
blueprint web build needs, with renderer templates:

- natbib: aux-file loading without spurious warnings; unresolved citations
  render their keys instead of empty parentheses (`TEXRA_FAIL_ON_CITATION_FALLBACK=1`
  turns the fallback into a hard error).
- leanblueprint: `\lean` declarations string-coerced, merged across multiple
  tags, and deduplicated in `lean_decls`.
- plastexdepgraph: `\uses`/`\alsoIn`/`\proves` label resolution deferred and
  hardened against plasTeX timing quirks, with a restricted (safe) unpickler
  for `.paux` files.
- plasTeX core: cross-reference keys survive underscores inside displays;
  a bracketed expression opening an array row is mathematics, not a length;
  a row break inside a braced argument stays inside it.
- Missing declarations: `\path`, `samepage`, the `mathtools` small matrices.

Each patch that fixes a plain upstream bug is an upstreaming candidate; this
package carries it until the fix lands upstream.

**A CLI** (`texra-blueprint`) for the paper-gap note apparatus: a published,
citable index of the notes recording where a formalization deviates from its
cited sources, and a CI check that every reference resolves and every note
name carries a registered source key.

## Use

```toml
# pyproject/requirements of your blueprint tooling, pinned by git tag:
# pip install "texra-blueprint @ git+https://github.com/texra-ai/texra-blueprint@v0.1.0"
```

`blueprint/src/plastex.cfg`:

```ini
[general]
plugins=plastexdepgraph  plastexshowmore  leanblueprint  texra_blueprint
```

`web.tex`: `\usepackage{texra_patches}` (after `blueprint`).

Repository root: a `texra-blueprint.toml` with a `[paper_gaps]` table — see
`fixture/texra-blueprint.toml` for a complete example. Then:

```bash
texra-blueprint paper-gaps check       # CI gate
texra-blueprint paper-gaps build       # latexmk over the notes
texra-blueprint paper-gaps site OUT    # index + PDFs + paper-gaps.bib
```

A project observing a specific mangled `\lean` name extends the repair map
from its own local package:

```python
from texra_blueprint.Packages.texra_patches import DECL_REPLACEMENTS
DECL_REPLACEMENTS["Mangled.name"] = "Correct.name"
```

## The fixture

`fixture/` is a minimal blueprint project exercising every patch; the test
suite renders it end to end. It doubles as the seed of the
oh-my-formalization starter kit.

## Version policy

The patches bind to private methods of the pinned plasTeX family
(`plasTeX==3.1`, `plastexdepgraph==0.0.5`, `leanblueprint==0.0.20`).
A version bump of any of them is a texra-blueprint release, tested against
the fixture — never an incidental upgrade in a consumer.
