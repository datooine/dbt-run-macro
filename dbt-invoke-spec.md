# dbt-invoke — Implementation Specification v0.1

**Status:** Ready for implementation\
**Purpose:** Compile SQL produced by dbt package macros from anywhere, without maintaining a dbt project or executing the compiled SQL.

## 1. Product contract

`dbt-invoke` is a small Python package and Unix-friendly CLI. It creates the minimum dbt project required to compile a macro invocation, returns the resulting SQL, and hides the generated project from the caller.

**Primary use case:** reuse complex SQL-generating dbt macros in notebooks, scripts, SQL consoles, and AI-assisted workflows.

**Non-goals:** execute SQL; invoke operational macros via `run-operation`; create persistent user-facing projects; discover macros; infer macro signatures; manage database credentials; provide a generic dbt runtime/framework.

Compilation is intended to be offline. The tool supports macros that generate SQL without querying the warehouse. Macros using `run_query`, database catalog introspection, or other connection-dependent operations are unsupported in v0.1. dbt's own compilation/adapter initialization behavior must be tested: dummy profiles do not inherently guarantee offline operation.

## 2. Public CLI

```text
dbt-invoke <macro> <package> <adapter> [--args JSON] [--template PATH]
           [--dry-run] [--no-cache] [--keep-project]
```

- `macro`: macro name within the installed package (normally unqualified).
- `package`: mandatory package reference including a reproducible version/revision where supported. The package's actual dbt namespace is read from its `dbt_project.yml`.
- `adapter`: mandatory adapter name, e.g. `bigquery`.
- `--args`: optional JSON **object** of named macro arguments. Positional macro arguments are out of scope.
- `--template`: optional path to a SQL/Jinja template used to place the macro's generated SQL within a statement.
- `--dry-run`: inspect generated files/configuration without compiling; diagnostics to stderr.
- `--no-cache`: bypass dependency/environment cache.
- `--keep-project`: preserve and report the workspace path on stderr for troubleshooting.

**Output contract:** On success, stdout contains *only* compiled SQL, with a trailing newline. All logs, warnings and diagnostics go to stderr. On failure, exit nonzero and do not emit partial SQL. No `--output`, `--file`, `--execute`, `--sql`, `--positional`, or `run-operation` commands.

Examples:

```bash
dbt-invoke count_events my-org/dbt-utils@1.0.0 bigquery \
  --args '{"relation":{"$relation":"myproject.raw.events"}}'

dbt-invoke count_events my-org/dbt-utils@1.0.0 bigquery \
  --args '{"relation":{"$cte":"SELECT * FROM raw.events WHERE active"}}' \
  > count_active.sql

dbt-invoke safe_ratio my-org/dbt-utils@1.0.0 bigquery \
  --args '{"a":"revenue","b":"cost"}' \
  --template ratio.sql
```

The package-reference notation `org/repo@version` is a proposed CLI convention; implementation must translate it to supported dbt package declarations and clearly document accepted sources and version syntax. Do not assume arbitrary GitHub repositories are dbt Hub packages.

## 3. Public Python API

One function, returning a plain string:

```python
from dbt_invoke import invoke

sql: str = invoke(
    "compare",
    "my-org/dbt-quality@1.0.0",
    "bigquery",
    args={
        "left": {"$relation": "myproject.prod.orders"},
        "right": {"$cte": "SELECT * FROM myproject.dev.orders WHERE active"},
    },
)
```

Signature:

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

`template` in Python is **template source text**; `--template` in the CLI is a **file path**. Cache/debug controls can remain CLI/internal settings for v0.1. No public `Compiler`, `Project`, session, or result object.

## 4. Argument descriptors

All macro arguments are named and encoded as JSON-compatible values. Recursively process typed descriptors, preserving ordinary strings, booleans, numbers, arrays, objects, and nulls.

### 4.1 Native dbt Relation

```json
{"relation": {"$relation": "myproject.raw.orders"}}
```

Create an adapter-appropriate dbt `Relation` object (database/project, schema/dataset, identifier/table). For v0.1, define and test three-part BigQuery identifiers. Avoid naïve string splitting for quoted identifiers; reject ambiguous formats with an actionable error. Relation creation must not contact the warehouse.

