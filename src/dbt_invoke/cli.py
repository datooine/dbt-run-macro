"""Unix-friendly command line interface."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .api import _invoke


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="dbt-invoke", description="Compile a SQL-generating dbt package macro without a warehouse.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("macro", help="Unqualified macro name")
    parser.add_argument("package", help="Hub owner/package@version or a dbt dependency JSON object")
    parser.add_argument("adapter", help="Adapter name (bigquery in v0.1)")
    parser.add_argument("--args", default="{}", metavar="JSON", help="JSON object of named arguments")
    parser.add_argument("--template", type=Path, metavar="PATH", help="SQL/Jinja template file")
    parser.add_argument("--dry-run", action="store_true", help="Describe generated files without compiling")
    parser.add_argument("--no-cache", action="store_true", help="Resolve dependencies without using the cache")
    parser.add_argument("--keep-project", action="store_true", help="Retain and report the generated project")
    options = parser.parse_args(argv)
    try:
        arguments = json.loads(options.args)
        if not isinstance(arguments, dict):
            raise ValueError("--args must be a JSON object of named macro arguments")
        template = options.template.read_text(encoding="utf-8") if options.template else None
        sql = _invoke(
            options.macro, options.package, options.adapter, args=arguments, template=template,
            dry_run=options.dry_run, no_cache=options.no_cache, keep_project=options.keep_project,
        )
    except (ValueError, OSError) as exc:
        print(f"dbt-invoke: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"dbt-invoke: {exc}", file=sys.stderr)
        return 1
    if not options.dry_run:
        sys.stdout.write(sql)
    return 0
