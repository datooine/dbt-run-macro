"""Private subprocess entry point; results travel in a file, never through dbt logs."""

import json
import sys
from pathlib import Path

import yaml

from .adapters import get_adapter
from .dependencies import resolve
from .inputs import generate_model

PROJECT = "dbt_run_macro_generated"


def execute(workspace: Path, request: dict) -> str:
    # Import only inside the worker: dbt maintains process-global state.
    from dbt.cli.main import dbtRunner

    project = {
        "name": PROJECT, "version": "1.0.0", "config-version": 2, "profile": PROJECT,
        "model-paths": ["models"], "packages-install-path": "dbt_packages",
        "target-path": "target", "log-path": "logs",
        "models": {"+enabled": False, PROJECT: {"+enabled": True}},
        "seeds": {"+enabled": False}, "snapshots": {"+enabled": False},
        "data_tests": {"+enabled": False},
    }
    profile = {PROJECT: {
        "target": "offline", "outputs": {"offline": get_adapter(request["adapter"]).output},
    }}
    for name, value in (
        ("dbt_project.yml", project), ("profiles.yml", profile),
        ("packages.yml", {"packages": [request["package"]]}),
    ):
        (workspace / name).write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    common = [
        "--project-dir", str(workspace), "--profiles-dir", str(workspace),
        "--profile", PROJECT, "--target", "offline", "--log-path", str(workspace / "logs"),
        "--no-send-anonymous-usage-stats", "--no-use-colors", "--no-partial-parse",
        "--no-populate-cache", "--no-static-parser",
    ]

    def run_dbt(command):
        options = [command, *common]
        if command == "compile":
            options.extend([
                "--no-introspect", "--select", "__invoke", "--threads", "1",
                "--target-path", str(workspace / "target"),
            ])
        result = dbtRunner().invoke(options)
        if not result.success:
            detail = str(result.exception) if result.exception else "see dbt diagnostics above"
            if result.result is not None and hasattr(result.result, "results"):
                messages = [item.message for item in result.result.results if item.message]
                if messages:
                    detail = "\n".join(messages)
            hint = (
                "\nWarehouse queries and catalog introspection are unsupported. "
                "The underlying dbt error is shown above; no credentials are configured."
            ) if command == "compile" else ""
            raise RuntimeError(f"dbt {command} failed: {detail}{hint}")
        return result

    namespace = resolve(
        workspace, request["package"], request["versions"], run_dbt, request["no_cache"],
    )
    model = generate_model(
        request["macro"], namespace, request["adapter"], request["args"], request["template"],
    )
    (workspace / "models").mkdir()
    (workspace / "models" / "__invoke.sql").write_text(model, encoding="utf-8")
    if request["dry_run"]:
        for name in (
            "dbt_project.yml", "profiles.yml", "packages.yml", "package-lock.yml",
            "models/__invoke.sql",
        ):
            print(f"\n--- {name} ---\n{(workspace / name).read_text(encoding='utf-8')}")
        return ""
    compiled = run_dbt("compile")
    nodes = [
        item.node for item in compiled.result.results
        if item.node.unique_id == f"model.{PROJECT}.__invoke"
    ]
    if len(nodes) != 1 or not isinstance(nodes[0].compiled_code, str):
        raise RuntimeError("dbt did not produce exactly one compiled __invoke model")
    return nodes[0].compiled_code.rstrip() + "\n"


def main() -> int:
    request_path, response_path = map(Path, sys.argv[1:])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        response = {"sql": execute(request_path.parent, request)}
        status = 0
    except Exception as exc:
        response = {
            "error": str(exc), "kind": "validation" if isinstance(exc, ValueError) else "runtime",
        }
        status = 1
    response_path.write_text(json.dumps(response), encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
