"""Flask CLI command groups for colony-manager management tasks.

All data-file operations live under the ``flask data`` group so there is a
single, discoverable entrypoint (``flask data --help``):

    flask data sync         [--datatype NAME|ID] [--dry-run] [-v]
    flask data rematch      --datatype NAME|ID [--force] [--dry-run] [-v]
    flask data rehash       [--dry-run] [-v]
    flask data sync-rating  [--datatype NAME|ID] [-v]
    flask data refresh      [--datatype NAME|ID] [-v]   # sync, then sync-rating

``refresh`` is the "one thing for cron to call" — it walks for new/moved
files and then refreshes rating status in a single run.
"""
import logging

import click
from flask.cli import with_appcontext

from colony_manager.models import DataType

log = logging.getLogger(__name__)


@click.group()
def data_cli():
    """Data-file management commands."""
    pass


def _resolve_datatype_id(datatype):
    """Resolve a ``--datatype`` option (name or numeric id) to an id.

    Returns ``None`` when the option was not supplied; raises
    ``click.ClickException`` when supplied but no DataType matches. Runs
    inside the command's app context, so ``db.session`` is bound.
    """
    if not datatype:
        return None
    from sqlalchemy import select
    from colony_manager_gui import db
    if datatype.isdigit():
        dt = db.session.get(DataType, int(datatype))
    else:
        dt = db.session.scalars(
            select(DataType).where(DataType.name == datatype)
        ).first()
    if dt is None:
        raise click.ClickException(f'DataType not found: {datatype}')
    return dt.id


def _echo_counts(label, counts):
    """Print a one-line ``label: k=v, k=v`` summary of a counts dict."""
    body = ', '.join(f'{k}={v}' for k, v in counts.items())
    click.echo(f'{label}: {body}')


def _enable_info_logging(verbose):
    """Surface sync.py's per-item INFO logging when ``-v`` is passed."""
    if verbose:
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s %(levelname)-8s %(message)s')
        logging.getLogger('colony_manager_gui.sync').setLevel(logging.INFO)


_datatype_option = click.option(
    '--datatype', default=None,
    help="Restrict to a single DataType (its name or numeric id).",
)
_dry_run_option = click.option(
    '--dry-run', is_flag=True, default=False,
    help="Report what would change without writing to the database.",
)
_verbose_option = click.option(
    '--verbose', '-v', is_flag=True, default=False,
    help="Show per-item progress logging.",
)


@data_cli.command('sync')
@_datatype_option
@_dry_run_option
@click.option('--debug', is_flag=True, default=False,
              help="Raise the first parser error instead of skipping it.")
@_verbose_option
@with_appcontext
def sync(datatype, dry_run, debug, verbose):
    """Walk DataLocations and ingest new / moved files."""
    from colony_manager_gui.sync import sync_locations
    _enable_info_logging(verbose)
    datatype_id = _resolve_datatype_id(datatype)
    counts = sync_locations(dry_run=dry_run, filter_datatype_id=datatype_id,
                            debug=debug)
    _echo_counts('sync', counts)


@data_cli.command('rematch')
@click.option('--datatype', required=True,
              help="DataType to rematch (its name or numeric id).")
@click.option('--force', is_flag=True, default=False,
              help="Walk every row, clearing existing target/candidate links, "
                   "instead of only currently-unmatched rows. Use after "
                   "changing parser regexes or matcher logic.")
@_dry_run_option
@_verbose_option
@with_appcontext
def rematch(datatype, force, dry_run, verbose):
    """Re-parse and re-match existing Data rows for one DataType."""
    from colony_manager_gui.sync import rematch_datatype
    _enable_info_logging(verbose)
    datatype_id = _resolve_datatype_id(datatype)
    counts = rematch_datatype(datatype_id, force=force, dry_run=dry_run)
    _echo_counts('rematch', counts)


@data_cli.command('rehash')
@_dry_run_option
@_verbose_option
@with_appcontext
def rehash(dry_run, verbose):
    """Re-hash rows whose stored hash isn't xxh3_128 (legacy hashes)."""
    from colony_manager_gui.sync import rehash_legacy
    _enable_info_logging(verbose)
    counts = rehash_legacy(dry_run=dry_run)
    _echo_counts('rehash', counts)


@data_cli.command('sync-rating')
@_datatype_option
@_verbose_option
@with_appcontext
def sync_rating(datatype, verbose):
    """Refresh rating status (is_rated / rating_note / raters) for all Data
    rows whose description class supports rating.
    """
    from colony_manager_gui.sync import sync_rating_status
    _enable_info_logging(verbose)
    datatype_id = _resolve_datatype_id(datatype)
    counts = sync_rating_status(filter_datatype_id=datatype_id)
    _echo_counts('sync-rating', counts)


@data_cli.command('refresh')
@_datatype_option
@_dry_run_option
@_verbose_option
@with_appcontext
def refresh(datatype, dry_run, verbose):
    """Full refresh for cron: ingest new/moved files, then rating status."""
    from colony_manager_gui.sync import sync_locations, sync_rating_status
    _enable_info_logging(verbose)
    datatype_id = _resolve_datatype_id(datatype)
    _echo_counts('sync', sync_locations(dry_run=dry_run,
                                        filter_datatype_id=datatype_id))
    if dry_run:
        click.echo('sync-rating: skipped (dry-run)')
        return
    _echo_counts('sync-rating', sync_rating_status(filter_datatype_id=datatype_id))
