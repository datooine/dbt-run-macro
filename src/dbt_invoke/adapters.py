"""Adapter-specific offline profiles and identifier parsing (internal)."""

import re
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Callable

from packaging.version import Version


def bigquery_relation(value: str) -> tuple[str, str, str]:
    """Accept a conservative, unambiguous subset of BigQuery table paths."""
    original = value
    if value.startswith("`") and value.endswith("`"):
        value = value[1:-1]
    match = re.fullmatch(
        r"([A-Za-z0-9_][A-Za-z0-9_-]*)\.([A-Za-z_][A-Za-z0-9_]*)\."
        r"([A-Za-z_][A-Za-z0-9_-]*(?:\$[0-9]+|@[0-9]+)?)",
        value,
    )
    if not match:
        raise ValueError(
            f"Invalid BigQuery $relation {original!r}: use project.dataset.table, "
            "optionally enclosed in one pair of backticks. Individually quoted parts, "
            "embedded dots, and whitespace are unsupported."
        )
    return match.group(1), match.group(2), match.group(3)


@dataclass(frozen=True)
class Adapter:
    distribution: str
    output: dict
    relation: Callable[[str], tuple[str, str, str]]


ADAPTERS = {
    "bigquery": Adapter(
        distribution="dbt-bigquery",
        output={
            "type": "bigquery",
            # oauth triggers ADC discovery during adapter initialization, even for compile.
            # oauth-secrets constructs a local credential object with this dummy token.
            "method": "oauth-secrets",
            "project": "dbt-invoke-offline",
            "dataset": "dbt_invoke_offline",
            "token": "dbt-invoke-offline-placeholder",
            "threads": 1,
        },
        relation=bigquery_relation,
    ),
}


def get_adapter(name: str) -> Adapter:
    if not isinstance(name, str) or name not in ADAPTERS:
        raise ValueError(f"Unsupported adapter {name!r}; v0.1 supports bigquery.")
    return ADAPTERS[name]


def runtime_versions(name: str) -> dict[str, str]:
    adapter = get_adapter(name)
    versions = {}
    for distribution in ("dbt-core", adapter.distribution):
        try:
            installed = version(distribution)
        except PackageNotFoundError as exc:
            raise ValueError(
                f"{distribution} is not installed. Install dbt-run-macro[bigquery] "
                "in the Python environment running dbt-invoke."
            ) from exc
        if Version(installed).release[:2] != (1, 10):
            raise ValueError(
                f"Unsupported {distribution} version {installed}; install the 1.10 release family."
            )
        versions[distribution] = installed
    return versions
