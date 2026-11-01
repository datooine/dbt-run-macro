# CLI and Python

Install `dbt-run-macro[bigquery]` in the Python environment that will run the
`dbt-invoke` command. The Python import remains `dbt_invoke`.
The supported dbt Core and BigQuery adapter versions are in the 1.10 family.

```text
dbt-invoke <macro> <package> bigquery [--args JSON] [--template PATH]
           [--dry-run] [--no-cache] [--keep-project]
```

`macro` is unqualified. `--args` is a JSON object of named arguments; omit it to
use defaults. Successful stdout is only SQL with a trailing newline. Logs and
errors go to stderr; failures leave stdout empty. Redirect stdout to save SQL.
Exit codes: `0` success, `1` dependency/compilation failure, `2` invalid input or
configuration. No execution, `run-operation`, positional-argument, or output-file
options exist.

The package argument uses dbt dependency declarations. Hub shorthand
`dbt-labs/dbt_utils@1.3.0` means a Hub package, never an inferred GitHub repository.
For Git or local sources, pass a JSON-encoded standard dbt dependency entry:

```sh
dbt-invoke my_macro \
  '{"git":"https://github.com/owner/repo.git","revision":"v1.0.0"}' \
  bigquery --args '{"value":"example"}'
```

Local entries use `{"local":"/path/to/package"}`. Git subdirectories use dbt's
`subdirectory` field. Namespace selection comes from installed `dbt_project.yml`.
Prefer an exact Hub version or Git commit SHA. dbt resolves transitive dependencies
and produces the dependency lock file.

```python
from dbt_invoke import invoke

sql = invoke(
    "generate_surrogate_key", "dbt-labs/dbt_utils@1.3.0", "bigquery",
    args={"field_list": ["id"]},
    template="SELECT {{ macro() }} AS key FROM raw.orders",
)
```

Python `template` is source text; CLI `--template` is a file path. `invoke()`
returns `str`; invalid inputs raise `ValueError`, dependency/compile errors raise
`RuntimeError`. Diagnostics go to stderr.

`--dry-run` shows generated files without compilation, but may download
dependencies. `--keep-project` preserves and reports the project even after an
error. `--no-cache` resolves fresh dependencies without reading or writing the
cache. Local dependencies bypass the persistent cache. Inspect the macro and
retained model when compilation fails; do not configure warehouse credentials
to work around an unsupported warehouse-dependent macro.
