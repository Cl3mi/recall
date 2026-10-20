from __future__ import annotations

import hashlib
import pathlib

import psycopg

MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"

_BOOTSTRAP = """
create table if not exists schema_migrations (
    version    text primary key,
    checksum   text not null,
    applied_at timestamptz not null default now()
)
"""


def discover() -> list[pathlib.Path]:
    """Migrations apply in filename order. Names are immutable once applied."""
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def _checksum(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_all(dsn: str) -> list[str]:
    """Apply pending migrations. Returns the versions applied this call."""
    applied: list[str] = []
    with psycopg.connect(dsn) as conn:
        conn.execute(_BOOTSTRAP)
        conn.commit()
        for path in discover():
            version, checksum = path.stem, _checksum(path)
            row = conn.execute(
                "select checksum from schema_migrations where version = %s", (version,)
            ).fetchone()
            if row is not None:
                if row[0] != checksum:
                    raise RuntimeError(
                        f"migration {version} changed after being applied "
                        f"(recorded {row[0][:12]}, on disk {checksum[:12]})"
                    )
                continue
            conn.execute(path.read_text())
            conn.execute(
                "insert into schema_migrations (version, checksum) values (%s, %s)",
                (version, checksum),
            )
            conn.commit()
            applied.append(version)
    return applied


if __name__ == "__main__":
    from recall.config import settings

    for v in apply_all(settings.pg_dsn):
        print(f"applied {v}")
