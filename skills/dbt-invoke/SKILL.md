---
name: dbt-invoke
description: Render SQL-generating dbt package macros into SQL using the dbt-run-macro Python distribution and dbt-invoke CLI, including native Relations, CTE inputs, and templates for fragments. Use for macro compilation outside a maintained dbt project; warehouse execution and operational macros are unsupported.
---

Use `dbt-invoke` to return compiled SQL from a known dbt package macro. It exposes
one Python function and one CLI, installed from the `dbt-run-macro` PyPI
distribution. The Python import is `dbt_invoke`. BigQuery is the supported adapter
in v0.1.

Inspect the macro's source or package documentation to identify its named
arguments, defaults, SQL shape, and adapter requirements. Choose a reproducible
package reference using dbt's source semantics. Macro discovery and signature
inference are not features of the tool; do not invent package names or arguments.

- Read [CLI and Python usage](references/cli.md) for installation, dependency
  declarations, output handling, and troubleshooting controls.
- Read [Relations and CTEs](references/relations-and-ctes.md) when supplying a table
  or a SQL query as input. A CTE name is a string, not a native dbt Relation.
- Read [Templates](references/templates.md) when the macro returns an expression,
  predicate, column list, or another fragment rather than a complete query.

Prefer a macro that generates SQL without requesting warehouse metadata. Macros
using `run_query`, catalog introspection, or operational side effects cannot be
rendered by this tool. Report the underlying dbt error and inspect the macro
before attributing an ambiguous adapter failure to warehouse access.

Preserve the requested outcome: return or save the generated SQL as requested.
Compilation does not validate SQL against the warehouse and does not authorize
executing it. Dependency installation may download packages; compilation of
supported macros needs no warehouse credentials. Templates and input SQL are
trusted code-generation inputs, not a SQL sandbox.
