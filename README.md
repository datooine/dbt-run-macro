# dbt-run-macro

Render SQL-generating dbt package macros from Python or the command line, without
maintaining a dbt project or configuring warehouse credentials.

```sh
python -m pip install 'dbt-run-macro[bigquery]'
```

Requires Python 3.11+. Version 0.1 supports dbt Core 1.10 and dbt-bigquery 1.10.
The PyPI distribution is `dbt-run-macro`. It installs the `dbt-run-macro` command;
the Python import is `dbt_run_macro`.

## Use the CLI

```text
dbt-run-macro <macro> <package> <adapter> [--args JSON] [--template PATH]
           [--dry-run] [--no-cache] [--keep-project]
```

For example, use dbt-utils' SQL expression macro with a surrounding statement:

```sql
-- surrogate.sql
SELECT {{ macro() }} AS surrogate_key
FROM raw.orders
```

```sh
dbt-run-macro generate_surrogate_key dbt-labs/dbt_utils@1.3.0 bigquery \
  --args '{"field_list":["customer_id","order_id"]}' \
  --template surrogate.sql > orders.sql
```

Successful stdout contains only compiled SQL and a trailing newline. dbt logs,
macro `log()`/`print()` output, errors, and retained project paths go to stderr.
Failures never emit partial SQL. Exit codes are `0` for success, `1` for dependency
or compilation failure, and `2` for invalid input or configuration. Help and
`--version` are informational commands and print to stdout.

There is no execution command, `run-operation`, output-file option, or positional
macro argument support. Redirect SQL with your shell.

## Use Python

```python
from dbt_run_macro import invoke

sql = invoke(
    "generate_surrogate_key",
    "dbt-labs/dbt_utils@1.3.0",
    "bigquery",
    args={"field_list": ["customer_id", "order_id"]},
    template="SELECT {{ macro() }} AS surrogate_key FROM raw.orders",
)
```

The public function returns a plain `str`:

```python
def invoke(
    macro: str,
    package: str,
    adapter: str,
    *,
    args: dict | None = None,
    template: str | None = None,
) -> str: ...
```

Python `template` is **source text**. CLI `--template` is a **file path**. Omitted
arguments become an empty named-argument object, allowing macro defaults.
Invalid inputs raise `ValueError`; dependency and compilation failures raise
`RuntimeError`. Diagnostics are written to stderr, including from Python.

## Package sources

Dependency resolution and installation use `dbt deps`, including transitive
dependencies and dbt's lock file. Supply one standard dependency entry as a JSON
string, using the same fields as `packages.yml`:

| Source | Package argument |
| --- | --- |
| dbt Hub | `'{"package":"dbt-labs/dbt_utils","version":"1.3.0"}'` |
| Git | `'{"git":"https://github.com/owner/repo.git","revision":"v1.0.0"}'` |
| Git subdirectory | `'{"git":"https://github.com/owner/repo.git","revision":"COMMIT_SHA","subdirectory":"dbt"}'` |
| Local project | `'{"local":"/path/to/dbt-package"}'` |
| dbt tarball | `'{"tarball":"https://example.org/package-1.0.0.tar.gz","name":"package_name"}'` |

`owner/package@version` is shorthand for a **dbt Hub** entry, following dbt's
package source semantics. It does not guess whether a GitHub repository exists.
Use a Git dependency entry for repositories outside dbt Hub. Hub versions and Git
revisions are required. Native Hub version constraints are passed through to dbt
and frozen by its resolved lock file; exact versions/commit SHAs are preferable
for reproducible inputs. Relative local paths are resolved from the caller's
working directory. Git dependencies require Git on `PATH`.

