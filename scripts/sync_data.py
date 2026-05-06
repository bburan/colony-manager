"""CLI wrapper around :mod:`colony_manager_gui.sync`.

Usage
-----
::

    python sync_data.py
    python sync_data.py --dry-run
    python sync_data.py --rehash
    python sync_data.py --rehash --dry-run
"""
import argparse
import logging

from colony_manager_gui import create_app
from colony_manager_gui.sync import sync_locations, rehash_legacy


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sync data files from DataLocations to the Database.",
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help="Scan files without saving to the database.",
    )
    parser.add_argument(
        '--rehash', action='store_true',
        help="Re-hash rows whose stored hash isn't xxh3_128 (32-char hex). "
             "Skips disk walks; only touches rows with legacy hashes.",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.rehash:
            rehash_legacy(dry_run=args.dry_run)
        else:
            sync_locations(dry_run=args.dry_run)
