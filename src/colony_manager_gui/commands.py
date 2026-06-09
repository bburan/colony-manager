"""Flask CLI command groups for colony-manager management tasks."""
import logging

import click
from flask.cli import with_appcontext

from colony_manager.datatypes import load_description_class
from colony_manager.models import Data, DataType

log = logging.getLogger(__name__)


@click.group()
def data_cli():
    """Data-file management commands."""
    pass


@data_cli.command('sync-rating')
@click.option(
    '--datatype', 'datatype_name', default=None,
    help='Limit sync to a specific DataType name.',
)
@click.option('--verbose', '-v', is_flag=True, default=False)
@with_appcontext
def sync_rating(datatype_name, verbose):
    """Refresh is_rated / rating_note for all Data rows whose description
    class supports rating.  Designed to be run nightly via cron.
    """
    from sqlalchemy import select
    from colony_manager_gui import db

    session = db.session

    stmt = select(Data).join(DataType, Data.datatype_id == DataType.id)
    if datatype_name:
        stmt = stmt.where(DataType.name == datatype_name)

    updated = errors = skipped = 0

    for row in session.scalars(stmt):
        key = row.datatype.description_class
        if not key:
            skipped += 1
            continue

        try:
            desc_cls = load_description_class(key)
        except Exception:
            skipped += 1
            continue

        if not desc_cls.supports_rating:
            skipped += 1
            continue

        try:
            result = desc_cls(row).get_rating_status()
        except Exception as exc:
            log.warning('sync-rating error for data id=%s: %s', row.id, exc)
            errors += 1
            continue

        if result is None:
            skipped += 1
            continue

        row.is_rated    = result['is_rated']
        row.rating_note = result.get('note')
        updated += 1

        if verbose:
            click.echo(
                f'  [{row.id}] {row.name}: '
                f'{"rated" if row.is_rated else "unrated"}'
                + (f' — {row.rating_note}' if row.rating_note else '')
            )

    session.commit()
    click.echo(
        f'sync-rating complete: {updated} updated, {errors} errors, '
        f'{skipped} skipped (no rating support or missing path).'
    )
