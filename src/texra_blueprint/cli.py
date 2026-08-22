"""Command line entry point for texra-blueprint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from texra_blueprint import __version__, papergaps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="texra-blueprint",
        description="Shared tooling for Lean blueprint projects.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(),
        help="repository root holding texra-blueprint.toml (default: cwd)")
    sub = parser.add_subparsers(required=True)

    pg = sub.add_parser("paper-gaps", help="paper-gap note machinery")
    pg_sub = pg.add_subparsers(dest="pg_command", required=True)
    site = pg_sub.add_parser("site", help="build the published index and bib")
    site.add_argument("out_dir", type=Path)
    pg_sub.add_parser("check", help="verify references and source keys")
    pg_sub.add_parser("build", help="compile the notes to PDF with latexmk")

    args = parser.parse_args(argv)
    cfg = papergaps.Config.load(args.root.resolve())

    if args.pg_command == "site":
        papergaps.build_site(cfg, args.out_dir.resolve())
        return 0
    if args.pg_command == "check":
        return papergaps.check(cfg)
    return papergaps.build_pdfs(cfg)


if __name__ == "__main__":
    sys.exit(main())
