"""Demo tester networks: visits from these have no demo time or budget limits.

  uv run --package eagleeye-api python scripts/demo_exempt.py --env-file .env.cloud list
  uv run --package eagleeye-api python scripts/demo_exempt.py --env-file .env.cloud add 203.0.113.0/24 --note "owner home"
  uv run --package eagleeye-api python scripts/demo_exempt.py --env-file .env.cloud remove 203.0.113.0/24

A network is a CIDR (a single address is /32). A home connection's address usually changes
within the provider's range: list the range, but keep it as small as covers your addresses,
because everyone else in it is exempt too. Changes apply at the next demo sign-in.
"""

import argparse
import asyncio
import ipaddress
import sys
from pathlib import Path

import asyncpg

MAX_IPV4_PREFIX = 16  # refuse ranges wider than a /16: too many strangers would be exempt


def database_url(env_file: Path) -> str:
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].split(" #", 1)[0].split("\t#", 1)[0].strip()
    sys.exit(f"DATABASE_URL not found in {env_file}")


def network(value: str) -> str:
    try:
        net = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError:
        sys.exit(f"not a network: {value!r} (use a CIDR such as 203.0.113.0/24)")
    if net.version == 4 and net.prefixlen < MAX_IPV4_PREFIX:
        sys.exit(f"{net} is wider than /{MAX_IPV4_PREFIX}; list a smaller range")
    return str(net)


async def main(args: argparse.Namespace) -> None:
    conn = await asyncpg.connect(database_url(args.env_file), statement_cache_size=0)
    try:
        if args.command == "add":
            await conn.execute(
                """
                INSERT INTO demo_exempt_networks (network, note) VALUES ($1::cidr, $2)
                ON CONFLICT (network) DO UPDATE SET note = EXCLUDED.note
                """,
                network(args.network),
                args.note,
            )
        elif args.command == "remove":
            await conn.execute(
                "DELETE FROM demo_exempt_networks WHERE network = $1::cidr", network(args.network)
            )
        rows = await conn.fetch(
            "SELECT network::text AS network, note, created_at FROM demo_exempt_networks"
            " ORDER BY created_at"
        )
        print(f"{len(rows)} exempt network(s)")
        for r in rows:
            print(f"  {r['network']:<20} {r['note']}  (added {r['created_at']:%Y-%m-%d})")
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--env-file", type=Path, default=Path(".env"))
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    add = sub.add_parser("add")
    add.add_argument("network")
    add.add_argument("--note", default="")
    rm = sub.add_parser("remove")
    rm.add_argument("network")
    asyncio.run(main(ap.parse_args()))
