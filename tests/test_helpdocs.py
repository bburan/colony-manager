"""Unit tests for the in-app help system (no DB, no app factory).

Three things are worth pinning down:

* the Markdown subset renders what the help topics actually use, and
  escapes everything else — the renderer is hand-rolled precisely so the
  app needs no runtime Markdown dependency, which makes it ours to test;
* every shipped topic parses, and every cross-link between topics resolves
  — a broken ``see_also`` or a ``/help/<slug>`` typo would otherwise only
  surface as a 404 for a user;
* the registry contract for plugin-supplied topics accepts what the host
  package is meant to send and rejects what it is not.
"""
import sys
import types

import pytest

from colony_manager_gui import helpdocs


# ---------------------------------------------------------------------------
# Markdown subset
# ---------------------------------------------------------------------------

def test_headings_get_anchors_for_the_contents_list():
    html = str(helpdocs.render_markdown('## Filters and sorting\n'))
    assert '<h2 id="filters-and-sorting">Filters and sorting</h2>' == html


def test_inline_spans():
    html = str(helpdocs.render_markdown(
        'A **bold** and *em* and `code` and [link](/animals).'))
    assert '<strong>bold</strong>' in html
    assert '<em>em</em>' in html
    assert '<code>code</code>' in html
    assert '<a href="/animals">link</a>' in html


def test_emphasis_inside_a_code_span_is_left_alone():
    html = str(helpdocs.render_markdown('Use `a**b**c` verbatim.'))
    assert '<code>a**b**c</code>' in html
    assert '<strong>' not in html


def test_html_in_source_is_escaped():
    html = str(helpdocs.render_markdown('Danger <script>alert(1)</script>.'))
    assert '<script>' not in html
    assert '&lt;script&gt;' in html


def test_unsafe_link_scheme_degrades_to_plain_text():
    html = str(helpdocs.render_markdown('[click](javascript:alert(1))'))
    assert 'javascript:' not in html
    assert 'click' in html


def test_a_bullet_list_followed_by_a_numbered_one_stays_two_lists():
    html = str(helpdocs.render_markdown('- one\n- two\n\n1. first\n2. second\n'))
    assert html.count('<ul>') == 1
    assert html.count('<ol>') == 1
    assert html.index('</ul>') < html.index('<ol>')


def test_nested_bullets_nest():
    html = str(helpdocs.render_markdown('- outer\n  - inner\n- outer2\n'))
    assert '<li>outer<ul><li>inner</li></ul></li>' in html


def test_pipe_table_renders_a_scrollable_table():
    html = str(helpdocs.render_markdown('| A | B |\n|---|---|\n| 1 | 2 |\n'))
    assert 'table-responsive' in html
    assert '<th>A</th><th>B</th>' in html
    assert '<td>1</td><td>2</td>' in html


def test_fenced_code_is_not_marked_up():
    html = str(helpdocs.render_markdown('```\n- not a list **not bold**\n```\n'))
    assert '<li>' not in html
    assert '<strong>' not in html
    assert '- not a list **not bold**' in html


def test_extract_headings_ignores_fenced_content():
    body = '## Real\n\n```\n## Not a heading\n```\n'
    assert helpdocs.extract_headings(body) == [(2, 'Real', 'real')]


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------

def test_front_matter_is_split_off():
    meta, body = helpdocs.parse_front_matter(
        '---\ntitle: A page\norder: 5\n---\n\nBody text.\n')
    assert meta == {'title': 'A page', 'order': '5'}
    # splitlines()/join drops the file's trailing newline; nothing downstream
    # cares, and the block renderer is whitespace-tolerant either way.
    assert body == 'Body text.'


def test_a_file_without_front_matter_is_all_body():
    meta, body = helpdocs.parse_front_matter('# Heading\n')
    assert meta == {}
    assert body == '# Heading\n'


# ---------------------------------------------------------------------------
# The topics actually shipped
# ---------------------------------------------------------------------------

def _builtin_topics():
    return {p.stem: helpdocs._topic_from_file(p)
            for p in helpdocs.HELP_DIR.glob('*.md')}


def test_every_shipped_topic_has_a_title_and_renders():
    topics = _builtin_topics()
    assert topics, 'no built-in help topics found'
    for slug, topic in topics.items():
        assert topic.title, slug
        assert topic.section, slug
        assert str(topic.html).strip(), slug


def test_see_also_slugs_resolve():
    topics = _builtin_topics()
    for slug, topic in topics.items():
        for other in topic.see_also:
            assert other in topics, f'{slug}: see_also "{other}" does not exist'


def test_in_body_help_links_resolve():
    """``/help/<slug>`` links between topics must point at a real topic.

    Links to a slug this package does not ship are allowed only for the
    ``mmm-db-`` prefix, which the deployment's data plugin contributes at
    runtime (see colony_manager.datatypes.get_registry_help_topics), and
    for ``/help/`` itself, the index.
    """
    import re
    topics = _builtin_topics()
    for slug, topic in topics.items():
        for target in re.findall(r'\]\(/help/([a-z0-9-]*)\)', topic.body):
            if target == '' or target.startswith('mmm-db-'):
                continue
            assert target in topics, f'{slug}: link to unknown topic "{target}"'


