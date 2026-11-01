"""dbt-native package declarations and disposable, process-safe dependency snapshots."""

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml
from filelock import FileLock
from platformdirs import user_cache_path

from .inputs import IDENTIFIER

SOURCES = ("package", "git", "local", "tarball")


def parse_package(value: str) -> dict:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("package must be a versioned Hub reference or a dbt dependency JSON object")
    value = value.strip()
    if value.startswith("{"):
        try:
            entry = json.loads(value)
        except ValueError as exc:
            raise ValueError(f"Invalid package dependency JSON: {exc}") from exc
    else:
        name, separator, revision = value.rpartition("@")
        if not separator or not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+", name) or not revision:
            raise ValueError(
                "Use owner/package@version for dbt Hub, or a dbt dependency JSON object "
                'such as {"git":"https://github.com/owner/repo.git","revision":"v1.0.0"}'
            )
        entry = {"package": name, "version": revision}
    sources = [key for key in SOURCES if key in entry]
    if len(sources) != 1:
        raise ValueError("A dependency must specify exactly one of package, git, local, or tarball")
    source = sources[0]
    if not isinstance(entry[source], str) or not entry[source].strip():
        raise ValueError(f"The dependency {source} must be a nonempty string")
    for required in {"package": ("version",), "git": ("revision",), "tarball": ("name",)}.get(source, ()):
        if not entry.get(required):
            raise ValueError(f"A {source} dependency requires {required}")
    if source == "local":
        path = Path(entry["local"]).expanduser().resolve()
        if not (path / "dbt_project.yml").is_file():
            raise ValueError(f"Local dependency has no dbt_project.yml: {path}")
        entry["local"] = str(path)
    return entry


def namespace(project: Path, entry: dict) -> str:
    lock = yaml.safe_load((project / "package-lock.yml").read_text(encoding="utf-8"))
    if (
        not isinstance(lock, dict) or not isinstance(lock.get("packages"), list)
        or any(not isinstance(item, dict) for item in lock["packages"])
    ):
        raise RuntimeError("Invalid dbt dependency lock file")
    source = next(key for key in SOURCES if key in entry)
    matches = [
        item for item in lock["packages"]
        if item.get(source) == entry[source]
        and item.get("subdirectory") == entry.get("subdirectory")
    ]
    if len(matches) != 1:
        raise RuntimeError("Could not identify the requested package in dbt's dependency lock file")
    name = matches[0].get("name")
    if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
        raise RuntimeError("The selected dependency has an invalid dbt namespace")
    metadata = yaml.safe_load(
        (project / "dbt_packages" / name / "dbt_project.yml").read_text(encoding="utf-8")
    )
    if not isinstance(metadata, dict) or metadata.get("name") != name:
        raise RuntimeError("Installed package metadata does not match the dependency lock file")
    return name


def cache_root() -> Path:
    override = os.environ.get("DBT_INVOKE_CACHE_DIR")
    return Path(override).expanduser().resolve() if override else user_cache_path("dbt-invoke")


def _copy_packages(source: Path, destination: Path):
    shutil.copytree(
        source, destination,
        ignore=shutil.ignore_patterns(".git", ".venv", "target", "logs", "dbt_packages"),
    )


def resolve(project: Path, entry: dict, versions: dict, run_dbt, no_cache: bool) -> str:
    if no_cache or "local" in entry:
        run_dbt("deps")
        return namespace(project, entry)
    try:
        return _resolve_cached(project, entry, versions, run_dbt)
    except OSError as exc:
        print(f"Dependency cache unavailable; resolving without it: {exc}", file=sys.stderr)
        try:
            # A snapshot write may fail after dependency installation has succeeded.
            return namespace(project, entry)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, yaml.YAMLError):
            run_dbt("deps")
            return namespace(project, entry)


def _resolve_cached(project: Path, entry: dict, versions: dict, run_dbt) -> str:
    identity = json.dumps({"format": 1, "package": entry, "versions": versions}, sort_keys=True)
    request_key = hashlib.sha256(identity.encode()).hexdigest()
    root = cache_root()
    for directory in ("locks", "index", "entries"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    with FileLock(root / "locks" / f"{request_key}.lock"):
        index = root / "index" / f"{request_key}.json"
        try:
            record = json.loads(index.read_text(encoding="utf-8"))
            content_key = record["snapshot"]
            if not re.fullmatch(r"[a-f0-9]{64}", content_key):
                raise ValueError("Invalid dependency cache snapshot")
            snapshot = root / "entries" / content_key
            lock_text = (snapshot / "package-lock.yml").read_bytes()
            expected = hashlib.sha256(identity.encode() + b"\0" + lock_text).hexdigest()
            if content_key != expected:
                raise ValueError("Dependency cache lock digest mismatch")
            shutil.copyfile(snapshot / "package-lock.yml", project / "package-lock.yml")
            _copy_packages(snapshot / "dbt_packages", project / "dbt_packages")
            name = namespace(project, entry)
            print("Using cached dbt dependencies", file=sys.stderr)
            return name
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, yaml.YAMLError):
            # A cache is disposable; never reuse partially restored dependency trees.
            shutil.rmtree(project / "dbt_packages", ignore_errors=True)
            (project / "package-lock.yml").unlink(missing_ok=True)

        run_dbt("deps")
        name = namespace(project, entry)
        lock_path = project / "package-lock.yml"
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
        if any("local" in item for item in lock["packages"]):
            # Local dependencies (including transitive ones) may change without a new revision.
            return name
        content_key = hashlib.sha256(identity.encode() + b"\0" + lock_path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="staging-", dir=root / "entries") as temporary:
            staging = Path(temporary) / "snapshot"
            staging.mkdir()
            shutil.copyfile(lock_path, staging / "package-lock.yml")
            _copy_packages(project / "dbt_packages", staging / "dbt_packages")
            destination = root / "entries" / content_key
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(staging, destination)
        # Only publish an index after the full snapshot has been installed.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=root / "index", delete=False,
        ) as stream:
            temporary_index = Path(stream.name)
            json.dump({"snapshot": content_key}, stream)
        try:
            os.replace(temporary_index, index)
        finally:
            temporary_index.unlink(missing_ok=True)
        return name
