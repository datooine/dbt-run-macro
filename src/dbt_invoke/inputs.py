"""Validate invocation data and generate dbt/Jinja source without evaluating it."""

import hashlib
import json
import math
import re

from jinja2 import Environment, TemplateSyntaxError

from .adapters import get_adapter

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
RESERVED = {"$relation", "$cte"}


def validate(macro: str, adapter: str, args: dict | None, template: str | None) -> dict:
    if not isinstance(macro, str) or not IDENTIFIER.fullmatch(macro):
        raise ValueError("macro must be an unqualified identifier, for example count_events")
    selected = get_adapter(adapter)
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError("args must be a JSON object of named macro arguments")
    if template is not None and not isinstance(template, str):
        raise ValueError("template must be SQL/Jinja source text, not a file path object")
    if any(not isinstance(key, str) or not IDENTIFIER.fullmatch(key) for key in args):
        raise ValueError("Named macro argument keys must be identifiers")

    active = set()

    def visit(value, path):
        if isinstance(value, (dict, list)):
            if id(value) in active:
                raise ValueError(f"Circular JSON value at {path}")
            active.add(id(value))
            try:
                if isinstance(value, dict):
                    if any(not isinstance(key, str) for key in value):
                        raise ValueError(f"JSON object keys must be strings at {path}")
                    reserved = RESERVED.intersection(value)
                    if reserved:
                        if len(value) != 1:
                            raise ValueError(f"A descriptor must contain exactly one key at {path}")
                        key = next(iter(reserved))
                        text = value[key]
                        if not isinstance(text, str) or not text.strip():
                            raise ValueError(f"{key} requires a nonempty string at {path}")
                        if key == "$relation":
                            selected.relation(text)
                    else:
                        for key, item in value.items():
                            visit(item, f"{path}.{key}")
                else:
                    for index, item in enumerate(value):
                        visit(item, f"{path}[{index}]")
            finally:
                active.remove(id(value))
        elif value is None or isinstance(value, (str, bool, int)):
            return
        elif isinstance(value, float) and math.isfinite(value):
            return
        else:
            raise ValueError(f"Expected a JSON-compatible value at {path}")

    visit(args, "args")
    # Validate placeholder use before installing any dependencies.
    if template is not None:
        _, calls = replace_placeholders(template, "selected_macro()", "input_definitions()")
        if not calls["macro"]:
            raise ValueError("A template must contain a {{ macro() }} placeholder")
        if has_cte(args) and not calls["input_ctes"]:
            raise ValueError("Templates with $cte arguments must contain {{ input_ctes() }}")
    return args


def has_cte(value) -> bool:
    if isinstance(value, dict):
        return "$cte" in value or any(has_cte(item) for item in value.values())
    if isinstance(value, list):
        return any(has_cte(item) for item in value)
    return False


def literal(value) -> str:
    """Round-trip JSON through a quoted Jinja string, keeping native JSON types."""
    encoded = json.dumps(value, ensure_ascii=True, allow_nan=False)
    return f"fromjson({json.dumps(encoded, ensure_ascii=True)})"


def replace_placeholders(source: str, macro_call: str, cte_call: str) -> tuple[str, dict]:
    """Rewrite bare zero-argument calls in output expressions, respecting Jinja tokens."""
    replacements = {"macro": macro_call, "input_ctes": cte_call}
    counts = dict.fromkeys(replacements, 0)
    try:
        tokens = list(Environment(keep_trailing_newline=True).lex(source))
    except TemplateSyntaxError as exc:
        raise ValueError(f"Malformed template: {exc}") from exc
    output = []
    in_expression = False
    previous = None
    index = 0
    while index < len(tokens):
        _, kind, text = tokens[index]
        if kind == "variable_begin":
            in_expression = True
            previous = None
        elif kind == "variable_end":
            in_expression = False
        if in_expression and kind == "name" and text in replacements and previous != ".":
            following = index + 1
            while following < len(tokens) and tokens[following][1] == "whitespace":
                following += 1
            if following < len(tokens) and tokens[following][2] == "(":
                closing = following + 1
                while closing < len(tokens) and tokens[closing][1] == "whitespace":
                    closing += 1
                if closing >= len(tokens) or tokens[closing][2] != ")":
                    raise ValueError(f"Template placeholder {text}() takes no arguments")
                output.append(replacements[text])
                counts[text] += 1
                index = closing + 1
                previous = ")"
                continue
        output.append(text)
        if kind != "whitespace":
            previous = text
        index += 1
    return "".join(output), counts


def generate_model(macro: str, namespace: str, adapter: str, args: dict, template: str | None):
    if not IDENTIFIER.fullmatch(namespace):
        raise ValueError(f"Invalid dbt package namespace {namespace!r}")
    seed = json.dumps([namespace, macro, args, template], sort_keys=True, ensure_ascii=True)
    # Avoid accidental collisions with names explicitly present in supplied SQL/templates.
    salt = 0
    while True:
        digest = hashlib.sha256(f"{salt}:{seed}".encode()).hexdigest()[:16]
        prefix = f"__dbt_invoke_{digest}"
        if prefix not in seed:
            break
        salt += 1
    ctes = []

    def expression(value):
        if isinstance(value, dict):
            if "$relation" in value:
                database, schema, identifier = get_adapter(adapter).relation(value["$relation"])
                return (
                    f"api.Relation.create(database={literal(database)}, "
                    f"schema={literal(schema)}, identifier={literal(identifier)})"
                )
            if "$cte" in value:
                name = f"{prefix}_input_{len(ctes)}"
                ctes.append((name, value["$cte"]))
                return literal(name)
            return "{" + ", ".join(
                f"{literal(key)}: {expression(item)}" for key, item in value.items()
            ) + "}"
        if isinstance(value, list):
            return "[" + ", ".join(expression(item) for item in value) + "]"
        return literal(value)

    preamble = "{% set " + prefix + "_args = " + expression(args) + " %}\n"
    macro_call = f"{namespace}.{macro}(**{prefix}_args)"
    definitions = ",\n".join(f"{name} AS (\n{sql}\n)" for name, sql in ctes)
    if template is not None:
        body, _ = replace_placeholders(template, macro_call, literal(definitions))
    elif ctes:
        body = (
            "WITH {{ " + literal(definitions) + " }},\n" + f"{prefix}_result AS (\n"
            "{{ " + macro_call + " }}\n)\n"
            f"SELECT * FROM {prefix}_result"
        )
    else:
        body = "{{ " + macro_call + " }}"
    return preamble + body
