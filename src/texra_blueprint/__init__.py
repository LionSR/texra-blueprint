"""texra-blueprint: shared plasTeX plugin and site tooling for Lean blueprints.

Load the plasTeX layer by listing ``texra_blueprint`` in ``plastex.cfg``::

    [general]
    plugins=plastexdepgraph  plastexshowmore  leanblueprint  texra_blueprint

and adding ``\\usepackage{texra_patches}`` to the web document.  The command
line tool ``texra-blueprint`` serves the paper-gaps site machinery.
"""

__version__ = "0.2.1"
