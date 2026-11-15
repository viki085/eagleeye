"""Put the demo machine's secrets into AWS Parameter Store (Phase 7B).

Reads a git-ignored .env.cloud (NAME=VALUE lines) and writes each allowed name as an encrypted
SecureString under /eagleeye/demo/env/, where the demo machine reads its settings at every
boot. The values never pass through Terraform (so they are not in its state) or the terminal.

    uv run --no-project --with "boto3[crt]" python scripts/cloud_env.py check   # names only
    uv run --no-project --with "boto3[crt]" python scripts/cloud_env.py push
    uv run --no-project --with "boto3[crt]" python scripts/cloud_env.py list    # names in AWS

Names Terraform manages (buckets, generated passwords...) are refused, so the two never fight.
"""

import argparse
import re
import sys
from pathlib import Path

PATH = "/eagleeye/demo/env"
DEFAULT_FILE = Path(".env.cloud")

# what the demo needs from you; anything else in the file is refused
ALLOWED = {
    "DATABASE_URL": True,  # Supabase session pooler (eagleeye-demo project)
    "OPENAI_API_KEY": True,
    "QDRANT_URL": True,
    "QDRANT_API_KEY": True,
    "CLERK_SECRET_KEY": True,
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": True,
    "CLERK_ORGANIZATION_ID": False,
    "DEMO_PASSWORD": True,
    "DEMO_NOTIFY_EMAIL": False,
    "SMTP_USERNAME": False,
    "SMTP_PASSWORD": False,
    "MODEL_FAST": False,
    "MODEL_CAPABLE": False,
}  # True = required
TERRAFORM_MANAGED = {
    "APP_ENV",
    "LOG_FORMAT",
    "AWS_REGION",
    "WEB_ORIGIN",
    "DOCS_BUCKET",
    "ARTIFACTS_BUCKET",
    "SANDBOX_TRANSFER_BUCKET",
    "SANDBOX_BACKEND",
    "SANDBOX_LAMBDA_FUNCTION",
    "SANDBOX_TIMEOUT_S",
    "DB_POOL_MAX_API",
    "DB_POOL_MAX_WORKER",
    "DB_POOL_MAX_GATEWAY",
    "ORIGIN_VERIFY_SECRET",
    "GATEWAY_HMAC_SECRET",
    "WAREHOUSE_ADMIN_PASSWORD",
    "WAREHOUSE_RO_PASSWORD",
    "WAREHOUSE_DSN",
}


def parse(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or not name:
            raise ValueError(f"line {n}: expected NAME=VALUE")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:  # an unquoted value ends at " #": a comment after it is not part of it
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        values[name] = value
    return values


def problems(values: dict[str, str]) -> list[str]:
    found = []
    for name in values:
        if name in TERRAFORM_MANAGED:
            found.append(f"{name}: managed by Terraform, remove it from the file")
        elif name not in ALLOWED:
            found.append(f"{name}: not a demo setting (allowed: {', '.join(sorted(ALLOWED))})")
        elif not values[name]:
            found.append(f"{name}: empty (Parameter Store can't hold an empty value)")
    found += [f"{n}: required but missing" for n, req in ALLOWED.items() if req and n not in values]
    return found


def _ssm(profile: str, region: str):  # noqa: ANN202
    import boto3

    return boto3.Session(profile_name=profile, region_name=region).client("ssm")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["check", "push", "list"])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--profile", default="eagleeye")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()

    if args.command == "list":
        pages = _ssm(args.profile, args.region).get_paginator("get_parameters_by_path")
        for page in pages.paginate(Path=PATH, Recursive=True):
            for p in page["Parameters"]:
                print(f"{p['Name'].rsplit('/', 1)[-1]:32} {p['Type']}")
        return 0

    try:
        values = parse(args.file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read {args.file}: {exc}", file=sys.stderr)
        return 1
    found = problems(values)
    if found:
        print("not pushed:\n  " + "\n  ".join(found), file=sys.stderr)
        return 1
    if args.command == "check":
        print(f"{len(values)} settings ready: {', '.join(sorted(values))}")
        return 0
    ssm = _ssm(args.profile, args.region)
    for name, value in sorted(values.items()):
        ssm.put_parameter(Name=f"{PATH}/{name}", Value=value, Type="SecureString", Overwrite=True)
        print(f"pushed {name}")
    print("Restart the demo machine (or wait for its next start) to use them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
