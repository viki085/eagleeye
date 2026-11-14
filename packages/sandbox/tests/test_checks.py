import pytest
from eagleeye_sandbox.checks_python import check_python
from eagleeye_sandbox.checks_sql import check_sql
from eagleeye_sandbox.types import CodeRejected, SandboxInput

INPUTS = (
    SandboxInput(
        "ds_1", b"", ({"name": "month", "type": "DATE"}, {"name": "revenue", "type": "DOUBLE"})
    ),
    SandboxInput(
        "ds_2", b"", ({"name": "month", "type": "DATE"}, {"name": "target", "type": "DOUBLE"})
    ),
)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT month, SUM(revenue) AS revenue FROM ds_1 GROUP BY month ORDER BY month",
        "SELECT a.month, a.revenue - b.target AS gap FROM ds_1 a JOIN ds_2 b ON a.month = b.month",
        "SELECT CORR(revenue, target) AS r FROM ds_1 JOIN ds_2 USING (month)",
        "WITH m AS (SELECT DATE_TRUNC('month', month) AS m, revenue FROM ds_1) "
        "SELECT m, MEDIAN(revenue) AS med, QUANTILE_CONT(revenue, 0.9) AS p90 FROM m GROUP BY m",
        "SELECT month, revenue, LAG(revenue) OVER (ORDER BY month) AS prev FROM ds_1",
    ],
)
def test_analysis_sql_accepted_and_limited(sql: str) -> None:
    out = check_sql(sql, INPUTS)
    assert "LIMIT 100000" in out and "main.ds_1" in out


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("SELECT * FROM read_csv('/etc/passwd')", "FUNCTION_NOT_ALLOWED"),
        ("SELECT * FROM read_parquet('/work/in/ds_1.parquet')", "FUNCTION_NOT_ALLOWED"),
        ("SELECT * FROM 'https://example.com/x.csv'", "TABLE_NOT_ALLOWED"),
        ("SELECT * FROM glob('/*')", "FUNCTION_NOT_ALLOWED"),
        ("SELECT getenv('HOME')", "FUNCTION_NOT_ALLOWED"),
        ("SELECT * FROM duckdb_settings()", "FUNCTION_NOT_ALLOWED"),
        ("SELECT * FROM other_table", "TABLE_NOT_ALLOWED"),
        ("SELECT nope FROM ds_1", "UNKNOWN_COLUMN"),
        ("COPY ds_1 TO '/work/out/x.csv'", "NOT_SINGLE_SELECT"),
        ("ATTACH 'x.db'", "NOT_SINGLE_SELECT"),
        ("INSTALL httpfs", "NOT_SINGLE_SELECT"),
        ("SELECT 1; DROP TABLE ds_1", "NOT_SINGLE_SELECT"),
        ("CREATE TABLE x AS SELECT * FROM ds_1", "NOT_SINGLE_SELECT"),
        ("SET enable_external_access = true", "NOT_SINGLE_SELECT"),
        ("SELECT * FROM ds_1, ds_2", "CARTESIAN_JOIN"),
    ],
)
def test_analysis_sql_rejected(sql: str, code: str) -> None:
    with pytest.raises(CodeRejected) as exc:
        check_sql(sql, INPUTS)
    assert exc.value.code == code


GOOD_PYTHON = """
import numpy as np
import pandas as pd
from scipy import stats

df = datasets["ds_1"]
t, p = stats.ttest_ind(df["revenue"], datasets["ds_2"]["target"], equal_var=False)
save_stat("t", t)
save_stat("p_value", p)
save_table("summary", df.groupby("month", as_index=False)["revenue"].mean())
"""


def test_python_accepted_unchanged() -> None:
    assert check_python(GOOD_PYTHON) == GOOD_PYTHON


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("import os\nos.listdir('/')", "IMPORT_NOT_ALLOWED"),
        ("import subprocess", "IMPORT_NOT_ALLOWED"),
        ("import socket", "IMPORT_NOT_ALLOWED"),
        ("from urllib import request", "IMPORT_NOT_ALLOWED"),
        ("import pandas.io.common as c\nimport sys", "IMPORT_NOT_ALLOWED"),
        ("from . import x", "IMPORT_NOT_ALLOWED"),
        ("open('/etc/passwd').read()", "NAME_NOT_ALLOWED"),
        ("eval('1+1')", "NAME_NOT_ALLOWED"),
        ("exec('import os')", "NAME_NOT_ALLOWED"),
        ("__import__('os')", "NAME_NOT_ALLOWED"),
        ("getattr(pd, 'read_pickle')", "NAME_NOT_ALLOWED"),
        ("().__class__.__bases__[0].__subclasses__()", "NAME_NOT_ALLOWED"),
        ("pd.read_pickle('x')", "NAME_NOT_ALLOWED"),
        ("pd.io.common.os.system('id')", "NAME_NOT_ALLOWED"),
        ("x = __builtins__", "NAME_NOT_ALLOWED"),
        ("def f(:\n  pass", "PARSE_ERROR"),
        ("x = 1\n" * 4000, "TOO_COMPLEX"),
    ],
)
def test_python_rejected(code: str, expected: str) -> None:
    with pytest.raises(CodeRejected) as exc:
        check_python(code)
    assert exc.value.code == expected


# ---- notebook mode: plotting -----------------------------------------------------------------


def test_plotting_libraries_are_allowed() -> None:
    code = (
        "import matplotlib.pyplot as plt\nimport seaborn as sns\n"
        "fig, ax = plt.subplots()\nsns.histplot(datasets['ds_1']['v'], ax=ax)\n"
    )
    assert check_python(code) == code


@pytest.mark.parametrize(
    "code",
    [
        "import matplotlib.pyplot as plt\nplt.savefig('/work/out/x.png')",  # figures are captured
        "import matplotlib.pyplot as plt\nfig = plt.figure()\nfig.savefig('/tmp/f.png')",
        "import matplotlib.pyplot as plt\nplt.imread('/etc/passwd')",
        "import matplotlib.pyplot as plt\nplt.imsave('/tmp/a.png', [[0]])",
        "import seaborn as sns\nsns.load_dataset('titanic')",  # downloads from the internet
    ],
)
def test_plotting_file_and_network_access_is_rejected(code: str) -> None:
    with pytest.raises(CodeRejected) as exc:
        check_python(code)
    assert exc.value.code == "NAME_NOT_ALLOWED"
