from __future__ import annotations

from pathlib import Path
from typing import List

from core.config import settings
from db import local_db

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _split_sql(sql: str) -> List[str]:
    statements: List[str] = []
    current: List[str] = []
    in_single = False
    in_double = False

    for char in sql:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double

        if char == ";" and not in_single and not in_double:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return statements


def ensure_schema() -> None:
    if not settings.AUTO_MIGRATE_SCHEMA:
        return
    if not settings.SUPABASE_DB_URL:
        print("SUPABASE_DB_URL not set; skipping Supabase schema initialization.")
        if settings.ENABLE_LOCAL_FALLBACK:
            local_db.ensure_local_schema()
        return

    try:
        import psycopg
    except ImportError:
        print("psycopg not installed; skipping schema initialization.")
        return

    if not SCHEMA_PATH.exists():
        print("Schema file not found; skipping schema initialization.")
        return

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    statements = _split_sql(schema_sql)

    try:
        with psycopg.connect(settings.SUPABASE_DB_URL) as conn:
            for statement in statements:
                conn.execute(statement)
            conn.commit()
    except Exception as exc:
        print(f"Schema initialization failed: {exc}")
        if settings.ENABLE_LOCAL_FALLBACK:
            local_db.ensure_local_schema()
