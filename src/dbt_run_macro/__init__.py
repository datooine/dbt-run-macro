"""Compile SQL-generating dbt macros without maintaining a dbt project."""

from importlib.metadata import PackageNotFoundError, version

from .api import invoke

try:
    __version__ = version("dbt-run-macro")
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = ["invoke"]
