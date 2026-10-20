"""pythia for PostgreSQL: PL/pgSQL development for AI agents, over
pythia-core. Pre-alpha — see README.md for what works today."""
__version__ = "0.4.0.dev0"     # kept equal to pyproject.toml (tests/test_postgres.py)

from .engine import PostgresEngine  # noqa: E402,F401 — needs __version__ first
