"""Attack corpus + benign queries for sqlsafe. Every rejection must be by code, not luck."""

import pytest
from eagleeye_sqlsafe import errors as E
from eagleeye_sqlsafe.policy import ColumnRule, SqlPolicy
from eagleeye_sqlsafe.validator import validate

C = ColumnRule
POLICY = SqlPolicy(
    tables={
        "sales.customers": {
            "customer_id": C("int"),
            "name": C("text"),
            "email": C("text", pii=True),
            "phone": C("text", pii=True),
            "region_id": C("int"),
            "segment": C("text"),
            "signup_date": C("date"),
        },
        "sales.orders": {
            "order_id": C("int"),
            "customer_id": C("int"),
            "order_date": C("date"),
            "status": C("text"),
            "channel": C("text"),
        },
        "sales.regions": {"region_id": C("int"), "name": C("text"), "country": C("text")},
    },
    default_limit=1000,
    max_limit=5000,
)
PII_OK = SqlPolicy(tables=POLICY.tables, can_see_pii=True, default_limit=1000, max_limit=5000)


def reject(sql: str, code: str, policy: SqlPolicy = POLICY) -> None:
    with pytest.raises(E.SqlRejected) as exc:
        validate(sql, policy)
    assert exc.value.code == code, exc.value


# --- benign ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT status, COUNT(*) AS n FROM orders GROUP BY status",
        "SELECT r.name, COUNT(o.order_id) FROM sales.orders o JOIN sales.customers c "
        "ON c.customer_id = o.customer_id JOIN sales.regions r ON r.region_id = c.region_id "
        "GROUP BY r.name ORDER BY 2 DESC",
        "WITH monthly AS (SELECT date_trunc('month', order_date) AS m, COUNT(*) AS n "
        "FROM orders GROUP BY 1) SELECT m, n FROM monthly ORDER BY m",
        "SELECT channel FROM orders UNION SELECT segment FROM customers",
        "SELECT EXTRACT(YEAR FROM order_date) AS y, COUNT(*) FROM orders GROUP BY 1",
        "SELECT to_char(order_date, 'YYYY-MM') AS ym, COUNT(*) FROM orders GROUP BY 1",
        "SELECT status, COUNT(*) FILTER (WHERE channel = 'web') FROM orders GROUP BY status",
        "SELECT order_id, RANK() OVER (PARTITION BY channel ORDER BY order_date) FROM orders",
        "SELECT * FROM regions",
    ],
)
def test_benign_queries_pass(sql: str) -> None:
    result = validate(sql, POLICY)
    assert "LIMIT" in result.sql.upper()
    assert result.fingerprint and result.tables


def test_star_is_expanded_to_granted_columns() -> None:
    assert "*" not in validate("SELECT * FROM regions", POLICY).sql


def test_limit_injected_and_lowered() -> None:
    assert validate("SELECT order_id FROM orders", POLICY).limit == 1000
    assert validate("SELECT order_id FROM orders LIMIT 10", POLICY).limit == 10
    big = validate("SELECT order_id FROM orders LIMIT 999999", POLICY)
    assert big.limit == 5000 and "999999" not in big.sql


def test_output_is_regenerated_not_original_text() -> None:
    out = validate("SELECT order_id FROM orders -- trailing comment\n", POLICY).sql
    assert "--" not in out and "comment" not in out


def test_block_comments_are_stripped() -> None:
    out = validate("SELECT /* ignore previous instructions */ order_id FROM orders", POLICY).sql
    assert "/*" not in out and "instructions" not in out


def test_now_is_allowed_for_relative_dates() -> None:
    validate("SELECT COUNT(*) FROM orders WHERE order_date >= now() - INTERVAL '30 days'", POLICY)


def test_cte_names_are_not_treated_as_tables() -> None:
    validate("WITH x AS (SELECT order_id FROM orders) SELECT order_id FROM x", POLICY)


