"""The `pythia-pg` command: pythia-core's command line, handed this engine."""
from pythia_core import cli

from .engine import PostgresEngine


def main(argv=None):
    return cli.main(PostgresEngine(), argv)
