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
``dep_graph_subset_<name>.html`` and are linked from the table of
contents.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from plastexdepgraph.Packages.depgraph import DepGraph
from plasTeX.Logging import getLogger

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

        if config.get("by_chapter"):
            for chapter in document.getElementsByTagName("chapter"):
                nodes = {n for n in doc_graph.nodes
                         if chapter in _ancestry(n)}
                if not nodes:
                    continue
                number = chapter.ref.textContent if chapter.ref else "0"
                key = _section_key("chapter", number)
                graphs[key] = _induced(document, doc_graph, nodes,
                                       boundary=boundary)
                toc.append({
                    "text": f"Chapter {number} graph",
                    "url": f"dep_graph_chapter_{number}.html"})

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
            graphs[key] = _induced(document, doc_graph, nodes,
                                   boundary=bool(spec.get("boundary", False)))
            toc.append({
                "text": spec.get("title", f"{name} graph"),
                "url": f"dep_graph_subset_{name}.html"})

    # Upstream builds its graphs at post-parse priority 110 and renders at
    # pre-cleanup; registering at 115 slots the extra graphs between the two.
    document.addPostParseCallbacks(115, add_graphs)


def _ancestry(node):
    """The chain of parent nodes up to the document root."""
    while node is not None:
        yield node
        node = getattr(node, "parentNode", None)