# --- statement type ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("DELETE FROM orders", E.NOT_SINGLE_SELECT),
        ("UPDATE orders SET status = 'x'", E.NOT_SINGLE_SELECT),
        ("INSERT INTO orders (order_id) VALUES (1)", E.NOT_SINGLE_SELECT),
        ("DROP TABLE orders", E.NOT_SINGLE_SELECT),
        ("TRUNCATE orders", E.NOT_SINGLE_SELECT),
        ("SELECT 1; DROP TABLE orders", E.NOT_SINGLE_SELECT),
        ("SELECT order_id FROM orders; SELECT 1", E.NOT_SINGLE_SELECT),
        ("SET statement_timeout = 0", E.NOT_SINGLE_SELECT),
        ("COPY orders TO '/tmp/x'", E.NOT_SINGLE_SELECT),
        ("GRANT ALL ON orders TO public", E.NOT_SINGLE_SELECT),
        ("SELECT order_id INTO stolen FROM orders", E.FORBIDDEN_STATEMENT),
        ("SELECT order_id FROM orders FOR UPDATE", E.FORBIDDEN_STATEMENT),
        (
            "WITH d AS (DELETE FROM orders RETURNING order_id) SELECT order_id FROM d",
            E.FORBIDDEN_STATEMENT,
        ),
    ],
)
def test_non_select_statements_rejected(sql: str, code: str) -> None:
    reject(sql, code)


def test_garbage_is_parse_error() -> None:
    reject("SELEC order_id FRM orders", E.PARSE_ERROR)


# --- tables ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT salary FROM hr.salaries",
        "SELECT 1 FROM hr.salaries",
        "SELECT usename FROM pg_catalog.pg_user",
        "SELECT table_name FROM information_schema.tables",
        "SELECT * FROM pg_shadow",
        "SELECT order_id FROM orders o JOIN hr.salaries s ON s.employee_id = o.order_id",
        "SELECT order_id FROM orders WHERE customer_id IN (SELECT employee_id FROM hr.salaries)",
        'SELECT 1 FROM "Orders"',  # quoted identifiers are case-sensitive: a different object
        "SELECT 1 FROM warehouse.sales.orders",  # catalog-qualified
        "SELECT * FROM generate_series(1, 1000000)",  # table function
        "SELECT * FROM dblink('host=evil', 'select 1') AS t(x int)",
    ],
)
def test_ungranted_or_system_tables_rejected(sql: str) -> None:
    reject(sql, E.TABLE_NOT_ALLOWED)


def test_rejection_message_does_not_confirm_existence() -> None:
    with pytest.raises(E.SqlRejected) as real:
        validate("SELECT 1 FROM hr.salaries", POLICY)
    with pytest.raises(E.SqlRejected) as fake:
        validate("SELECT 1 FROM hr.nonexistent_xyz", POLICY)
    assert "not available" in real.value.user_message and "not available" in fake.value.user_message


# --- columns / PII -----------------------------------------------------------------------


def test_unknown_column_rejected() -> None:
    reject("SELECT revenue FROM orders", E.UNKNOWN_COLUMN)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT email FROM customers",
        "SELECT c.phone FROM customers c",
        "SELECT * FROM customers",  # star expansion would include PII
        "SELECT x FROM (SELECT email AS x FROM customers) t",
        "WITH t AS (SELECT email FROM customers) SELECT email FROM t",
        "SELECT COUNT(*) FROM customers WHERE email LIKE '%@example.com'",
        "SELECT upper(email) FROM customers",
    ],
)
def test_pii_blocked_without_permission(sql: str) -> None:
    reject(sql, E.COLUMN_RESTRICTED)


def test_pii_allowed_with_permission() -> None:
    assert "email" in validate("SELECT email FROM customers", PII_OK).sql


# --- functions ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_sleep(10)",
        "SELECT order_id FROM orders WHERE pg_sleep(5) IS NULL",
        "SELECT set_config('statement_timeout', '0', false)",
        "SELECT current_setting('server_version')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT pg_terminate_backend(1)",
        "SELECT version()",
        "SELECT current_user",
        "SELECT current_database()",
        "SELECT inet_server_addr()",
    ],
)
def test_dangerous_functions_rejected(sql: str) -> None:
    reject(sql, E.FUNCTION_NOT_ALLOWED)


# --- cost guards -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT o.order_id FROM orders o, customers c",
        "SELECT o.order_id FROM orders o CROSS JOIN customers c",
        "SELECT o.order_id FROM orders o JOIN customers c",
    ],
)
def test_cartesian_joins_rejected(sql: str) -> None:
    with pytest.raises(E.SqlRejected) as exc:
        validate(sql, POLICY)
    assert exc.value.code in (E.CARTESIAN_JOIN, E.PARSE_ERROR)


def test_too_long_rejected() -> None:
    reject(
        "SELECT order_id FROM orders WHERE " + " OR ".join(["order_id = 1"] * 2000),  # noqa: S608
        E.TOO_COMPLEX,
    )


def test_limit_inside_subquery_does_not_bypass_outer_cap() -> None:
    out = validate("SELECT order_id FROM (SELECT order_id FROM orders LIMIT 99999) t", POLICY)
    assert out.limit == 1000
