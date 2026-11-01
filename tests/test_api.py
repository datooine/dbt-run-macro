import contextlib
import io
import json
import shutil
import subprocess
import unittest
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

from support import LOCAL

from dbt_invoke import invoke
from dbt_invoke.adapters import runtime_versions
from dbt_invoke.api import _invoke


class ApiTests(unittest.TestCase):
    def test_worker_logs_are_diagnostics_and_workspace_is_removed(self):
        workspaces = []

        def worker(command, **kwargs):
            workspace = kwargs["cwd"]
            workspaces.append(workspace)
            request = json.loads(Path(command[-2]).read_text())
            self.assertEqual(request["args"], {"value": "example"})
            self.assertEqual(request["template"], "SELECT {{ macro() }}")
            self.assertNotEqual(kwargs["env"].get("DBT_DOWNLOADS_DIR"), "")
            Path(command[-1]).write_text(json.dumps({"sql": "SELECT 1\n"}))
            return subprocess.CompletedProcess(command, 0, "dbt diagnostics\n")

        diagnostics = io.StringIO()
        with patch("dbt_invoke.api.subprocess.run", side_effect=worker), contextlib.redirect_stderr(diagnostics):
            sql = invoke("named", LOCAL, "bigquery", args={"value": "example"}, template="SELECT {{ macro() }}")
        self.assertEqual(sql, "SELECT 1\n")
        self.assertEqual(diagnostics.getvalue(), "dbt diagnostics\n")
        self.assertFalse(workspaces[0].exists())

    def test_failure_is_retained_only_when_requested(self):
        workspaces = []

        def worker(command, **kwargs):
            workspaces.append(kwargs["cwd"])
            Path(command[-1]).write_text(json.dumps({"error": "compile failed", "kind": "runtime"}))
            return subprocess.CompletedProcess(command, 1, "logs\n")

        with patch("dbt_invoke.api.subprocess.run", side_effect=worker):
            for keep in (False, True):
                diagnostics = io.StringIO()
                with contextlib.redirect_stderr(diagnostics), self.assertRaisesRegex(RuntimeError, "compile failed"):
                    _invoke("named", LOCAL, "bigquery", keep_project=keep)
                self.assertEqual(workspaces[-1].exists(), keep)
                if keep:
                    self.addCleanup(shutil.rmtree, workspaces[-1])
                    self.assertIn(str(workspaces[-1]), diagnostics.getvalue())

    def test_no_partial_sql_when_worker_has_no_valid_result(self):
        with patch("dbt_invoke.api.subprocess.run", return_value=subprocess.CompletedProcess([], 9, "SELECT partial\n")):
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaisesRegex(RuntimeError, "without a valid result"):
                    invoke("named", LOCAL, "bigquery")
            self.assertEqual(output.getvalue(), "")

    def test_missing_or_incompatible_adapter_has_actionable_error(self):
        with patch("dbt_invoke.adapters.version", side_effect=PackageNotFoundError("dbt-bigquery")):
            with self.assertRaisesRegex(ValueError, r"dbt-invoke\[bigquery\]"):
                runtime_versions("bigquery")
        with patch("dbt_invoke.adapters.version", return_value="2.0.0"):
            with self.assertRaisesRegex(ValueError, "1.10"):
                runtime_versions("bigquery")
