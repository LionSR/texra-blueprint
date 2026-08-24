"""Command line entry point for texra-blueprint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from texra_blueprint import __version__, papergaps, web


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="texra-blueprint",
        description="Shared tooling for Lean blueprint projects.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(),
        help="repository root holding texra-blueprint.toml (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    pg = sub.add_parser("paper-gaps", help="paper-gap note machinery")
    pg_sub = pg.add_subparsers(dest="pg_command", required=True)
    site = pg_sub.add_parser("site", help="build the published index and bib")
    site.add_argument("out_dir", type=Path)
    pg_sub.add_parser("check", help="verify references and source keys")
    pg_sub.add_parser("build", help="compile the notes to PDF with latexmk")
    init = pg_sub.add_parser(
        "init", help="copy the canonical scaffold (command.tex, policy.tex, "
        "template.tex) into a notes directory")
    init.add_argument(
        "--dir", type=Path, default=Path("docs/paper-gaps"),
        help="target directory, resolved against --root when relative "
        "(default: docs/paper-gaps)")
    init.add_argument(
        "--force", action="store_true", help="overwrite existing files")

    bblp = sub.add_parser(
        "bbl", help="generate the blueprint .bbl for plasTeX from \\cite keys")
    bblp.add_argument(
        "--src-dir", type=Path, default=Path("blueprint/src"),
        help="blueprint TeX source directory, resolved against --root when "
        "relative (default: blueprint/src)")
    bblp.add_argument("--tex", default="web.tex")
    bblp.add_argument("--default-style", default="alpha")
    bblp.add_argument(
        "--keys", help="Comma-separated citation keys, or '*' for all entries.")

    webp = sub.add_parser(
        "web", help="leanblueprint web with a strict renderer-failure gate")
    webp.add_argument(
        "web_args", nargs=argparse.REMAINDER, metavar="-- ARGS",
        help="arguments passed through to leanblueprint web")

    args = parser.parse_args(argv)

    if args.command == "bbl":
        # Imported here so the pybtex requirement only binds this subcommand.
        from texra_blueprint import bbl
        src_dir = args.src_dir if args.src_dir.is_absolute() \
            else args.root.resolve() / args.src_dir
        return bbl.run(src_dir, tex=args.tex,
                       default_style=args.default_style, keys=args.keys)

    if args.command == "web":
        extra = args.web_args
        if extra and extra[0] == "--":
            extra = extra[1:]
        return web.run_web(extra)

    if args.pg_command == "init":
        target = args.dir if args.dir.is_absolute() \
            else args.root.resolve() / args.dir
        return papergaps.init_scaffold(target, force=args.force)

    cfg = papergaps.Config.load(args.root.resolve())

    if args.pg_command == "site":
        papergaps.build_site(cfg, args.out_dir.resolve())
        return 0
    if args.pg_command == "check":
        return papergaps.check(cfg)
    return papergaps.build_pdfs(cfg)


if __name__ == "__main__":
    sys.exit(main())
