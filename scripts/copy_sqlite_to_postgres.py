"""Copy your Life Inbox from SQLite into a new Postgres database (for deploying).

Run it once, from the project folder, after `alembic upgrade head` on the new
database and before anyone signs in there:

    python -m scripts.copy_sqlite_to_postgres --to "postgresql+psycopg://USER:PASSWORD@HOST:5432/DB"

What it does:
- checks both databases are at the same migration (and refuses otherwise);
- refuses if the new database already has notes or accounts of its own
  (only the built-in "Local Owner" and the default topics a migration makes
  are cleared first);
- copies every table, parents before children, in batches;
- skips sign-in sessions, one-time codes and push subscriptions (they belong
  to the old address; you sign in again);
- sets each table's id counter past the copied rows (Postgres).

It only reads the source. Uploaded files (PDFs, images, audio) are not in the
database: copy `data/uploads/` to the server's upload folder (see
docs/deploy-container.md). Run with --dry-run first to see the counts.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import MetaData, create_engine, func, select, text

SKIP = {"alembic_version", "auth_sessions", "otp_challenges", "push_subscriptions"}
BATCH = 500


def _version(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _count(connection, table) -> int:
    return connection.execute(select(func.count()).select_from(table)).scalar_one()


def copy(source_url: str, target_url: str, *, dry_run: bool = False, out=print) -> dict:
    source = create_engine(source_url)
    target = create_engine(target_url)
    if _version(source) != _version(target):
        raise SystemExit(f"The databases are at different migrations ({_version(source)} vs {_version(target)}). "
                         "Run `python -m alembic upgrade head` on both first.")
    source_meta, target_meta = MetaData(), MetaData()
    source_meta.reflect(source)
    target_meta.reflect(target)
    tables = [t for t in source_meta.sorted_tables if t.name not in SKIP and t.name in target_meta.tables]

    with target.connect() as connection:
        users = target_meta.tables["users"]
        items = target_meta.tables["inbox_items"]
        others = connection.execute(select(func.count()).select_from(users).where(
            users.c.email != "local@life-inbox.local")).scalar_one()
        if others or _count(connection, items):
            raise SystemExit("The new database already has accounts or notes; this only copies into a fresh one.")

    counts: dict[str, int] = {}
    with source.connect() as reader, target.begin() as writer:
        # A fresh database holds only what migrations seeded: clear it, children first.
        for table in reversed(target_meta.sorted_tables):
            if table.name != "alembic_version" and not dry_run:
                writer.execute(table.delete())
        for table in tables:
            goal = target_meta.tables[table.name]
            columns = [c.name for c in table.columns if c.name in goal.c]
            rows = reader.execute(select(*[table.c[name] for name in columns])).mappings().all()
            counts[table.name] = len(rows)
            if dry_run or not rows:
                continue
            # A table pointing at itself (a subtopic's parent topic) gets those
            # links in a second pass, so a child never arrives before its parent.
            self_links = [fk.parent.name for fk in goal.foreign_keys if fk.column.table.name == goal.name]
            first = [{**dict(row), **{name: None for name in self_links}} for row in rows]
            for start in range(0, len(first), BATCH):
                writer.execute(goal.insert(), first[start:start + BATCH])
            for name in self_links:
                for row in rows:
                    if row[name] is not None:
                        writer.execute(goal.update().where(goal.c.id == row["id"]).values({name: row[name]}))
        if target.dialect.name == "postgresql" and not dry_run:
            for table in tables:
                goal = target_meta.tables[table.name]
                if "id" in goal.c and goal.c.id.autoincrement is not False and counts.get(table.name):
                    writer.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{goal.name}', 'id'), "
                        f"(SELECT COALESCE(MAX(id), 1) FROM {goal.name}))"))
    for name, number in counts.items():
        if number:
            out(f"{name}: {number}")
    out("Dry run: nothing was written." if dry_run else "Copied. Now copy data/uploads/ to the server's upload folder.")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from", dest="source", default="sqlite:///./data/life_inbox.db",
                        help="the SQLite database to copy (default: data/life_inbox.db)")
    parser.add_argument("--to", dest="target", required=True, help="the new Postgres database URL")
    parser.add_argument("--dry-run", action="store_true", help="only show what would be copied")
    args = parser.parse_args(argv)
    if args.source == args.target:
        print("The source and the target are the same database.")
        return 2
    copy(args.source, args.target, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
