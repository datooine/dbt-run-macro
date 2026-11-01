"""Verify an installed distribution from a working directory outside the source tree."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tiny_package"
    with tempfile.TemporaryDirectory(prefix="dbt-invoke-installed-") as temporary:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "-m", "dbt_invoke", "no_args", json.dumps({"local": str(fixture)}), "bigquery"],
            cwd=temporary, env=env, capture_output=True, text=True, check=False,
        )
        if result.returncode or result.stdout.strip() != "SELECT 42 AS answer":
            raise RuntimeError(f"Installed CLI smoke test failed:\n{result.stderr}\n{result.stdout}")
        subprocess.run([
            sys.executable, "-c", "from dbt_invoke import invoke; "
            f"assert invoke('no_args', {json.dumps(json.dumps({'local': str(fixture)}))}, "
            "'bigquery').strip() == 'SELECT 42 AS answer'",
        ], cwd=temporary, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    print("Installed CLI and Python API passed")


if __name__ == "__main__":
    main()