### 4.2 SQL-backed CTE

```json
{"relation": {"$cte": "SELECT * FROM raw.events WHERE active"}}
```

The runner assigns a unique generated name (e.g. `__dbt_invoke_input_0`), injects the supplied query into a CTE in the generated SQL statement, and passes the **name as a string** to the macro. A CTE is not a native dbt Relation. This works only for macros that interpolate the relation-like identifier into SQL; it does not work for macros that introspect a physical database relation.

Allow multiple `$cte` descriptors, with deterministic, collision-resistant names. Descriptor recognition is limited to objects with exactly one reserved key (`$relation` or `$cte`); ordinary dictionaries remain ordinary dictionaries. Reject malformed descriptors explicitly. The user is responsible for trusted SQL input; this is a code-generation tool, not a SQL sandbox.

## 5. Model generation and SQL composition

The tool generates `models/__invoke.sql` inside a minimal project. Compilation is performed by dbt, not by ad-hoc SQL substitution.

### 5.1 Complete-query macro, physical relation

Given:

```jinja
{% macro count_events(relation) %}
SELECT COUNT(*) AS n FROM {{ relation }}
{% endmacro %}
```

Generate a model conceptually equivalent to:

```jinja
{% set relation = api.Relation.create(database='myproject', schema='raw', identifier='events') %}
{{ my_package.count_events(relation=relation) }}
```

The resulting SQL is a complete `SELECT` statement.

### 5.2 Complete-query macro, SQL-backed CTE

For `{"relation":{"$cte":"SELECT * FROM raw.events WHERE active"}}`, generate conceptually:

```jinja
WITH __dbt_invoke_input_0 AS (
    SELECT * FROM raw.events WHERE active
),
__dbt_invoke_result AS (
    {{ my_package.count_events(relation='__dbt_invoke_input_0') }}
)
SELECT * FROM __dbt_invoke_result
```

This **assumes** the macro generates a query suitable for placement in a CTE body. Without a custom template, a macro with `$cte` arguments is treated as a complete-query macro. The runner does not infer the SQL fragment type.

### 5.3 Fragment-producing macros and templates

A macro may return a SQL expression, predicate, column list, or complete query. `--template` supplies the surrounding SQL.

`ratio.sql`:

```sql
SELECT {{ macro() }} AS ratio
FROM raw.orders
```

`macro()` is a **dbt-invoke template placeholder**, not a built-in dbt macro. Before dbt compilation, preprocess it into a valid Jinja call to the selected package macro with typed arguments. Preserve ordinary dbt Jinja in the template.

For templates using `$cte`, expose a second placeholder, `input_ctes()`, which expands to comma-separated CTE definitions **without** the `WITH` keyword. Example:

```sql
WITH
{{ input_ctes() }},
result AS (
    {{ macro() }}
)
SELECT * FROM result
```

Templates are responsible for placing the CTEs and macro output in syntactically valid SQL. If a template uses `$cte` arguments but omits `input_ctes()`, fail clearly rather than silently producing unresolved identifiers. If no `$cte` arguments exist, `input_ctes()` can render an empty string; users remain responsible for avoiding dangling commas.

**Implementation caution:** preserve Jinja evaluation order, variable scope, and native Relation values when expanding placeholders. Do not construct macro calls by unsafe interpolation of unescaped user strings. Use generated Jinja variables with safe serialization and deterministic names.

## 6. Generated project and compilation

Minimal workspace:

```text
<workspace>/
  dbt_project.yml
  packages.yml
  profiles.yml
  models/__invoke.sql
  dbt_packages/
  target/
```

The project is generated automatically. The profile uses the selected adapter with minimal dummy configuration sufficient for parsing/compilation. For BigQuery, investigate whether `method: oauth` with placeholder project/dataset is usable without credential discovery; do not claim an offline guarantee until verified.

Use the installed dbt Core and matching adapter. Resolve package dependencies using dbt's standard package mechanism (`dbt deps`) and resolve the actual package namespace from package metadata. Generate the model, then call `dbtRunner.invoke([... "compile", "--select", "__invoke" ...])` with explicit project/profile paths.

