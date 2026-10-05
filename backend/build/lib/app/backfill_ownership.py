"""Adopt legacy, unowned rows into an account after upgrading to per-account scoping.

Why this is safe to run in stages: rows written before scoping have ``user_id IS NULL``
and stay visible to *every* signed-in account. Assigning them to an owner never removes
them from that owner's view, so you can assign one table at a time, check it, and undo it.

    cd backend
    uv run python -m app.backfill_ownership --dry-run                    # what exists
    uv run python -m app.backfill_ownership --list --table updates       # who wrote what
    uv run python -m app.backfill_ownership --email you@example.com --repo github.com/you
    uv run python -m app.backfill_ownership --undo --run-id <id>         # put it back

Every write is recorded in ``ownership_backfills`` (run id, table, and the exact row ids
it adopted), so a mistake is a one-command fix rather than a bad afternoon.
"""

from __future__ import annotations

import argparse
import json
import uuid
from collections import Counter

from sqlalchemy import select, text, update

from .auth import normalize_email
from .db import Note, SessionLocal, Task, TechDebt, Update, User, engine

TABLES = {
    "updates": (Update, "repo_url"),
    "notes": (Note, "repository"),
    "tasks": (Task, "repo_url"),
    "tech_debt": (TechDebt, "repo_url"),
}

LEDGER = "ownership_backfills"


def _ensure_ledger() -> None:
    """Create the audit table the first time a backfill runs."""
    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {LEDGER} ("
                "run_id VARCHAR(36) PRIMARY KEY, "
                "applied_at TIMESTAMPTZ, "
                "target_email VARCHAR(320), "
                "repo_filter VARCHAR(300), "
                "rows_by_table TEXT)"
            )
        )


def _unowned_rows(db, model, repo_column: str | None, repo_filter: str | None):
    query = select(model).where(model.user_id.is_(None))
    rows = list(db.scalars(query).all())
    if not repo_filter:
        return rows
    wanted = repo_filter.strip().lower().rstrip("/")
    return [row for row in rows if (getattr(row, repo_column, None) or "").lower().find(wanted) >= 0]


def _print_inventory(db, targets) -> None:
    print("Unowned (legacy) rows still visible to every account:")
    for name, (model, repo_column) in targets.items():
        rows = list(db.scalars(select(model).where(model.user_id.is_(None))).all())
        print(f"  {name:10} {len(rows)}")
        if not rows:
            continue
        owners = Counter()
        for row in rows:
            raw = (getattr(row, repo_column, None) or "").lower()
            if "github.com/" in raw:
                owners[raw.split("github.com/", 1)[1].split("/")[0]] += 1
            else:
                owners["(no repo)"] += 1
        for owner, count in owners.most_common():
            print(f"      owner-or-org {owner:28} {count}")


def _print_rows(db, targets, table: str) -> None:
    model, repo_column = targets[table]
    rows = list(db.scalars(select(model).where(model.user_id.is_(None))).all())
    print(f"{len(rows)} unowned row(s) in {table}:")
    for row in rows:
        repo = getattr(row, repo_column, None) or "-"
        print(f"  {row.id}  {getattr(row, 'title', '')[:60]!r}  repo={repo}")


def _undo(db, run_id: str) -> int:
    row = db.execute(
        text(f"SELECT target_email, rows_by_table FROM {LEDGER} WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).first()
    if row is None:
        print(f"No backfill recorded under run id {run_id}.")
        return 1
    target_email, rows_by_table = row
    adopted: dict[str, list[str]] = json.loads(rows_by_table or "{}")
    user = db.scalar(select(User).where(User.email == target_email))
    if user is None:
        print(f"Account {target_email} no longer exists; nothing to undo.")
        return 1
    # Undo exactly the rows this run adopted, leaving anything the account already owned.
    for name, ids in adopted.items():
        model = TABLES[name][0]
        result = db.execute(
            update(model)
            .where(model.id.in_(ids), model.user_id == user.id)
            .values(user_id=None)
        )
        if result.rowcount:
            print(f"  {name:10} returned {result.rowcount} row(s) to unowned")
    db.execute(text(f"DELETE FROM {LEDGER} WHERE run_id = :run_id"), {"run_id": run_id})
    db.commit()
    print(f"Run {run_id} undone.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Give legacy unowned rows an owner (staged, reversible, and auditable).",
        epilog="Without --email this only reports; it never writes.",
    )
    parser.add_argument("--email", help="Account that should own the rows")
    parser.add_argument("--table", choices=sorted(TABLES), help="Limit the work to one table")
    parser.add_argument("--repo", help="Only adopt rows whose repo contains this text (e.g. github.com/you)")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing")
    parser.add_argument("--list", action="store_true", help="List the unowned rows themselves")
    parser.add_argument("--run-id", help="Optional id to record the run under (default: generated)")
    parser.add_argument("--undo", action="store_true", help="Reverse a recorded run by --run-id")
    args = parser.parse_args()

    _ensure_ledger()
    targets = {args.table: TABLES[args.table]} if args.table else dict(TABLES)

    with SessionLocal() as db:
        if args.undo:
            if not args.run_id:
                parser.error("--undo needs --run-id")
            return _undo(db, args.run_id)

        if args.list:
            if not args.table:
                parser.error("--list needs --table")
            _print_rows(db, targets, args.table)
            return 0

        if not args.email:
            _print_inventory(db, targets)
            print("\nPass --email to adopt them, e.g. --email you@example.com --repo github.com/you")
            return 0

        email = normalize_email(args.email)
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            parser.error(f"No account found for {email}. Register it in the web UI first.")

        performed: dict[str, int] = {}
        for name, (model, repo_column) in targets.items():
            pending = {row.id for row in _unowned_rows(db, model, repo_column, args.repo)}
            if not pending:
                continue
            if args.dry_run:
                print(f"{name}: {len(pending)} unowned row(s) would be assigned to {email}")
                continue
            db.execute(update(model).where(model.id.in_(pending)).values(user_id=user.id))
            performed[name] = sorted(pending)
            print(f"{name}: assigned {len(pending)} unowned row(s) to {email}")

        if args.dry_run:
            db.rollback()
            return 0

        if not performed:
            print("Nothing to do.")
            return 0

        run_id = args.run_id or str(uuid.uuid4())
        db.execute(
            text(
                f"INSERT INTO {LEDGER} (run_id, applied_at, target_email, repo_filter, rows_by_table) "
                "VALUES (:run_id, CURRENT_TIMESTAMP, :email, :repo, :rows)"
            ),
            {"run_id": run_id, "email": email, "repo": args.repo or "", "rows": json.dumps(performed)},
        )
        db.commit()
        print(f"\nRecorded as run {run_id}. Undo with:")
        print(f"  uv run python -m app.backfill_ownership --undo --run-id {run_id}")
        # Context requests have no owner of their own; they are reached through their
        # update, so adopting the updates above scopes them automatically.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
