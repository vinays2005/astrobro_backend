"""Run the whole test suite against a throw-away real Postgres (production uses Postgres; the default tests use SQLite).

    pip install pgserver              # embedded Postgres, development only
    python scripts/pg_tests.py        # extra pytest arguments are passed through, e.g. -k consult -x
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pgserver

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="astrobro-pg-") as data_dir:
        server = pgserver.get_server(data_dir, cleanup_mode="stop")
        try:
            url = server.get_uri().replace("postgresql://", "postgresql+asyncpg://", 1)
            print(f"Postgres is up at {url.split('@')[-1]}", flush=True)
            env = {**os.environ, "TEST_DATABASE_URL": url, "ASTROBRO_NULL_POOL": "1"}
            return subprocess.call([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", *sys.argv[1:]],
                                   cwd=ROOT, env=env)
        finally:
            server.cleanup()


if __name__ == "__main__":
    sys.exit(main())
