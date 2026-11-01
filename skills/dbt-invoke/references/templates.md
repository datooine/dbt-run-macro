# Templates for SQL fragments

Templates contain ordinary SQL/dbt Jinja plus two zero-argument placeholders in
Jinja output expressions:

- `{{ macro() }}` invokes the chosen package macro with the supplied typed args.
- `{{ input_ctes() }}` emits input CTE definitions separated by commas, without
  a `WITH` keyword. With no CTE inputs, it emits an empty string.

A SQL expression macro can use:

```sql
SELECT {{ macro() }} AS ratio
FROM raw.orders
```

A complete-query macro with custom CTE composition can use:

```sql
WITH {{ input_ctes() }},
result AS (
    {{ macro() }}
)
SELECT * FROM result
```

Supply CLI templates through a file path, Python templates through source text.
Every template needs an active `macro()` placeholder. A template receiving CTE
descriptors also needs `input_ctes()`; place `WITH`, commas, and surrounding SQL
explicitly. If there are no input CTEs, omit the separator to avoid invalid SQL.

Filters, loops, local variables, normal dbt Jinja, and whitespace control remain
available. Calls are expanded where written; macro output is not precomputed.
Placeholder-like text in strings, comments, and raw blocks is not expanded.
Do not put named arguments inside the placeholders: provide them through
`--args` or Python `args` instead.