The invocation targets the selected package's actual `dbt_project.yml` namespace,
which may differ from its repository or Hub name. The macro name must be an
unqualified identifier. Standard dbt dependency documentation is available at
[dbt packages](https://docs.getdbt.com/docs/build/packages).

## Relations and CTE inputs

Arguments accept JSON-compatible strings, booleans, finite numbers, arrays,
objects, and nulls. Two singleton object forms receive special treatment,
including when nested inside ordinary lists or dictionaries.

### Native Relation

```json
{"relation":{"$relation":"my-project.raw.events"}}
```

This becomes an actual adapter-specific dbt Relation, constructed without a
warehouse request. BigQuery accepts three-part `project.dataset.table` paths or
a single pair of backticks around the whole path, such as
`` `my-project.raw.events` ``. Database names may contain hyphens; table partition
and snapshot decorators are accepted. Individually quoted parts, whitespace,
embedded dots, and other ambiguous formats are rejected with a format hint.

For a macro that returns a complete query such as
`SELECT COUNT(*) AS n FROM {{ relation }}`, no template is required.

### SQL-backed CTE

```json
{"relation":{"$cte":"SELECT * FROM raw.events WHERE active"}}
```

This supplies a generated **identifier string**, not a native Relation. The tool
places the input query in a CTE and passes its name to the macro. It is suitable
for macros that interpolate a relation-like identifier into SQL; it cannot support
catalog introspection on a physical relation.

With no template, CTE inputs produce this statement shape:

```sql
WITH __dbt_run_macro_HASH_input_0 AS (
    SELECT * FROM raw.events WHERE active
),
__dbt_run_macro_HASH_result AS (
    -- selected macro's complete query
)
SELECT * FROM __dbt_run_macro_HASH_result
```

CTE descriptors contain SQL text; embedded Jinja is not evaluated. Multiple CTE
inputs receive distinct, deterministic names. The automatic wrapper
assumes the macro returns a query suitable for a CTE body. SQL fragments need a
custom template. Input SQL and Jinja templates are trusted code-generation input;
this tool is not a SQL sandbox.

Descriptors must contain exactly one reserved key with a nonempty string value.
Mixing a reserved key with extra fields is an error. Other dictionaries retain
their ordinary JSON meaning. Ordinary string arguments are serialized as data
and are never reinterpreted as Jinja source.

## Templates

Use `{{ macro() }}` to invoke the selected macro with its typed named arguments.
For example, a ratio macro returning an expression can use:

```sql
SELECT {{ macro() }} AS ratio
FROM raw.orders
```

`{{ input_ctes() }}` emits comma-separated input CTE definitions, without `WITH`:

```sql
WITH
{{ input_ctes() }},
result AS (
    {{ macro() }}
)
SELECT * FROM result
```

Templates with CTE arguments must include `input_ctes()`. Without CTE arguments,
it emits an empty string. The template controls valid SQL placement and commas.
Templates must contain at least one active `macro()` placeholder. Both placeholders
take zero arguments and appear in Jinja output expressions; filters are supported.
Ordinary dbt Jinja, local variables, loops, comments, raw blocks, and whitespace
control remain available. Placeholder text inside strings, comments, and raw
blocks is left alone. Rendering does not infer whether the macro returns an
expression, predicate, column list, or complete query.

## Offline behavior and limitations

Each invocation creates an isolated disposable project, installs/restores its
dependencies, generates `models/__invoke.sql`, and invokes dbt compilation in a
separate Python process. It never runs or materializes the generated model.

Pure SQL-generating macros compile with a dummy BigQuery `oauth-secrets` profile,
without valid credentials or credential discovery. Tests block network access
and Google default-credential lookup and cover native Relations, CTEs, and
adapter dispatch. dbt introspection, initial relation-cache population, partial
parsing, and anonymous telemetry are disabled. An `oauth` profile would trigger
credential discovery, so the generated profile deliberately does not use it.

**Dependency downloads can require network access.** A warm dependency cache or a
fully local dependency tree permits offline use. `--dry-run` still resolves
dependencies; it prints generated files to stderr without compiling or verifying
that the selected macro exists.

Macros using `run_query`, catalog introspection, warehouse-dependent adapter
methods, or operational side effects are unsupported. dbt's underlying failure is
reported; an adapter error alone is not proof that the macro queried a warehouse.
Packages requiring additional project configuration or undeclared resources can
also fail with their dbt errors. Successful compilation does not validate SQL
against BigQuery. Arbitrary third-party macro code is not sandboxed.

BigQuery is the only adapter supported in v0.1. Adapter profiles and identifier
parsers live behind an internal registry to allow future adapters without
changing `invoke()`. Other adapters require their own offline validation before
being enabled. No database credentials are read from your dbt profiles.

## Cache and troubleshooting

- Dependency snapshots live in the platform's user cache directory for `dbt-run-macro`.
  Set `DBT_RUN_MACRO_CACHE_DIR` to choose a different cache directory.
- Cache identity includes the dependency declaration, dbt Core/adapter versions,
  and resolved dependency lock state. Macro arguments and templates do not affect it.
- Process locks and atomic publication protect concurrent calls. Models, profiles,
  and compiled artifacts are always invocation-specific.
- Mutable local dependencies, including transitive local dependencies, bypass the
  persistent cache. Corrupt or incomplete cache records are rebuilt.
- `--no-cache` bypasses cache reads and writes and performs fresh resolution.
  Use it to refresh a branch, moved tag, or version constraint.
- `--keep-project` retains the generated workspace on success or failure and
  reports its path on stderr. Otherwise it is removed.

For macro errors, check its named arguments, whether it returns a complete query
or a fragment, and whether it requires a warehouse. The bundled
[dbt-run-macro skill](skills/dbt-run-macro/SKILL.md) provides assistant-facing guidance.

## Development and validation

```sh
uv sync --locked --extra bigquery
uv run --locked --extra bigquery ruff check .
uv run --locked --extra bigquery python -m unittest discover -s tests -v
uv build --no-sources
uv run --locked --extra bigquery python scripts/benchmark.py
```

`uv.lock` is versioned. CI tests Python 3.11–3.13 on Linux and Python 3.12 on
Windows/macOS. Offline integration tests use the tiny local fixture package and
a temporary Git repository, with no warehouse credentials or remote package
downloads. `scripts/benchmark.py` measures a cold dependency resolution and warm
invocations separately, including subprocess startup, using a local Git fixture.
It sets no performance threshold. Use `--package` to measure another standard
package reference.

Local validation on 2026-11-01 covered all 38 test cases on Linux with Python
3.11.13, 3.12.3, and 3.13.7. The built wheel and source distribution were also
installed into a separate environment and exercised outside the checkout.
Windows/macOS execution is configured in CI and has not been verified locally.

A local Python 3.12.3 benchmark with dbt Core 1.10.23 and dbt-bigquery 1.10.3,
using the temporary Git fixture, measured:

| Invocation | Seconds |
| --- | ---: |
| Cold dependency resolution and compile | 15.58 |
| First warm invocation | 11.22 |
| Second warm invocation | 9.60 |
| Warm median | 10.41 |

These measurements include a fresh dbt subprocess for every call. The cache
reuses dependencies, not an initialized adapter or parsed project. Results vary
with machine load and dependency versions; remote download latency is excluded
by the local Git fixture.

The source distribution includes the fixture, tests, scripts, and Agent Skills
documentation. The wheel contains the Python library and command.

## Publishing releases

Publishing follows `gitvars-render`'s conventions. The PyPI and TestPyPI project
is `dbt-run-macro`, hosted at `datooine/dbt-run-macro` on GitHub. `pyproject.toml`
is the single version source; `dbt-run-macro --version` reads the installed
`dbt-run-macro` distribution metadata.

| Event after successful CI | Result |
| --- | --- |
| Pull request | Tests/builds; no publishing |
| Push to `main` before any release tag | Development build to TestPyPI |
| Push with unchanged released version | Next-patch development build to TestPyPI |
| Version above the latest release tag | Tag the tested commit and publish to PyPI |
| Push of a matching version tag | Verify version/tag/tests and publish to PyPI |

The first production release is explicit:

```sh
git tag v0.1.0
git push origin v0.1.0
```

For subsequent releases, run `uv version 0.1.1`, commit `pyproject.toml` and
`uv.lock`, and merge to `main`. Stable releases use canonical `MAJOR.MINOR.PATCH`
versions. Development builds use a unique `.dev` serial derived from the workflow
run and attempt; that version change stays in the build checkout.

The workflow serializes publication, rejects version regressions and mismatched
tags, never moves an existing tag, and tags the exact commit CI tested. Retrying
a tagged release skips distributions already uploaded. Wheel and source
installations are checked before upload.

Configure trusted publishers on PyPI and TestPyPI and create GitHub environments:

| Setting | PyPI | TestPyPI |
| --- | --- | --- |
| Project | `dbt-run-macro` | `dbt-run-macro` |
| Repository owner | `datooine` | `datooine` |
| Repository name | `dbt-run-macro` | `dbt-run-macro` |
| Workflow | `publish.yml` | `publish.yml` |
| Environment | `pypi` | `testpypi` |

Uploads use OIDC trusted publishing, without a stored registry API token. Pending
publishers can create the project on its first upload; see the
[PyPI trusted-publishing documentation](https://docs.pypi.org/trusted-publishers/).
