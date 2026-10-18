"""CLI: `stretchserve serve [dir]` and `stretchserve check [dir]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .scanner import validate
from .server import main as serve_main


def _check(directory: Path) -> int:
    files = sorted(directory.rglob("*.md"))
    failures = 0
    for file in files:
        text = file.read_text(encoding="utf-8", errors="replace")
        issues = validate(text)
        rel = file.relative_to(directory) if file.is_relative_to(directory) else file
        for issue in issues:
            print(f"{rel}:{issue['line']}: {issue['severity']}: {issue['message']}"
                  + (f" [{issue['key']}]" if issue.get("key") else ""))
            if issue["severity"] == "error":
                failures += 1
    print(f"checked {len(files)} files, {failures} errors")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="stretchserve")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="serve a directory of markdown")
    p_serve.add_argument("directory", nargs="?", default=".", type=Path)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8377)

    p_check = sub.add_parser("check", help="validate stretch markup in .md files")
    p_check.add_argument("directory", nargs="?", default=".", type=Path)

    p_mcp = sub.add_parser("mcp", help="run the MCP server (stdio)")
    p_mcp.add_argument("directory", nargs="?", default=".", type=Path)
    p_mcp.add_argument("--gzero", action="store_true",
                       help="serve the gzero atom store + workflow doc read-only "
                            "(directory sets the project scope; mutations stay with gzero)")

    args = parser.parse_args(argv)
    if args.command == "serve":
        serve_main([str(args.directory), "--host", args.host, "--port", str(args.port)])
    elif args.command == "check":
        sys.exit(_check(args.directory))
    elif args.command == "mcp":
        from .mcp_server import run

        run(args.directory, gzero=args.gzero)


if __name__ == "__main__":
    main()
