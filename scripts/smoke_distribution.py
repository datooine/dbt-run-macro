"""Verify an installed distribution from a working directory outside the source tree."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tiny_package"
    with tempfile.TemporaryDirectory(prefix="dbt-run-macro-installed-") as temporary:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        subprocess.run([
            sys.executable, "-c",
            "from importlib.metadata import distribution; import dbt_run_macro; "
            "package = distribution('dbt-run-macro'); "
            "assert package.metadata['Name'] == 'dbt-run-macro'; "
            "assert dbt_run_macro.__version__ == package.version; "
            "assert any(entry.name == 'dbt-run-macro' and entry.group == 'console_scripts' "
            "for entry in package.entry_points)",
        ], cwd=temporary, env=env, check=True)
        module = subprocess.run(
            [sys.executable, "-m", "dbt_run_macro", "--version"],
            cwd=temporary, env=env, capture_output=True, text=True, check=True,
        )
        if not module.stdout.startswith("dbt-run-macro "):
            raise RuntimeError(f"Unexpected module command version: {module.stdout}")
        console = Path(sys.executable).parent / (
            "dbt-run-macro.exe" if os.name == "nt" else "dbt-run-macro"
        )
        result = subprocess.run(
            [str(console), "no_args", json.dumps({"local": str(fixture)}), "bigquery"],
            cwd=temporary, env=env, capture_output=True, text=True, check=False,
        )
        if result.returncode or result.stdout.strip() != "SELECT 42 AS answer":
            raise RuntimeError(f"Installed CLI smoke test failed:\n{result.stderr}\n{result.stdout}")
        subprocess.run([
            sys.executable, "-c", "from dbt_run_macro import invoke; "
            f"assert invoke('no_args', {json.dumps(json.dumps({'local': str(fixture)}))}, "
            "'bigquery').strip() == 'SELECT 42 AS answer'",
        ], cwd=temporary, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    print("Installed CLI and Python API passed")


if __name__ == "__main__":
    main()
