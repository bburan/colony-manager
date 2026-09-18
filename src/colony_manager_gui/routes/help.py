"""In-app help pages.

Three views over the same Markdown topics (see
:mod:`colony_manager_gui.helpdocs`):

* ``/help/`` — the index, grouped by section.
* ``/help/<slug>`` — one topic as a full page, with a contents sidebar.
* ``/help/<slug>/panel`` — the same topic as a modal body, which is what the
  ``?`` button on every page requests so a reader keeps their place.
"""
from flask import Blueprint, abort, current_app, render_template, request, Response

from .. import helpdocs

help_bp = Blueprint('help', __name__)


def _topics():
    """Load topics, re-reading from disk while debugging.

    Mirrors how Jinja templates behave in dev: edit a ``.md`` file, reload
    the page, see the change. In production the parse happens once.
    """
    return helpdocs.load_topics(reload=current_app.debug)


def _get_topic(slug):
    topic = _topics().get(slug)
    if topic is None:
        abort(404, description=f'No help topic named "{slug}".')
    return topic


@help_bp.route('/')
def index() -> Response | str:
    topics = _topics()
    return render_template(
        'help_index.html',
        sections=helpdocs.topics_by_section(topics),
        total=len(topics),
    )


@help_bp.route('/<slug>')
def view_topic(slug) -> Response | str:
    topics = _topics()
    topic = _get_topic(slug)
    return render_template(
        'help_topic.html',
        topic=topic,
        see_also=[topics[s] for s in topic.see_also if s in topics],
        sections=helpdocs.topics_by_section(topics),
    )


@help_bp.route('/<slug>/panel')
def topic_panel(slug) -> Response | str:
    """Modal body for the ``?`` buttons.

    ``anchor`` scrolls the modal to one heading within the topic, so a
    button next to a specific control can point at the paragraph that
    explains it rather than the top of the page.
    """
    topic = _get_topic(slug)
    return render_template(
        'partials/help_modal.html',
        topic=topic,
        anchor=request.args.get('anchor', ''),
    )