Extract compiled SQL from the selected model's compiled node or artifact. Do not scrape dbt logs for SQL. Do not execute or materialize the model. An explicit parse step is unnecessary unless an implementation test demonstrates otherwise.

**Critical feasibility spike:** verify that pure SQL-generating macros compile with a dummy BigQuery profile and no credentials or network access. Test a native Relation, a CTE argument, and an adapter-dispatched macro. If `dbt compile` attempts connection initialization, investigate supported offline-safe alternatives before expanding the API.

## 7. Caching and concurrency

Cache resolved package dependencies by package identity/revision, dependency lock state, dbt Core version, and adapter version. Do not key the package cache on macro arguments. Generate invocation-specific models in isolated workspaces so concurrent calls cannot overwrite each other's files.

Partial parsing and full persistent project caching are optional later optimizations; prioritize correctness and package reuse in v0.1. Cache state is disposable and never a user-owned project. `--no-cache` forces a fresh dependency resolution; `--keep-project` retains a debug workspace.

## 8. Errors and observability

Validate package reference, adapter availability, JSON object shape, reserved descriptors, template file existence, and macro name. Report dbt compilation failures with useful context to stderr. Distinguish unsupported warehouse-dependent macros when detectable; otherwise surface the underlying adapter/dbt failure without claiming certainty.

A successful compile does **not** guarantee that the SQL is valid for the warehouse. Use exit codes consistently; stdout must remain empty on error. Logs and debug paths must never pollute piped SQL.

## 9. Testing

Provide a tiny fixture dbt package with macros for:

1. Complete-query SQL generation from a physical Relation.
2. Complete-query generation from one and multiple SQL-backed CTEs.
3. Expression and column-list generation through templates.
4. Named arguments, defaults, nested JSON values, and descriptor conversion.
5. Adapter-specific quoting and macro dispatch.
6. No-argument macros and omitted `--args`.
7. Invalid descriptors, invalid macro names, and malformed templates.
8. Compilation without valid warehouse credentials or network access.
9. Dependency cache reuse and concurrent invocations.
10. Strict stdout/stderr separation and nonzero failure exit codes.

Include CLI integration tests and direct `invoke()` tests. Benchmark cold and warm invocations separately; performance targets should be set from measurements, not assumptions.

## 10. AI skill

Ship an Agent Skills-compatible skill in the same repository:

```text
skills/dbt-invoke/
  SKILL.md
  references/cli.md
  references/relations-and-ctes.md
  references/templates.md
```

The skill explains how to select a SQL-generating macro, identify named arguments, choose `$relation` versus `$cte`, generate templates for fragments, and diagnose unsupported warehouse-dependent macros. It is documentation for AI assistants, not an execution dependency or replacement for the Python CLI.

## 11. Implementation sequence

1. **Feasibility:** minimal BigQuery dummy project, `dbtRunner` compilation, no credentials/network; confirm compiled artifact extraction.
2. **Core:** package resolution, namespace lookup, generated model, public `invoke()` function.
3. **Typed inputs:** `$relation`, `$cte`, safe named argument generation.
4. **Composition:** automatic complete-query CTE wrapper and `macro()` / `input_ctes()` template placeholders.
5. **CLI:** positional macro/package/adapter, named `--args`, stdout/stderr contract.
6. **Robustness:** dependency cache, concurrency isolation, debug flags, tests, docs and skill.

## 12. Review risks and unresolved implementation details

- **Offline feasibility:** dummy adapter profiles may not prevent dbt from opening connections. Treat as a gating technical test.
- **Package notation:** decide whether `org/repo@version` means a dbt Hub package, a Git package, or supports both through explicit parsing rules.
- **Template placeholder implementation:** ensure reliable Jinja scope and native object handling without building a general templating framework.
- **CTE compatibility:** only macros that use an identifier as SQL can accept `$cte`; catalog-introspecting macros cannot.
- **SQL composition:** the automatic CTE wrapper assumes a complete-query macro. Templates handle other SQL shapes.
- **Cross-adapter expansion:** v0.1 can have a generic `adapter` argument while only guaranteeing tested BigQuery behavior initially.

**Design principle:** one function, one CLI, one output: compiled SQL. Everything else is internal plumbing.
