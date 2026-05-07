"""CLI wrapper around :mod:`colony_manager_gui.sync`.

Usage
-----
::

    python sync_data.py
    python sync_data.py --dry-run
    python sync_data.py --rehash
    python sync_data.py --rehash --dry-run
    python sync_data.py --datatype "Animal Photos"
    python sync_data.py --datatype 7
    python sync_data.py --rematch --datatype "Ear Dissection Notes"
    python sync_data.py --rematch --force --datatype "Ear Dissection Notes"
"""
import argparse
import logging
import sys

from colony_manager_gui import create_app
from colony_manager_gui.sync import (
    sync_locations, rehash_legacy, rematch_datatype,
)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
)
log = logging.getLogger(__name__)


def _resolve_datatype_id(value):
    """Resolve ``--datatype`` to an integer id.

    Accepts either a numeric id or a DataType ``name``. Returns
    ``None`` and logs an error if no matching row exists.
    """
    from colony_manager.models import DataType
    if value.isdigit():
        dt = DataType.query.get(int(value))
    else:
        dt = DataType.query.filter_by(name=value).first()
    if dt is None:
        log.error('No DataType matches %r.', value)
        return None
    return dt.id


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
    parser.add_argument(
        '--datatype', metavar='NAME_OR_ID', default=None,
        help="Restrict the walk to a single DataType. Accepts the "
             "DataType's name or numeric id. Ignored with --rehash.",
    )
    parser.add_argument(
        '--rematch', action='store_true',
        help="Re-parse and re-match existing rows for a DataType "
             "(requires --datatype). Skips disk walks for new files.",
    )
    parser.add_argument(
        '--force', action='store_true',
        help="With --rematch, walk every row (clearing existing target "
             "and candidate links) instead of only currently-unmatched "
             "rows. Use after changing parser regexes or matcher logic.",
    )
    parser.add_argument(
        '--debug', action='store_true',
        help="Raise the first error rather than suppressing it."
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.rehash:
            if args.datatype:
                log.warning('--datatype is ignored when --rehash is set.')
            rehash_legacy(dry_run=args.dry_run)
        elif args.rematch:
            if not args.datatype:
                log.error('--rematch requires --datatype.')
                sys.exit(1)
            filter_id = _resolve_datatype_id(args.datatype)
            if filter_id is None:
                sys.exit(1)
            rematch_datatype(filter_id, force=args.force, dry_run=args.dry_run)
        else:
            if args.force:
                log.warning('--force has no effect without --rematch.')
            filter_id = None
            if args.datatype:
                filter_id = _resolve_datatype_id(args.datatype)
                if filter_id is None:
                    sys.exit(1)
            sync_locations(dry_run=args.dry_run, filter_datatype_id=filter_id,
                           debug=args.debug)
