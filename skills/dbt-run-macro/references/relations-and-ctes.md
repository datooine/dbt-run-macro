# Relations and SQL-backed CTEs

Pass a physical BigQuery table as a native Relation:

```json
{"relation":{"$relation":"my-project.raw.events"}}
```

Accepted identifiers have exactly three parts, optionally wrapped together in
one pair of backticks. Individually quoted parts and embedded dots are rejected.
The dbt adapter supplies quoting; no warehouse request creates the Relation.

Pass a query as a generated CTE identifier string:

```json
{"relation":{"$cte":"SELECT * FROM raw.events WHERE active"}}
```

This works when the macro interpolates an identifier into SQL. It does not give
the macro a native Relation and cannot provide catalog metadata. Inspect the
macro before substituting a CTE for a Relation argument.

Descriptors work recursively in lists and ordinary JSON objects. They must have
exactly one reserved key and a nonempty string value. Ordinary strings are data,
not Jinja expressions. Other JSON values retain their types.

Without a template, CTE inputs wrap the selected macro's SQL in a result CTE and
select from it. The macro must therefore return a complete query suitable for a
CTE body. Multiple inputs receive unique deterministic identifiers. For fragments
or custom composition, use a template with `{{ input_ctes() }}`; see
[templates](templates.md).
