import json
import unittest
from pathlib import Path

from support import FIXTURE

from dbt_invoke.adapters import bigquery_relation, get_adapter, runtime_versions
from dbt_invoke.dependencies import parse_package
from dbt_invoke.inputs import generate_model, replace_placeholders, validate


class InputTests(unittest.TestCase):
    def test_hub_shorthand_and_standard_dependency_entries(self):
        self.assertEqual(parse_package("dbt-labs/dbt_utils@1.3.0"), {
            "package": "dbt-labs/dbt_utils", "version": "1.3.0",
        })
        entry = {"git": "https://github.com/owner/project.git", "revision": "v1.2.3", "subdirectory": "dbt"}
        self.assertEqual(parse_package(json.dumps(entry)), entry)
        self.assertEqual(parse_package(json.dumps({"local": str(FIXTURE)})), {
            "local": str(FIXTURE.resolve()),
        })
        tarball = {"tarball": "https://example.test/pkg-1.0.0.tar.gz", "name": "pkg"}
        self.assertEqual(parse_package(json.dumps(tarball)), tarball)

    def test_invalid_sources(self):
        for value in (
            "", "owner/repo", "https://github.com/owner/repo.git@v1", "{}", "{broken",
            '{"package":"a/b"}', '{"git":"url"}', '{"local":"/does-not-exist"}',
            '{"git":"url","revision":"v1","package":"a/b","version":"1"}',
            '{"tarball":"url"}',
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_package(value)

    def test_relation_parsing_and_quoting(self):
        for value in ("my-project.raw.events", "`my-project.raw.events`", "my-project.raw.events$20260101"):
            parts = bigquery_relation(value)
            self.assertEqual(parts[:2], ("my-project", "raw"))
        for value in ("raw.events", "`p`.`raw`.`events`", "p.raw.some.table", "p.raw.`table`", "`p.raw.table", "p.raw.a b"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "project.dataset.table"):
                bigquery_relation(value)

    def test_recursive_validation(self):
        value = {"data": [None, True, 2, 3.5, {"ordinary": ["x", {"$relation": "p.s.t"}]}]}
        self.assertIs(validate("macro", "bigquery", value, None), value)
        bad = [
            [], {"a": {"$cte": ""}}, {"a": {"$relation": 1}},
            {"a": {"$cte": "SELECT 1", "extra": True}},
            {"a": {"$cte": "SELECT 1", "$relation": "p.s.t"}},
            {"a": float("nan")}, {"a": (1, 2)}, {"a": {1: "x"}}, {"not-valid": 1},
        ]
        circular = []
        circular.append(circular)
        bad.append({"a": circular})
        for value in bad:
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                validate("macro", "bigquery", value, None)

    def test_invalid_names_adapters_templates(self):
        for value in ("pkg.macro", "macro()", "macro;", "", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value, "bigquery", {}, None)
        with self.assertRaises(ValueError):
            get_adapter("postgres")
        with self.assertRaises(ValueError):
            runtime_versions("postgres")
        for template in ("SELECT 1", "{{ macro(1) }}", "{{ macro( }}", Path("template.sql")):
            with self.subTest(template=template), self.assertRaises(ValueError):
                validate("macro", "bigquery", {}, template)
        with self.assertRaisesRegex(ValueError, "input_ctes"):
            validate("macro", "bigquery", {"r": {"$cte": "SELECT 1"}}, "{{ macro() }}")

    def test_placeholders_are_token_aware(self):
        source = "{# {{ macro() }} #}{% raw %}{{ macro() }}{% endraw %}{{ 'macro()' }}{{ obj.macro() }}{{- macro ( ) | trim -}}"
        rewritten, counts = replace_placeholders(source, "pkg.real(**data)", "ctes()")
        self.assertEqual(counts, {"macro": 1, "input_ctes": 0})
        self.assertIn("{{ obj.macro() }}", rewritten)
        self.assertIn("{% raw %}{{ macro() }}{% endraw %}", rewritten)
        self.assertIn("{{- pkg.real(**data) | trim -}}", rewritten)

    def test_generated_names_are_deterministic_and_arguments_escaped(self):
        args = {"left": {"$cte": "SELECT 1"}, "right": {"$cte": "SELECT 2"}}
        first = generate_model("compare", "fixture", "bigquery", args, None)
        self.assertEqual(first, generate_model("compare", "fixture", "bigquery", args, None))
        self.assertIn("_input_0 AS", first)
        self.assertIn("_input_1 AS", first)
        self.assertIn("_result AS", first)
        self.assertIn("fixture.compare(**", first)
