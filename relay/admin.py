"""Make, list and revoke Sida access keys on the relay server.

    docker compose exec relay python -m relay.admin issue "홍길동 (OO대)" [--limit 3000] [--days 90]
    docker compose exec relay python -m relay.admin list
    docker compose exec relay python -m relay.admin revoke <id>
    docker compose exec relay python -m relay.admin limit <id> <calls per day>
    docker compose exec relay python -m relay.admin usage [--days 7]

`issue` prints the key once; only its hash is kept, so a lost key is revoked and a new one made.
"""

from __future__ import annotations

import argparse
import os
import sys

from relay.tokens import DEFAULT_DAILY_LIMIT, TokenStore


def main(argv: list[str] | None = None, *, store: TokenStore | None = None, out=None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="relay.admin", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue", help="make a key for one person")
    issue.add_argument("name")
    issue.add_argument("--limit", type=int, default=DEFAULT_DAILY_LIMIT, help="API calls per day")
    issue.add_argument("--days", type=int, default=None, help="expires after this many days")
    sub.add_parser("list", help="every key, without the key itself")
    revoke = sub.add_parser("revoke", help="stop a key")
    revoke.add_argument("id")
    limit = sub.add_parser("limit", help="change a key's daily limit")
    limit.add_argument("id")
    limit.add_argument("calls", type=int)
    usage = sub.add_parser("usage", help="calls per key, day and service")
    usage.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)

    store = store or TokenStore(os.environ.get("SIDA_RELAY_DB", "/data/relay.db"))
    if args.command == "issue":
        token, record = store.issue(args.name, daily_limit=args.limit, days=args.days)
        print(f"id {record.id}  {record.name}  하루 {record.daily_limit}회  만료 {record.expires or '없음'}", file=out)
        print(f"키(지금 한 번만 보입니다): {token}", file=out)
    elif args.command == "list":
        for t in store.all():
            state = "폐기" if t.revoked else ("만료" if not t.usable(store.now().date()) else "사용 중")
            print(f"{t.id}  {state}  {t.name}  하루 {t.daily_limit}회  오늘 {store.calls_today(t.id)}회"
                  f"  만료 {t.expires or '없음'}  마지막 {t.last_used or '-'}", file=out)
    elif args.command == "revoke":
        if not store.revoke(args.id):
            print(f"없거나 이미 폐기한 키: {args.id}", file=out)
            return 1
        print(f"폐기함: {args.id}", file=out)
    elif args.command == "limit":
        if not store.set_limit(args.id, args.calls):
            print(f"없는 키: {args.id}", file=out)
            return 1
        print(f"{args.id}: 하루 {args.calls}회", file=out)
    else:
        for day, name, service, calls, failed in store.usage(args.days):
            print(f"{day}  {name}  {service}  {calls}회 (실패 {failed})", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
