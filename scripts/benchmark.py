"""Measure cold dependency resolution and warm calls, including worker startup."""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from dbt_invoke import invoke
from dbt_invoke.adapters import runtime_versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", help="Standard dependency reference; defaults to a temporary Git fixture")
    parser.add_argument("--macro", default="no_args")
    parser.add_argument("--warm-runs", type=int, default=3)
    options = parser.parse_args()
    if options.warm_runs < 1:
        parser.error("--warm-runs must be positive")
    with tempfile.TemporaryDirectory(prefix="dbt-invoke-benchmark-") as temporary:
        root = Path(temporary).resolve()
        package = options.package
        if not package:
            source = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tiny_package"
            checkout = root / "fixture"
            shutil.copytree(source, checkout)
            for command in (
                ["init", "-b", "main"], ["config", "user.name", "Benchmark"],
                ["config", "user.email", "benchmark@example.test"], ["add", "."],
                ["commit", "-m", "Fixture"],
            ):
                subprocess.run(["git", *command], cwd=checkout, check=True, capture_output=True)
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout).decode().strip()
            package = json.dumps({"git": checkout.as_uri(), "revision": sha})
        os.environ["DBT_INVOKE_CACHE_DIR"] = str(root / "cache")
        timings = []
        for _ in range(options.warm_runs + 1):
            start = time.perf_counter()
            invoke(options.macro, package, "bigquery")
            timings.append(time.perf_counter() - start)
        print(json.dumps({
            "versions": runtime_versions("bigquery"), "cold_seconds": timings[0],
            "warm_seconds": timings[1:], "warm_median_seconds": statistics.median(timings[1:]),
        }, indent=2))


if __name__ == "__main__":
    main()
