r"""Per-chapter and subset dependency graphs.

Load with ``\usepackage{texra_graphs}`` after ``blueprint``.  The upstream
``plastexdepgraph`` package builds either one global dependency graph or
(with its ``dep_by`` option) per-section graphs — but not both, and it has
no notion of an arbitrary subset.  This package keeps the global graph and
adds further graph pages, configured from ``texra-blueprint.toml``::

    [blueprint.graphs]
    by_chapter = true      # one graph page per chapter
    boundary   = true      # include direct external dependencies (grayable
                           # context) in chapter graphs

    [blueprint.graphs.subsets]
    # the dependency cone of one result:
    ft = { ancestors_of = "thm:fundamental_theorem" }
    # or an explicit list of labels:
    core = { labels = ["thm:base_result", "thm:dependent_result"] }

Every added graph is an induced subgraph of the document graph and is
rendered by upstream's own pipeline (same template, colors, and modal
behavior), by registering the subgraphs before its pre-cleanup callback
runs.  Pages land as ``dep_graph_chapter_<n>.html`` and
``dep_graph_subset_<name>.html``.

Navigation: the table of contents gains a single ``Dependency graphs``
entry pointing at a generated chooser page (``dep_graphs.html``) that
lists every graph with its chapter title and node count, and each graph
page gets a selector injected after rendering, so the reader picks the
chapter to go into from anywhere.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
import html as _html
import re

from plastexdepgraph.Packages.depgraph import DepGraph
from plasTeX.Logging import getLogger
from plasTeX.PackageResource import PackagePreCleanupCB

log = getLogger()


def _load_graphs_config() -> dict:
    """The [blueprint.graphs] table of texra-blueprint.toml, searched upward."""
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        path = candidate / "texra-blueprint.toml"
        if path.exists():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            return data.get("blueprint", {}).get("graphs", {})
    return {}


def _induced(document, doc_graph: DepGraph, nodes: set, *,
             boundary: bool) -> DepGraph:
    """The subgraph of ``doc_graph`` induced by ``nodes``.

    With ``boundary``, the direct external dependencies of the set are
    included as context; ``to_dot`` then draws the crossing edges too.
    """
    if boundary:
        all_edges = doc_graph.edges | doc_graph.proof_edges
        nodes = nodes | {s for s, t in all_edges if t in nodes}
    graph = DepGraph()
    graph.document = document
    graph.nodes = set(nodes)
    graph.edges = {(s, t) for s, t in doc_graph.edges
                   if s in nodes and t in nodes}
    graph.proof_edges = {(s, t) for s, t in doc_graph.proof_edges
                         if s in nodes and t in nodes}
    return graph


class _SectionKey:
    """A stand-in accepted by upstream's renderer, which reads only
    ``sec.counter`` and ``sec.ref.textContent`` to name the output file.
    Hashable, since it keys the shared graphs dict."""

    class _Ref:
        def __init__(self, text: str):
            self.textContent = text

    def __init__(self, counter: str, name: str):
        self.counter = counter
        self.ref = self._Ref(name)


def _section_key(counter: str, name: str):
    return _SectionKey(counter, name)


def ProcessOptions(options, document):  # noqa: N802 (plasTeX hook name)
    config = _load_graphs_config()
    if not config:
        return

    def add_graphs() -> None:
        dep = document.userdata.get("dep_graph", {})
        graphs = dep.get("graphs", {})
        doc_graph = graphs.get(document)
        if doc_graph is None:
            log.warning(
                "texra_graphs: no document dependency graph found "
                "(is blueprint loaded with dep_graph, without dep_by?); "
                "skipping extra graphs")
            return
        toc = document.rendererdata["html5"].setdefault("extra_toc_items", [])
        boundary = bool(config.get("boundary", True))
        registry = document.userdata.setdefault("texra_graphs_registry", [])
        registry.append({"url": "dep_graph_document.html",
                         "label": "Full graph",
                         "count": len(doc_graph.nodes)})

        if config.get("by_chapter"):
            for chapter in document.getElementsByTagName("chapter"):
                nodes = {n for n in doc_graph.nodes
                         if chapter in _ancestry(n)}
                if not nodes:
                    continue
                number = chapter.ref.textContent if chapter.ref else "0"
                title = getattr(chapter, "title", None)
                title_text = (title.textContent.strip()
                              if title is not None else "")
                key = _section_key("chapter", number)
                graph = _induced(document, doc_graph, nodes,
                                 boundary=boundary)
                graphs[key] = graph
                registry.append({
                    "url": f"dep_graph_chapter_{number}.html",
                    "label": (f"Chapter {number} · {title_text}"
                              if title_text else f"Chapter {number}"),
                    "count": len(graph.nodes)})

        for name, spec in config.get("subsets", {}).items():
            nodes: set = set()
            if "ancestors_of" in spec:
                target = document.context.labels.get(spec["ancestors_of"])
                if target is None:
                    log.error("texra_graphs: subset %r: label %r not found",
                              name, spec["ancestors_of"])
                    continue
                nodes = doc_graph.ancestors(target) | {target}
            elif "labels" in spec:
                for label in spec["labels"]:
                    node = document.context.labels.get(label)
                    if node is None:
                        log.error("texra_graphs: subset %r: label %r not found",
                                  name, label)
                        continue
                    nodes.add(node)
            if not nodes:
                continue
            key = _section_key("subset", name)
            graph = _induced(document, doc_graph, nodes,
                             boundary=bool(spec.get("boundary", False)))
            graphs[key] = graph
            registry.append({
                "url": f"dep_graph_subset_{name}.html",
                "label": spec.get("title", f"{name} graph"),
                "count": len(graph.nodes)})

        toc.append({"text": "Dependency graphs", "url": "dep_graphs.html"})

    # Upstream builds its graphs at post-parse priority 110 and renders at
    # pre-cleanup; registering at 115 slots the extra graphs between the two.
    document.addPostParseCallbacks(115, add_graphs)

    # After upstream has rendered the graph pages (callbacks run in
    # registration order, and this package loads after blueprint), write the
    # chooser page and inject the selector into every graph page.
    cb = PackagePreCleanupCB(data=_write_navigation)
    document.addPackageResource([cb])


_SELECT_CSS = (
    '<div style="position:fixed;top:0;left:0;right:0;z-index:20;'
    'background:#f5f5f5;border-bottom:1px solid #ccc;padding:.35rem .8rem;'
    'font:14px sans-serif">Graph:&nbsp;<select style="max-width:70%" '
    'onchange="if(this.value)location=this.value">{options}</select></div>')


def _write_navigation(document):
    registry = document.userdata.get("texra_graphs_registry", [])
    if not registry:
        return []

    # The chooser page: every graph with its title and node count.
    rows = "\n".join(
        f'<li><a href="{g["url"]}">{_html.escape(g["label"])}</a> '
        f'<small>({g["count"]} nodes)</small></li>' for g in registry)
    chooser = (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Dependency graphs</title>"
        "<style>body{font:16px/1.6 sans-serif;max-width:40rem;margin:2rem auto;"
        "padding:0 1rem}small{color:#777}li{margin:.2rem 0}</style></head>"
        f"<body><h1>Dependency graphs</h1><ul>{rows}</ul></body></html>\n")
    Path("dep_graphs.html").write_text(chooser, encoding="utf-8")

    # The selector, injected into each rendered graph page.
    written = ["dep_graphs.html"]
    for g in registry:
        page = Path(g["url"])
        if not page.exists():
            continue
        options = '<option value="dep_graphs.html">all graphs…</option>' + "".join(
            f'<option value="{h["url"]}"'
            + (" selected" if h["url"] == g["url"] else "")
            + f'>{_html.escape(h["label"])}</option>' for h in registry)
        text = page.read_text(encoding="utf-8")
        text, n = re.subn(r"(<body[^>]*>)",
                          r"\1" + _SELECT_CSS.format(options=options),
                          text, count=1)
        if n:
            page.write_text(text, encoding="utf-8")
            written.append(g["url"])
    return written


def _ancestry(node):
    """The chain of parent nodes up to the document root."""
    while node is not None:
        yield node
        node = getattr(node, "parentNode", None)
