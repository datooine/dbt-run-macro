import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from dbt_run_macro.dependencies import resolve


class CacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dbt-run-macro-cache-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / "cache"
        environment = patch.dict(os.environ, {"DBT_RUN_MACRO_CACHE_DIR": str(self.cache)})
        environment.start()
        self.addCleanup(environment.stop)
        self.entry = {"git": "https://example.test/repository.git", "revision": "fixed-sha"}
        self.versions = {"dbt-core": "1.10.23", "dbt-bigquery": "1.10.3"}
        self.counter = 0

    def project(self):
        self.counter += 1
        project = self.root / f"project-{self.counter}"
        project.mkdir()
        return project

    def install(self, project, entry=None, transitive=None):
        entry = self.entry if entry is None else entry

        def deps(command):
            self.assertEqual(command, "deps")
            package = project / "dbt_packages" / "actual_namespace"
            package.mkdir(parents=True)
            (package / "dbt_project.yml").write_text("name: actual_namespace\nversion: 1.0.0\n")
            (package / "macro.sql").write_text("SELECT 1")
            (project / "package-lock.yml").write_text(yaml.safe_dump({
                "packages": [{**entry, "name": "actual_namespace"}, *(transitive or [])],
            }))
        return Mock(side_effect=deps)

    def test_reuse_and_versions_are_part_of_cache_identity(self):
        first = self.project()
        installer = self.install(first)
        self.assertEqual(resolve(first, self.entry, self.versions, installer, False), "actual_namespace")
        installer.assert_called_once()
        second = self.project()
        installer = Mock(side_effect=AssertionError("A cache hit must not run dbt deps"))
        resolve(second, self.entry, self.versions, installer, False)
        self.assertEqual((second / "dbt_packages" / "actual_namespace" / "macro.sql").read_text(), "SELECT 1")
        self.assertFalse((second / "dbt_packages").is_symlink())
        third = self.project()
        installer = self.install(third)
        resolve(third, self.entry, {**self.versions, "dbt-core": "1.10.22"}, installer, False)
        installer.assert_called_once()

    def test_corrupt_lock_snapshot_is_rebuilt(self):
        first = self.project()
        resolve(first, self.entry, self.versions, self.install(first), False)
        index = next((self.cache / "index").glob("*.json"))
        snapshot = self.cache / "entries" / json.loads(index.read_text())["snapshot"]
        (snapshot / "package-lock.yml").write_text("corrupted")
        second = self.project()
        installer = self.install(second)
        self.assertEqual(resolve(second, self.entry, self.versions, installer, False), "actual_namespace")
        installer.assert_called_once()

    def test_failed_resolution_publishes_no_cache_record(self):
        first = self.project()
        with self.assertRaisesRegex(RuntimeError, "dependency failed"):
            resolve(first, self.entry, self.versions, Mock(side_effect=RuntimeError("dependency failed")), False)
        self.assertEqual(list((self.cache / "index").iterdir()), [])
        self.assertEqual(list((self.cache / "entries").iterdir()), [])
        second = self.project()
        self.assertEqual(resolve(second, self.entry, self.versions, self.install(second), False), "actual_namespace")

    def test_corrupt_package_metadata_is_rebuilt(self):
        first = self.project()
        resolve(first, self.entry, self.versions, self.install(first), False)
        index = next((self.cache / "index").glob("*.json"))
        snapshot = self.cache / "entries" / json.loads(index.read_text())["snapshot"]
        (snapshot / "dbt_packages" / "actual_namespace" / "dbt_project.yml").write_text("null")
        second = self.project()
        installer = self.install(second)
        self.assertEqual(resolve(second, self.entry, self.versions, installer, False), "actual_namespace")
        installer.assert_called_once()

    def test_no_cache_and_local_dependencies_bypass_persistent_state(self):
        for entry, no_cache, transitive in (
            (self.entry, True, None), ({"local": "/local/source"}, False, None),
            (self.entry, False, [{"local": "/local/transitive", "name": "transitive"}]),
        ):
            with self.subTest(entry=entry, no_cache=no_cache):
                project = self.project()
                installer = self.install(project, entry, transitive)
                resolve(project, entry, self.versions, installer, no_cache)
                installer.assert_called_once()
        self.assertEqual(list((self.cache / "index").iterdir()), [])
        self.assertEqual(list((self.cache / "entries").iterdir()), [])

    def test_cache_write_failure_does_not_discard_successful_resolution(self):
        project = self.project()
        installer = self.install(project)
        with patch("dbt_run_macro.dependencies._copy_packages", side_effect=OSError("cache is full")):
            self.assertEqual(resolve(project, self.entry, self.versions, installer, False), "actual_namespace")
        installer.assert_called_once()
        self.assertEqual(list((self.cache / "index").iterdir()), [])
        self.assertEqual(list((self.cache / "entries").iterdir()), [])
