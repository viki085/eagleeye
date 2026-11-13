"""Static check for DuckDB SQL written by the analysis agent.

Reuses the text-to-SQL validator with a policy built from the input schemas: one SELECT,
only the registered inputs, known columns, no table functions, a row limit. The container
(no network, external access disabled) is the control; this check saves wasted runs and
gives the model a precise reason to fix.
"""

import re

from eagleeye_sqlsafe.errors import SqlRejected
from eagleeye_sqlsafe.policy import ColumnRule, SqlPolicy
from eagleeye_sqlsafe.validator import validate

from eagleeye_sandbox.types import MAX_RESULT_ROWS, CodeRejected, SandboxInput

SCHEMA = "main"  # DuckDB's default schema, where the runner creates the input tables
# Functions sqlglot may not model as typed nodes, but which are pure and useful for analysis.
ANALYSIS_FUNCTIONS = frozenset(
    """
    corr covar_pop covar_samp regr_slope regr_intercept regr_r2 regr_count quantile_cont
    quantile_disc quantile median mode stddev stddev_samp stddev_pop variance var_samp var_pop
    skewness kurtosis entropy mad approx_count_distinct approx_quantile string_agg listagg
    strftime strptime date_diff datediff date_part datepart date_sub date_add date_trunc
    datetrunc dayname monthname year month day week quarter dayofweek dayofyear hour minute
    second epoch make_date last_day age greatest least round floor ceil ceiling abs ln log log10
    log2 exp power pow sqrt sign trunc lower upper trim ltrim rtrim replace substring substr left
    right length strlen concat concat_ws contains starts_with ends_with prefix suffix
    regexp_matches regexp_replace regexp_extract split_part lpad rpad try_cast coalesce nullif
    ifnull if isnan isfinite isinf bool_and bool_or count_if first last any_value arg_max
    arg_min max_by min_by row_number rank dense_rank percent_rank ntile lag lead first_value
    last_value cume_dist width_bucket to_char to_date
    """.split()
)
# Belt and braces: these never belong in an analysis query, however they were parsed.
_FORBIDDEN_CALL = re.compile(
    r"\b(read_\w+|parquet_scan|parquet_\w+|glob|getenv|query|query_table|duckdb_\w+"
    r"|pragma_\w+|sniff_csv|current_setting|which_secret|load|install|attach)\s*\(",
    re.IGNORECASE,
)


def policy_for(inputs: tuple[SandboxInput, ...]) -> SqlPolicy:
    tables = {
        f"{SCHEMA}.{i.name}": {c["name"].lower(): ColumnRule(c["type"]) for c in i.columns}
        for i in inputs
    }
    return SqlPolicy(
        tables=tables,
        can_see_pii=True,  # the user's own data; the model's preview is masked separately
        dialect="duckdb",
        default_schema=SCHEMA,
        default_limit=MAX_RESULT_ROWS,
        max_limit=MAX_RESULT_ROWS,
        extra_functions=ANALYSIS_FUNCTIONS,
    )


def check_sql(code: str, inputs: tuple[SandboxInput, ...]) -> str:
    """Returns the SQL to run (regenerated from the AST) or raises CodeRejected."""
    if _FORBIDDEN_CALL.search(code):
        raise CodeRejected(
            "FUNCTION_NOT_ALLOWED",
            "Use only the registered input tables; no file or system functions.",
        )
    try:
        validated = validate(code, policy_for(inputs))
    except SqlRejected as exc:
        raise CodeRejected(exc.code, exc.user_message) from exc
    if _FORBIDDEN_CALL.search(validated.sql):
        raise CodeRejected("FUNCTION_NOT_ALLOWED", "File and system functions are not allowed.")
    return validated.sql
