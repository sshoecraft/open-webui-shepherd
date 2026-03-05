"""Peewee migrations -- 019_populate_usernames.py.

Populates the username column for all existing users who don't have one,
deriving usernames from email addresses.
"""

import re
from contextlib import suppress

import peewee as pw
from peewee_migrate import Migrator


with suppress(ImportError):
    import playhouse.postgres_ext as pw_pext


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    """Populate username column for existing users from email local parts."""
    if fake:
        return

    # Ensure columns exist (may not if Alembic hasn't run yet)
    # Works with both SQLite and PostgreSQL
    for col_name, col_type in [
        ("username", "VARCHAR(50)"),
        ("bio", "TEXT"),
        ("gender", "TEXT"),
        ("date_of_birth", "DATE"),
    ]:
        try:
            database.execute_sql(
                f"ALTER TABLE \"user\" ADD COLUMN {col_name} {col_type}"
            )
        except Exception:
            pass

    # Get all users without a username
    cursor = database.execute_sql(
        "SELECT id, email FROM \"user\" WHERE username IS NULL OR username = ''"
    )
    rows = cursor.fetchall()

    if not rows:
        return

    # Track already-used usernames to handle uniqueness conflicts
    existing_cursor = database.execute_sql(
        "SELECT username FROM \"user\" WHERE username IS NOT NULL AND username != ''"
    )
    used_usernames = set()
    for row in existing_cursor.fetchall():
        used_usernames.add(row[0].lower())

    for user_id, email in rows:
        # Derive base username from email local part
        if email and "@" in email:
            base_username = email.split("@")[0].lower()
        elif email:
            base_username = email.lower()
        else:
            base_username = user_id[:8]

        # Sanitize: keep only alphanumeric, hyphens, underscores, periods
        base_username = re.sub(r"[^a-zA-Z0-9._-]", "", base_username)
        if len(base_username) < 3:
            base_username = base_username + "user"

        username = base_username
        counter = 1
        while username.lower() in used_usernames:
            username = f"{base_username}{counter}"
            counter += 1

        used_usernames.add(username.lower())

        database.execute_sql(
            "UPDATE \"user\" SET username = ? WHERE id = ?",
            (username, user_id),
        )


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    """Clear usernames that were populated by this migration."""
    if fake:
        return

    database.execute_sql("UPDATE \"user\" SET username = NULL")
