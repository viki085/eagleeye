"""validate(sql, policy) -> Validated | raises SqlRejected (C5 §4).

Pipeline: parse → one read-only SELECT → no forbidden nodes → only granted tables →
columns resolve (stars expanded) → no PII unless allowed → function policy → no cartesian
joins → limit injected/lowered → SQL regenerated from the AST (original text never runs).
"""

import hashlib
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError, SqlglotError
from sqlglot.optimizer.qualify import qualify

from eagleeye_sqlsafe import errors as E
from eagleeye_sqlsafe.functions import function_name, is_allowed
from eagleeye_sqlsafe.policy import SqlPolicy

ROOT_TYPES = (exp.Select, exp.Union, exp.Intersect, exp.Except)
FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Into,
    exp.Lock,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Copy,
    exp.Grant,
    exp.Revoke,
    exp.Use,
    exp.Pragma,
    exp.TruncateTable,
    exp.LoadData,
    exp.Analyze,
    exp.Kill,
    exp.Execute,
    exp.Declare,
)


@dataclass(frozen=True)
class Validated:
    sql: str
    tables: tuple[str, ...]
    limit: int
    fingerprint: str  # sha256 of the executed SQL (audit log)


def _ident(node: exp.Expression | None) -> str:
    """Quoted identifiers are case-sensitive in Postgres; unquoted fold to lower case."""
    if not isinstance(node, exp.Identifier):
        return ""
    return node.this if node.quoted else node.this.lower()


def _parse(sql: str, policy: SqlPolicy) -> exp.Expression:
    if len(sql) > policy.max_sql_chars:
        raise E.SqlRejected(E.TOO_COMPLEX, "The query is too long.")
    try:
        statements = [s for s in sqlglot.parse(sql, dialect=policy.dialect) if s is not None]
    except ParseError as exc:
        raise E.SqlRejected(
            E.PARSE_ERROR, f"The SQL could not be parsed: {str(exc)[:160]}"
        ) from exc
    if len(statements) != 1:
        raise E.SqlRejected(E.NOT_SINGLE_SELECT, "Exactly one SELECT statement is allowed.")
    root = statements[0]
    if not isinstance(root, ROOT_TYPES):
        raise E.SqlRejected(E.NOT_SINGLE_SELECT, "Only read-only SELECT queries are allowed.")
    return root


def _check_forbidden(root: exp.Expression, policy: SqlPolicy) -> None:
    for node in root.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise E.SqlRejected(E.FORBIDDEN_STATEMENT, "Only read-only SELECT queries are allowed.")
    if sum(1 for _ in root.find_all(exp.Select)) > policy.max_selects:
        raise E.SqlRejected(E.TOO_COMPLEX, "The query has too many nested SELECTs.")


def _cte_names(root: exp.Expression) -> set[str]:
    names: set[str] = set()
    for cte in root.find_all(exp.CTE):
        alias = cte.args.get("alias")
        if isinstance(alias, exp.TableAlias):
            names.add(_ident(alias.this))
    return names


def _check_tables(root: exp.Expression, policy: SqlPolicy) -> tuple[str, ...]:
    ctes = _cte_names(root)
    used: list[str] = []
    for table in root.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier) or table.args.get("catalog"):
            # table functions (generate_series, ...) and catalog-qualified names: fail closed
            raise E.SqlRejected(E.TABLE_NOT_ALLOWED, "That table is not available to you.")
        name = _ident(table.this)
        schema = _ident(table.args.get("db"))
        if not schema and name in ctes:
            continue
        key = f"{schema or policy.default_schema}.{name}"
        if key not in policy.tables:
            raise E.SqlRejected(E.TABLE_NOT_ALLOWED, f"Table '{name}' is not available to you.")
        if key not in used:
            used.append(key)
    return tuple(used)


def _qualify(root: exp.Expression, policy: SqlPolicy) -> exp.Expression:
    try:
        return qualify(
            root,
            schema=policy.sqlglot_schema(),
            db=policy.default_schema,
            dialect=policy.dialect,
            expand_stars=True,
            validate_qualify_columns=True,
            identify=False,
        )
    except (OptimizeError, SqlglotError) as exc:
        raise E.SqlRejected(E.UNKNOWN_COLUMN, f"Column check failed: {str(exc)[:200]}") from exc


def _alias_map(root: exp.Expression, policy: SqlPolicy) -> dict[str, str]:
    """alias (or bare name) → 'schema.table' for base tables in the qualified tree."""
    out: dict[str, str] = {}
    for table in root.find_all(exp.Table):
        name, schema = _ident(table.this), _ident(table.args.get("db"))
        key = f"{schema or policy.default_schema}.{name}"
        if key in policy.tables:
            out[table.alias_or_name] = key
    return out


def _check_pii(root: exp.Expression, policy: SqlPolicy) -> None:
    if policy.can_see_pii:
        return
    pii = policy.pii_columns()
    if not pii:
        return
    aliases = _alias_map(root, policy)
    for column in root.find_all(exp.Column):
        key = aliases.get(column.table)
        if key and (key, column.name.lower()) in pii:
            raise E.SqlRejected(
                E.COLUMN_RESTRICTED,
                f"Column '{column.name}' contains personal data you can't access.",
            )


def _check_functions(root: exp.Expression, policy: SqlPolicy) -> None:
    for func in root.find_all(exp.Func):
        if not is_allowed(func, policy.extra_functions):
            raise E.SqlRejected(
                E.FUNCTION_NOT_ALLOWED, f"Function '{function_name(func)}' is not allowed."
            )


def _check_joins(root: exp.Expression) -> None:
    for join in root.find_all(exp.Join):
        has_condition = join.args.get("on") is not None or join.args.get("using")
        if not has_condition:
            raise E.SqlRejected(
                E.CARTESIAN_JOIN, "Every JOIN needs an ON/USING condition (no cartesian joins)."
            )


def _apply_limit(root: exp.Expression, policy: SqlPolicy) -> tuple[exp.Expression, int]:
    limit_node = root.args.get("limit")
    current: int | None = None
    if isinstance(limit_node, exp.Limit) and isinstance(limit_node.expression, exp.Literal):
        try:
            current = int(limit_node.expression.this)
        except ValueError:
            current = None
    target = min(current, policy.max_limit) if current is not None else policy.default_limit
    return root.limit(target, copy=False), target


def validate(sql: str, policy: SqlPolicy) -> Validated:
    root = _parse(sql, policy)
    _check_forbidden(root, policy)
    tables = _check_tables(root, policy)
    qualified = _qualify(root, policy)
    _check_pii(qualified, policy)
    _check_functions(qualified, policy)
    _check_joins(qualified)
    limited, limit = _apply_limit(qualified, policy)
    # comments=False: comment text never reaches the database, logs or the UI
    final_sql = limited.sql(dialect=policy.dialect, comments=False)
    return Validated(final_sql, tables, limit, hashlib.sha256(final_sql.encode()).hexdigest())
