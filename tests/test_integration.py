import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from support import LOCAL, git_package, offline_environment

from dbt_run_macro import invoke
from dbt_run_macro.api import _invoke


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dbt-run-macro-tests-")
        cls.root = Path(cls.temporary.name).resolve()
        cls.git_source = git_package(cls.root)
        cls.environment = patch.dict(os.environ, offline_environment(cls.root))
        cls.environment.start()

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temporary.cleanup()

    def tearDown(self):
        attempts = self.root / "offline-attempts.txt"
        self.assertFalse(attempts.exists(), attempts.read_text() if attempts.exists() else "")

    def render(self, macro, *, args=None, template=None, package=LOCAL, **controls):
        diagnostics = io.StringIO()
        output = io.StringIO()
        with contextlib.redirect_stderr(diagnostics), contextlib.redirect_stdout(output):
            if controls:
                sql = _invoke(macro, package, "bigquery", args=args, template=template, **controls)
            else:
                sql = invoke(macro, package, "bigquery", args=args, template=template)
        self.assertEqual(output.getvalue(), "")
        return sql, diagnostics.getvalue()

    def cli(self, macro="no_args", *options):
        return subprocess.run(
            [sys.executable, "-m", "dbt_run_macro", macro, LOCAL, "bigquery", *options],
            capture_output=True, encoding="utf-8", check=False,
        )

    def test_native_relation_and_namespace_from_metadata(self):
        sql, _ = self.render("physical_relation", args={"relation": {"$relation": "`my-project.raw.events`"}})
        self.assertEqual(sql.strip(), "SELECT COUNT(*) AS n FROM `my-project`.`raw`.`events`")

    def test_cte_wrapper_and_multiple_inputs(self):
        sql, _ = self.render("compare", args={
            "left": {"$cte": "SELECT 1 AS x"}, "right": {"$cte": "SELECT 2 AS x"},
        })
        self.assertRegex(sql, r"WITH __dbt_run_macro_[a-f0-9]+_input_0 AS")
        self.assertIn("_input_1 AS", sql)
        self.assertIn("SELECT 1 AS x", sql)
        self.assertIn("SELECT 2 AS x", sql)
        self.assertIn("UNION ALL", sql)
        self.assertRegex(sql, r"SELECT \* FROM __dbt_run_macro_[a-f0-9]+_result\s*$")

    def test_expression_and_column_templates_preserve_scope(self):
        sql, _ = self.render("safe_ratio", args={"a": "revenue", "b": "cost"}, template=(
            "{% set table = 'raw.orders' %}SELECT {{ macro() | trim }} AS ratio FROM {{ table }}"
        ))
        self.assertEqual(sql.strip(), "SELECT SAFE_DIVIDE(revenue, cost) AS ratio FROM raw.orders")
        sql, _ = self.render("columns", args={"names": ["id", "name"]}, template=(
            "{% for n in [1, 2] %}SELECT {{ macro() }} FROM table_{{ n }};{% endfor %}"
        ))
        self.assertEqual(sql.strip(), "SELECT id, name FROM table_1;SELECT id, name FROM table_2;")

    def test_template_ctes_and_empty_ctes(self):
        sql, _ = self.render("count_events", args={"relation": {"$cte": "SELECT 1 AS n"}}, template=(
            "WITH {{ input_ctes() }}, result AS ({{ macro() }}) SELECT * FROM result"
        ))
        self.assertIn("SELECT 1 AS n", sql)
        self.assertIn("result AS (", sql)
        sql, _ = self.render("no_args", template="{{ input_ctes() }}{{ macro() }}")
        self.assertEqual(sql.strip(), "SELECT 42 AS answer")

    def test_nested_descriptors_and_native_json_types(self):
        sql, _ = self.render("nested", args={"data": [
            {"relation": {"$relation": "p.raw.events"}},
            {"relation": {"$cte": "SELECT 1"}}, [None, True, False, 3, 2.5, {"ordinary": "yes"}],
        ]}, template="-- {{ input_ctes() | replace('\n', ' ') }}\n{{ macro() }}")
        payload = json.loads(sql[sql.index('{'):])
        self.assertEqual((payload["database"], payload["schema"], payload["identifier"]), ("p", "raw", "events"))
        self.assertRegex(payload["cte"], r"__dbt_run_macro_[a-f0-9]+_input_0")
        self.assertEqual(payload["values"], [None, True, False, 3, 2.5, {"ordinary": "yes"}])

    def test_strings_are_data_and_not_jinja_code(self):
        values = {"text": "'\"\\\n{{ exceptions.raise_compiler_error('injected') }}", "unicode": "España 😀", "bool": True}
        sql, _ = self.render("json_values", args={"data": values})
        self.assertEqual(json.loads(sql), values)

    def test_no_arguments_defaults_and_dispatch(self):
        sql, _ = self.render("no_args")
        self.assertEqual(sql.strip(), "SELECT 42 AS answer")
        sql, _ = self.render("named")
        self.assertIn('"default" AS value, TRUE AS enabled', sql)
        sql, _ = self.render("dispatched", args={"relation": {"$relation": "p.s.t"}})
        self.assertIn("'bigquery' AS flavor FROM `p`.`s`.`t`", sql)

    def test_cli_output_and_error_contract(self):
        success = self.cli("noisy")
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertEqual(success.stdout.strip(), "SELECT 1 AS n")
        self.assertTrue(success.stdout.endswith("\n"))
        self.assertIn("fixture log", success.stderr)
        self.assertIn("fixture print", success.stderr)
        for options in (("--args", "[]"), ("--args", "{"), ("--template", "/no/such/file.sql")):
            failed = self.cli("no_args", *options)
            self.assertEqual(failed.returncode, 2, failed.stderr)
            self.assertEqual(failed.stdout, "")
        failed = self.cli("missing_macro")
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertEqual(failed.stdout, "")

    def test_cli_template_file_and_dry_run(self):
        template = self.root / "ratio.sql"
        template.write_text("SELECT {{ macro() }} AS ratio", encoding="utf-8")
        result = self.cli("safe_ratio", "--args", '{"a":"a","b":"b"}', "--template", str(template))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "SELECT SAFE_DIVIDE(a, b) AS ratio")
        result = self.cli("missing_macro", "--dry-run", "--keep-project")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("models/__invoke.sql", result.stderr)
        path = Path(re.search(r"Kept dbt project: (.+)", result.stderr).group(1))
        self.addCleanup(shutil.rmtree, path)
        self.assertTrue((path / "models" / "__invoke.sql").is_file())
        self.assertFalse((path / "target" / "manifest.json").exists())

    def test_warehouse_macros_fail_without_network_or_credentials(self):
        for macro, args in (("warehouse_query", None), ("warehouse_catalog", {"relation": {"$relation": "p.s.t"}})):
            with self.subTest(macro=macro), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "unsupported"):
                    invoke(macro, LOCAL, "bigquery", args=args)

    def test_cache_reuse_is_independent_of_arguments_and_no_cache_resolves_fresh(self):
        with patch.dict(os.environ, {"DBT_RUN_MACRO_CACHE_DIR": str(self.root / "reuse-cache")}):
            cold, logs = self.render("named", args={"value": "cold"}, package=self.git_source)
            self.assertNotIn("Using cached dbt dependencies", logs)
            origin = self.root / "git-fixture"
            moved = self.root / "git-fixture-hidden"
            origin.rename(moved)
            try:
                warm, logs = self.render("named", args={"value": "warm"}, package=self.git_source)
                self.assertIn("Using cached dbt dependencies", logs)
                self.assertIn('"cold"', cold)
                self.assertIn('"warm"', warm)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(RuntimeError):
                    _invoke("named", self.git_source, "bigquery", no_cache=True)
            finally:
                moved.rename(origin)

    def test_concurrent_cold_calls_share_only_dependencies(self):
        cache = self.root / "concurrent-cache"
        with patch.dict(os.environ, {"DBT_RUN_MACRO_CACHE_DIR": str(cache)}), contextlib.redirect_stderr(io.StringIO()):
            with ThreadPoolExecutor(max_workers=3) as pool:
                outputs = list(pool.map(
                    lambda value: invoke("named", self.git_source, "bigquery", args={"value": value}),
                    ["first", "second", "third"],
                ))
        for value, sql in zip(("first", "second", "third"), outputs):
            self.assertIn(json.dumps(value), sql)
        self.assertEqual(len(list((cache / "index").glob("*.json"))), 1)
