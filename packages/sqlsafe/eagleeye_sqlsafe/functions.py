"""Function policy.

sqlglot parses functions it knows (SUM, DATE_TRUNC, COALESCE, ...) into typed nodes and
everything else into `Anonymous`. Typed analytical functions are allowed unless denied;
Anonymous functions are denied unless explicitly allowed. Dangerous Postgres functions
(pg_read_file, pg_sleep, dblink, lo_import, set_config, ...) are all Anonymous, so they
fail closed even if this list misses one.
"""

from sqlglot import exp

# Typed sqlglot functions that are still unwanted (keys are sqlglot node keys): they reveal
# server, session or identity details rather than business data.
DENIED_TYPED = frozenset(
    {
        "currentversion",
        "currentuser",
        "sessionuser",
        "currentrole",
        "currentdatabase",
        "currentschema",
        "currentcatalog",
        "randomize",
    }
)

# Unknown-to-sqlglot names that are safe and useful for analytics.
ALLOWED_ANONYMOUS = frozenset(
    {
        "date_part",
        "to_char",
        "to_date",
        "age",
        "make_date",
        "justify_interval",
        "percentile_cont",
        "percentile_disc",
        "mode",
        "width_bucket",
        "regexp_replace",
        "split_part",
        "initcap",
        "lpad",
        "rpad",
        "btrim",
        "date_bin",
        "ntile",
    }
)


def function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.key.lower()


def is_allowed(node: exp.Func, extra: frozenset[str] = frozenset()) -> bool:
    name = function_name(node)
    if isinstance(node, exp.Anonymous):
        return name in ALLOWED_ANONYMOUS or name in extra
    return name not in DENIED_TYPED
