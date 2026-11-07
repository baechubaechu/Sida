"""Make, list and revoke Sida access keys on the relay server, and answer key requests.

    docker compose exec relay python -m relay.admin issue "홍길동 (OO대)" [--limit 3000] [--days 90]
    docker compose exec relay python -m relay.admin list
    docker compose exec relay python -m relay.admin revoke <id>
    docker compose exec relay python -m relay.admin limit <id> <calls per day>
    docker compose exec relay python -m relay.admin usage [--days 7]
    docker compose exec relay python -m relay.admin requests [--all]
    docker compose exec relay python -m relay.admin approve <request id> [--limit 3000] [--days 90]
    docker compose exec relay python -m relay.admin refuse <request id>

`issue` prints the key once; only its hash is kept, so a lost key is revoked and a new one made.
A request someone sent from the app's settings is approved here; the app then collects its key
itself (nobody has to pass the key on).
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
    requests = sub.add_parser("requests", help="key requests sent from the app (waiting ones)")
    requests.add_argument("--all", action="store_true", help="answered ones too")
    approve = sub.add_parser("approve", help="approve a key request")
    approve.add_argument("id")
    approve.add_argument("--limit", type=int, default=DEFAULT_DAILY_LIMIT, help="API calls per day")
    approve.add_argument("--days", type=int, default=None, help="the key expires after this many days")
    refuse = sub.add_parser("refuse", help="refuse a key request")
    refuse.add_argument("id")
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
        if waiting := len(store.requests("pending")):
            print(f"기다리는 키 요청 {waiting}건 (requests로 보기)", file=out)
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
    elif args.command == "usage":
        for day, name, service, calls, failed in store.usage(args.days):
            print(f"{day}  {name}  {service}  {calls}회 (실패 {failed})", file=out)
    elif args.command == "requests":
        shown = store.requests(None if args.all else "pending")
        for r in shown:
            print(f"{r.id}  {_REQUEST_LABELS[r.state]}  {r.name}  연락 {r.contact or '-'}  요청 {r.created}", file=out)
        if not shown:
            print("기다리는 요청이 없습니다.", file=out)
    elif args.command == "approve":
        if not store.approve(args.id, daily_limit=args.limit, days=args.days):
            print(f"없거나 이미 답한 요청: {args.id}", file=out)
            return 1
        print(f"승인함: {args.id} (하루 {args.limit}회). 앱이 다음에 확인할 때 키를 받아 갑니다.", file=out)
    else:
        if not store.refuse(args.id):
            print(f"없거나 이미 답한 요청: {args.id}", file=out)
            return 1
        print(f"거절함: {args.id}", file=out)
    return 0


_REQUEST_LABELS = {"pending": "기다림", "approved": "승인(아직 안 받아 감)", "refused": "거절", "delivered": "키 받아 감"}


if __name__ == "__main__":
    raise SystemExit(main())
