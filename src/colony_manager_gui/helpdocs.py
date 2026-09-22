"""Loading and rendering for the in-app help pages.

Help content is plain Markdown. Topics come from two places:

* **Built-in** — ``colony_manager_gui/help/*.md``, one file per topic, each
  with a small front-matter block (see :func:`parse_front_matter`).
* **Registry-supplied** — the host's description-registry module may export
  a ``HELP_TOPICS`` list, letting a deployment document its own experiment
  types without colony-manager knowing they exist. See
  ``colony_manager.datatypes.get_registry_help_topics``.

Rendering deliberately uses the small Markdown subset implemented here
rather than a third-party library. The Docker entrypoint reinstalls the
package with ``--no-deps`` at container start, so a new runtime dependency
would need an image rebuild to land — not a trade worth making for help
text. The subset covers headings, paragraphs, nested lists, fenced code,
blockquotes, pipe tables, horizontal rules, and inline emphasis / code /
links. Everything is HTML-escaped first, so Markdown source can never
inject markup.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from markupsafe import Markup, escape

from colony_manager.datatypes import get_registry_help_topics


HELP_DIR = Path(__file__).parent / 'help'

# Index grouping order. Sections not listed here sort alphabetically after
# these; 'Data types' is near the end because it is where registry-supplied
# topics land by default and it grows with the deployment, not with the app.
# 'Changelog' is pinned last so a registry section can't sort above it.
SECTION_ORDER = [
    'Getting started',
    'Colony',
    'Histology',
    'Data files',
    'Administration',
    'Data types',
    'Changelog',
]

# URL schemes a Markdown link is allowed to use. Anything else renders as
# plain text — help content is developer-authored, but a typo'd
# ``javascript:`` link should fail closed rather than ship.
_SAFE_LINK = re.compile(r'^(?:https?://|mailto:|/|#)')


# ---------------------------------------------------------------------------
# Topic model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HelpTopic:
    """One help page."""

    slug: str
    title: str
    body: str
    summary: str = ''
    section: str = 'Getting started'
    order: int = 100
    #: ``'app'`` for a built-in topic, ``'registry'`` for one contributed by
    #: the description registry. The index labels the latter so it is obvious
    #: which docs travel with the deployment's data plugin.
    source: str = 'app'
    #: Other topics worth reading next, as slugs. Unresolvable slugs are
    #: dropped at render time rather than 404-ing the page they sit on.
    see_also: tuple = field(default_factory=tuple)

    @property
    def html(self):
        return render_markdown(self.body)

    @property
    def headings(self):
        """``[(level, text, anchor), ...]`` for the on-page contents list."""
        return extract_headings(self.body)


def parse_front_matter(text):
    """Split a leading ``---`` delimited metadata block off *text*.

    The block is a simple ``key: value`` list — not YAML, and deliberately
    so; the only values help topics need are strings and one integer::

        ---
        title: The animal list
        section: Colony
        order: 10
        summary: Filtering, sorting and bulk-assigning animals.
        see_also: animal-detail, data-files
        ---

    Returns ``(metadata_dict, body)``. A file with no block yields an empty
    dict and the original text.
    """
    if not text.startswith('---'):
        return {}, text
    lines = text.splitlines()
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == '---')
    except StopIteration:
        return {}, text

    meta = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(':')
        if not sep:
            continue
        meta[key.strip().lower()] = value.strip()
    return meta, '\n'.join(lines[end + 1:]).lstrip('\n')


def _topic_from_file(path):
    meta, body = parse_front_matter(path.read_text(encoding='utf-8'))
    see_also = tuple(
        s.strip() for s in meta.get('see_also', '').split(',') if s.strip()
    )
    try:
        order = int(meta.get('order', 100))
    except ValueError:
        order = 100
    return HelpTopic(
        slug=path.stem,
        title=meta.get('title') or path.stem.replace('-', ' ').capitalize(),
        body=body,
        summary=meta.get('summary', ''),
        section=meta.get('section', 'Getting started'),
        order=order,
        source='app',
        see_also=see_also,
    )


_CACHE = None


def load_topics(reload=False):
    """Return ``{slug: HelpTopic}`` for every topic the app can serve.

    Built-in topics win a slug collision with a registry-supplied one — the
    app's own pages must stay reachable whatever a plugin is named.

    Parameters
    ----------
    reload : bool
        Re-read from disk instead of using the process-wide cache. The
        routes pass ``current_app.debug`` so editing a ``.md`` file shows up
        on the next request during development, exactly like editing a
        template.
    """
    global _CACHE
    if _CACHE is not None and not reload:
        return _CACHE

    topics = {}
    for path in sorted(HELP_DIR.glob('*.md')):
        topic = _topic_from_file(path)
        topics[topic.slug] = topic

    # A registry that fails to import contributes nothing rather than taking
    # the help pages down with it; one that ships *malformed* HELP_TOPICS
    # raises, and that is deliberate (see get_registry_help_topics).
    for entry in get_registry_help_topics():
        if entry['slug'] in topics:
            continue
        topics[entry['slug']] = HelpTopic(
            slug=entry['slug'],
            title=entry['title'],
            body=entry['body'],
            summary=entry['summary'],
            section=entry['section'],
            order=entry['order'],
            source='registry',
        )

    _CACHE = topics
    return topics


def topics_by_section(topics):
    """Group ``{slug: HelpTopic}`` into ``[(section, [topic, ...]), ...]``."""
    sections = {}
    for topic in topics.values():
        sections.setdefault(topic.section, []).append(topic)

    def section_key(name):
        try:
            return (0, SECTION_ORDER.index(name), '')
        except ValueError:
            return (1, 0, name.lower())

    return [
        (name, sorted(items, key=lambda t: (t.order, t.title.lower())))
        for name, items in sorted(sections.items(), key=lambda kv: section_key(kv[0]))
    ]


def topic_for_description_class(key):
    """Return the help slug a description-class key documents itself with.

    ``key`` is a ``DataType.description_class`` value. Returns ``None`` when
    the registry is unset, the key is unknown, the class declares no
    ``help_topic``, or the slug it declares resolves to nothing — every one
    of which means "render no help button", not "raise".
    """
    if not key:
        return None
    try:
        from colony_manager.datatypes import load_description_class
        slug = getattr(load_description_class(key), 'help_topic', None)
    except Exception:
        return None
    return slug if slug in load_topics() else None


# ---------------------------------------------------------------------------
# Markdown subset renderer
# ---------------------------------------------------------------------------

def slugify(text):
    """Turn heading text into a stable ``id`` for deep links."""
    out = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return out or 'section'


def extract_headings(text):
    """Return ``[(level, text, anchor), ...]`` for h2/h3 headings in *text*."""
    headings = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith('```'):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r'^(#{2,3})\s+(.+?)\s*$', line)
        if m:
            heading = m.group(2)
            headings.append((len(m.group(1)), heading, slugify(heading)))
    return headings


def render_inline(text):
    """Render the inline span syntax of one already-unescaped line."""
    out = escape(text)

    # Pull code spans out before emphasis so `**` inside `code` survives.
    spans = []

    def stash(match):
        spans.append(match.group(1))
        return f'\x00{len(spans) - 1}\x00'

    out = re.sub(r'`([^`]+)`', stash, str(out))

    def link(match):
        label, url = match.group(1), match.group(2)
        if not _SAFE_LINK.match(url):
            return label
        return f'<a href="{url}">{label}</a>'

    out = re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', link, out)
    out = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', out)
    out = re.sub(r'(?<![\w*])\*([^*\n]+)\*(?![\w*])', r'<em>\1</em>', out)
    out = re.sub(r'(?<![\w_])_([^_\n]+)_(?![\w_])', r'<em>\1</em>', out)

    out = re.sub(r'\x00(\d+)\x00', lambda m: f'<code>{spans[int(m.group(1))]}</code>', out)
    return out


_BULLET = re.compile(r'^(\s*)([-*])\s+(.*)$')
_NUMBER = re.compile(r'^(\s*)(\d+)\.\s+(.*)$')
_TABLE_RULE = re.compile(r'^\s*\|?[\s:|-]+\|[\s:|-]*$')


def _split_row(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def render_markdown(text):
    """Render the supported Markdown subset to Bootstrap-friendly HTML."""
    lines = text.splitlines()
    out = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Fenced code
        if stripped.startswith('```'):
            i += 1
            block = []
            while i < n and not lines[i].strip().startswith('```'):
                block.append(lines[i])
                i += 1
            i += 1  # closing fence (or EOF)
            out.append(
                '<pre class="help-code"><code>'
                + str(escape('\n'.join(block)))
                + '</code></pre>'
            )
            continue

        # Horizontal rule
        if re.match(r'^(-{3,}|\*{3,})$', stripped):
            out.append('<hr>')
            i += 1
            continue

        # Heading
        m = re.match(r'^(#{1,6})\s+(.+?)\s*$', stripped)
        if m:
            level = len(m.group(1))
            body = m.group(2)
            anchor = f' id="{slugify(body)}"' if level in (2, 3) else ''
            out.append(f'<h{level}{anchor}>{render_inline(body)}</h{level}>')
            i += 1
            continue

        # Pipe table: a header row followed by a |---|---| rule
        if '|' in stripped and i + 1 < n and _TABLE_RULE.match(lines[i + 1]):
            header = _split_row(stripped)
            i += 2
            rows = []
            while i < n and '|' in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            head = ''.join(f'<th>{render_inline(c)}</th>' for c in header)
            body = ''.join(
                '<tr>' + ''.join(f'<td>{render_inline(c)}</td>' for c in row) + '</tr>'
                for row in rows
            )
            out.append(
                '<div class="table-responsive">'
                '<table class="table table-sm align-middle help-table">'
                f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
            )
            continue

        # Blockquote
        if stripped.startswith('>'):
            block = []
            while i < n and lines[i].strip().startswith('>'):
                block.append(lines[i].strip().lstrip('>').strip())
                i += 1
            out.append(
                '<blockquote class="help-note">'
                + ' '.join(render_inline(b) for b in block)
                + '</blockquote>'
            )
            continue

        # Lists (bullet or numbered, nested by indent)
        if _BULLET.match(line) or _NUMBER.match(line):
            html, i = _render_list(lines, i)
            out.append(html)
            continue

        # Paragraph: run of non-blank lines that start no other block
        para = []
        while i < n and lines[i].strip():
            nxt = lines[i]
            if (nxt.strip().startswith(('```', '>', '#'))
                    or _BULLET.match(nxt) or _NUMBER.match(nxt)):
                break
            para.append(nxt.strip())
            i += 1
        if para:
            out.append('<p>' + render_inline(' '.join(para)) + '</p>')
        else:
            i += 1

    return Markup(''.join(out))


def _render_list(lines, start):
    """Render one list (and any nested sub-lists) starting at *start*.

    Returns ``(html, next_index)``. Nesting is by leading whitespace: any
    item indented further than the one that opened the list starts a
    sub-list, which recurses.
    """
    n = len(lines)
    first = _BULLET.match(lines[start]) or _NUMBER.match(lines[start])
    base_indent = len(first.group(1))
    ordered = _NUMBER.match(lines[start]) is not None

    items = []
    i = start
    while i < n:
        line = lines[i]
        if not line.strip():
            # A blank line ends the list unless the next line continues it —
            # same indent or deeper, and the same kind of marker. A bullet
            # list followed by a numbered one is two lists, not one.
            nxt = None
            if i + 1 < n:
                nxt = _BULLET.match(lines[i + 1]) or _NUMBER.match(lines[i + 1])
            if nxt is not None and len(nxt.group(1)) >= base_indent and (
                    len(nxt.group(1)) > base_indent
                    or (_NUMBER.match(lines[i + 1]) is not None) == ordered):
                i += 1
                continue
            break

        m = _BULLET.match(line) or _NUMBER.match(line)
        if m is None:
            # Lazy continuation of the previous item's text.
            if items and len(line) - len(line.lstrip()) > base_indent:
                items[-1][0] += ' ' + line.strip()
                i += 1
                continue
            break

        indent = len(m.group(1))
        if indent < base_indent:
            break
        if indent == base_indent and (_NUMBER.match(line) is not None) != ordered:
            break
        if indent > base_indent:
            sub_html, i = _render_list(lines, i)
            if items:
                items[-1][1].append(sub_html)
            continue

        items.append([m.group(3).strip(), []])
        i += 1

    tag = 'ol' if ordered else 'ul'
    body = ''.join(
        f'<li>{render_inline(text)}{"".join(subs)}</li>' for text, subs in items
    )
    return f'<{tag}>{body}</{tag}>', i