def test_page_help_buttons_point_at_real_topics():
    """Every ``macros.help_button('slug')`` in a template must resolve.

    The macro cannot validate its own argument — it has no view of the
    topic list — so a typo would ship as a 404 behind a ``?`` button.
    """
    import re
    from pathlib import Path
    topics = _builtin_topics()
    templates = Path(helpdocs.__file__).parent / 'templates'
    found = 0
    for path in templates.rglob('*.html'):
        for slug in re.findall(r"help_button\('([a-z0-9-]+)'", path.read_text(encoding='utf-8')):
            found += 1
            assert slug in topics, f'{path.name}: help_button("{slug}") is not a topic'
    assert found > 10, 'expected a help button on every page type'


# ---------------------------------------------------------------------------
# Registry-supplied topics
# ---------------------------------------------------------------------------

@pytest.fixture
def registry_module(monkeypatch):
    """Install a synthetic registry module and point the env var at it."""
    module = types.ModuleType('_test_help_registry')
    sys.modules['_test_help_registry'] = module
    monkeypatch.setenv('COLONY_MANAGER_DESCRIPTION_REGISTRY', '_test_help_registry')
    yield module
    sys.modules.pop('_test_help_registry', None)


def test_registry_without_help_topics_contributes_nothing(registry_module):
    from colony_manager.datatypes import get_registry_help_topics
    assert get_registry_help_topics() == []


def test_unset_registry_contributes_nothing(monkeypatch):
    monkeypatch.delenv('COLONY_MANAGER_DESCRIPTION_REGISTRY', raising=False)
    from colony_manager.datatypes import get_registry_help_topics
    assert get_registry_help_topics() == []


def test_inline_body_topic_is_normalized(registry_module):
    from colony_manager.datatypes import get_registry_help_topics
    registry_module.HELP_TOPICS = [
        {'slug': 'plugin-thing', 'title': 'A Thing', 'body': '# A Thing\n'},
    ]
    assert get_registry_help_topics() == [{
        'slug': 'plugin-thing',
        'title': 'A Thing',
        'summary': '',
        'section': 'Data types',
        'order': 100,
        'body': '# A Thing\n',
    }]


def test_path_topic_is_read_from_disk(registry_module, tmp_path):
    from colony_manager.datatypes import get_registry_help_topics
    md = tmp_path / 'thing.md'
    md.write_text('# From disk\n', encoding='utf-8')
    registry_module.HELP_TOPICS = [
        {'slug': 'plugin-thing', 'title': 'A Thing', 'path': md,
         'section': 'Experiment data', 'order': 20, 'summary': 'Blurb.'},
    ]
    (topic,) = get_registry_help_topics()
    assert topic['body'] == '# From disk\n'
    assert topic['section'] == 'Experiment data'
    assert topic['order'] == 20
    assert topic['summary'] == 'Blurb.'


@pytest.mark.parametrize('entry', [
    {'title': 'No slug', 'body': ''},
    {'slug': 'Bad Slug', 'title': 'x', 'body': ''},
    {'slug': 'ok', 'body': ''},
    {'slug': 'ok', 'title': 'x'},                        # neither body nor path
    {'slug': 'ok', 'title': 'x', 'body': '', 'path': 'p'},  # both
])
def test_malformed_topics_raise(registry_module, entry):
    from colony_manager.datatypes import get_registry_help_topics
    registry_module.HELP_TOPICS = [entry]
    with pytest.raises(RuntimeError):
        get_registry_help_topics()


def test_duplicate_slugs_raise(registry_module):
    from colony_manager.datatypes import get_registry_help_topics
    registry_module.HELP_TOPICS = [
        {'slug': 'dup', 'title': 'One', 'body': ''},
        {'slug': 'dup', 'title': 'Two', 'body': ''},
    ]
    with pytest.raises(RuntimeError):
        get_registry_help_topics()


def test_builtin_topic_wins_a_slug_collision(registry_module, monkeypatch):
    """A plugin must not be able to shadow the app's own help pages."""
    from colony_manager.datatypes import reset_registry_cache
    reset_registry_cache()
    builtin = next(iter(_builtin_topics()))
    registry_module.HELP_TOPICS = [
        {'slug': builtin, 'title': 'Hijacked', 'body': 'nope'},
    ]
    topics = helpdocs.load_topics(reload=True)
    assert topics[builtin].source == 'app'
    assert topics[builtin].title != 'Hijacked'


def test_registry_topics_are_merged_and_labelled(registry_module):
    registry_module.HELP_TOPICS = [
        {'slug': 'plugin-thing', 'title': 'A Thing', 'body': '# A Thing\n',
         'section': 'Experiment data'},
    ]
    topics = helpdocs.load_topics(reload=True)
    assert topics['plugin-thing'].source == 'registry'
    sections = dict(helpdocs.topics_by_section(topics))
    assert 'Experiment data' in sections


def test_sections_sort_known_first_then_alphabetically():
    topics = {
        'a': helpdocs.HelpTopic('a', 'A', '', section='Zebra'),
        'b': helpdocs.HelpTopic('b', 'B', '', section='Colony'),
        'c': helpdocs.HelpTopic('c', 'C', '', section='Getting started'),
        'd': helpdocs.HelpTopic('d', 'D', '', section='Aardvark'),
    }
    names = [name for name, _ in helpdocs.topics_by_section(topics)]
    assert names == ['Getting started', 'Colony', 'Aardvark', 'Zebra']
