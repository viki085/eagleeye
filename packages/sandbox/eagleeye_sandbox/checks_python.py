"""Static check for Python written by the analysis agent (AST allow-list).

NOT a security boundary: Python cannot be sandboxed by inspecting source. The boundary is
the container (no network, read-only filesystem, non-root, resource caps). This check stops
obviously out-of-scope code before a container is started and tells the model why.
"""

import ast

from eagleeye_sandbox.types import CodeRejected

MAX_CODE_CHARS = 6000
ALLOWED_MODULES = frozenset(
    {
        "pandas",
        "numpy",
        "scipy",
        "sklearn",
        "math",
        "statistics",
        "datetime",
        "json",
        "re",
        "itertools",
        "collections",
        "functools",
    }
)
BANNED_NAMES = frozenset(
    {
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "input",
        "breakpoint",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "exit",
        "quit",
        "help",
    }
)
BANNED_ATTRIBUTES = frozenset(
    {
        "system",
        "popen",
        "read_pickle",
        "to_pickle",
        "read_html",
        "read_sql",
        "read_sql_query",
        "read_sql_table",
        "to_sql",
        "read_clipboard",
        "to_clipboard",
        "fromfile",
        "tofile",
        "memmap",
        "ctypeslib",
        "f2py",
    }
)
_ALLOWED_DUNDER_NAMES = frozenset({"__name__"})


def _reject(code: str, message: str) -> CodeRejected:
    return CodeRejected(code, message)


def _check_import(node: ast.Import | ast.ImportFrom) -> None:
    if isinstance(node, ast.ImportFrom):
        if node.level:
            raise _reject("IMPORT_NOT_ALLOWED", "Relative imports are not allowed.")
        modules = [node.module or ""]
    else:
        modules = [alias.name for alias in node.names]
    for module in modules:
        root = module.split(".", 1)[0]
        if root not in ALLOWED_MODULES:
            allowed = ", ".join(sorted(ALLOWED_MODULES))
            raise _reject(
                "IMPORT_NOT_ALLOWED", f"Module '{root}' is not available. Allowed: {allowed}."
            )


def check_python(code: str) -> str:
    """Returns the code unchanged or raises CodeRejected."""
    if len(code) > MAX_CODE_CHARS:
        raise _reject("TOO_COMPLEX", "The script is too long; keep it short and focused.")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise _reject(
            "PARSE_ERROR", f"Python syntax error: {exc.msg} (line {exc.lineno})."
        ) from exc
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            _check_import(node)
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES:
                raise _reject("NAME_NOT_ALLOWED", f"'{node.id}' is not allowed in analysis code.")
            if node.id.startswith("__") and node.id not in _ALLOWED_DUNDER_NAMES:
                raise _reject("NAME_NOT_ALLOWED", "Double-underscore names are not allowed.")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                raise _reject("NAME_NOT_ALLOWED", "Double-underscore attributes are not allowed.")
            if node.attr in BANNED_ATTRIBUTES:
                raise _reject("NAME_NOT_ALLOWED", f"'.{node.attr}' is not allowed.")
    return code
