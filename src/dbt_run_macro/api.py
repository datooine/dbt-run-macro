"""The public function and private CLI controls."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .adapters import runtime_versions
from .dependencies import parse_package
from .inputs import validate


def invoke(
    macro: str,
    package: str,
    adapter: str,
    *,
    args: dict | None = None,
    template: str | None = None,
) -> str:
    """Render a SQL-generating dbt macro, returning its compiled SQL.

    ``package`` accepts ``owner/package@version`` for dbt Hub or a JSON-encoded
    standard dbt dependency entry. ``template`` is source text, not a file path.
    Invalid inputs raise ValueError; dependency/compilation failures raise RuntimeError.
    dbt diagnostics are written to stderr. No warehouse credentials are required.
    """
    return _invoke(macro, package, adapter, args=args, template=template)


def _invoke(
    macro, package, adapter, *, args=None, template=None,
    dry_run=False, no_cache=False, keep_project=False,
) -> str:
    arguments = validate(macro, adapter, args, template)
    dependency = parse_package(package)
    versions = runtime_versions(adapter)
    workspace = Path(tempfile.mkdtemp(prefix="dbt-run-macro-"))
    try:
        request = workspace / ".dbt-run-macro-request.json"
        response = workspace / ".dbt-run-macro-response.json"
        request.write_text(json.dumps({
            "macro": macro, "package": dependency, "adapter": adapter, "args": arguments,
            "template": template, "dry_run": dry_run, "no_cache": no_cache,
            "versions": versions,
        }, allow_nan=False), encoding="utf-8")
        env = os.environ.copy()
        # Source imports and installed imports must execute the same copy of this package.
        source_root = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [source_root, env.get("PYTHONPATH")]))
        env.update(
            DBT_SEND_ANONYMOUS_USAGE_STATS="false", DBT_USE_COLORS="false",
            DBT_DOWNLOADS_DIR=str(workspace / ".downloads"),
            PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
        )
        try:
            process = subprocess.run(
                [sys.executable, "-m", "dbt_run_macro._worker", str(request), str(response)],
                cwd=workspace, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", check=False,
            )
        except OSError as exc:
            raise RuntimeError(f"Could not start the dbt worker: {exc}") from exc
        if process.stdout:
            sys.stderr.write(process.stdout)
        try:
            result = json.loads(response.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"dbt worker exited with status {process.returncode} without a valid result"
            ) from exc
        if "error" in result:
            error_type = ValueError if result.get("kind") == "validation" else RuntimeError
            raise error_type(result["error"])
        if process.returncode:
            raise RuntimeError(f"dbt worker exited with status {process.returncode}")
        return result["sql"]
    finally:
        if keep_project:
            print(f"Kept dbt project: {workspace}", file=sys.stderr)
        else:
            shutil.rmtree(workspace, ignore_errors=True)
