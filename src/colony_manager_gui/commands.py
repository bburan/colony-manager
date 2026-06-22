"""Flask CLI command groups for colony-manager management tasks."""
import logging

import click
from flask.cli import with_appcontext

from colony_manager.models import DataType

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
    from colony_manager_gui.sync import sync_rating_status

    datatype_id = None
    if datatype_name:
        dt = db.session.scalars(
            select(DataType).where(DataType.name == datatype_name)
        ).first()
        if dt is None:
            raise click.ClickException(f'DataType not found: {datatype_name}')
        datatype_id = dt.id

    counts = sync_rating_status(filter_datatype_id=datatype_id)

    if verbose:
        click.echo(
            f'sync-rating complete: {counts["updated"]} updated, '
            f'{counts["errors"]} errors, {counts["skipped"]} skipped.'
        )
    else:
        click.echo(
            f'sync-rating complete: {counts["updated"]} updated, '
            f'{counts["errors"]} errors, {counts["skipped"]} skipped '
            f'(no rating support or missing path).'
        )
