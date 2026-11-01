{% macro count_events(relation) %}
SELECT COUNT(*) AS n FROM {{ relation }}
{% endmacro %}

{% macro physical_relation(relation) %}
{% if relation is string %}{{ exceptions.raise_compiler_error('Expected a native Relation') }}{% endif %}
SELECT COUNT(*) AS n FROM {{ relation }}
{% endmacro %}

{% macro compare(left, right) %}
SELECT COUNT(*) AS n FROM {{ left }}
UNION ALL
SELECT COUNT(*) AS n FROM {{ right }}
{% endmacro %}

{% macro safe_ratio(a, b) %}SAFE_DIVIDE({{ a }}, {{ b }}){% endmacro %}

{% macro columns(names) %}{{ names | join(', ') }}{% endmacro %}

{% macro named(value='default', enabled=true) %}
SELECT {{ tojson(value) }} AS value, {{ 'TRUE' if enabled else 'FALSE' }} AS enabled
{% endmacro %}

{% macro no_args() %}SELECT 42 AS answer{% endmacro %}

{% macro json_values(data) %}{{ return(tojson(data)) }}{% endmacro %}

{% macro nested(data) %}
{{ return(tojson({'database': data[0]['relation'].database,
                 'schema': data[0]['relation'].schema,
                 'identifier': data[0]['relation'].identifier,
                 'cte': data[1]['relation'], 'values': data[2]})) }}
{% endmacro %}

{% macro dispatched(relation) %}
{{ return(adapter.dispatch('count_rows', 'fixture_macros')(relation)) }}
{% endmacro %}
{% macro default__count_rows(relation) %}SELECT 'default' AS flavor FROM {{ relation }}{% endmacro %}
{% macro bigquery__count_rows(relation) %}SELECT 'bigquery' AS flavor FROM {{ relation }}{% endmacro %}

{% macro noisy() %}
{{ log('fixture log', info=true) }}
{{ print('fixture print') }}
SELECT 1 AS n
{% endmacro %}

{% macro warehouse_query() %}
{% set result = run_query('SELECT 1') %}
SELECT 1
{% endmacro %}

{% macro warehouse_catalog(relation) %}
{% set columns = adapter.get_columns_in_relation(relation) %}
SELECT 1
{% endmacro %}
