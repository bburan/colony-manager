// Paste-as-Markdown for the text-note editor
// (partials/text_note_modal.html, services/text_notes.py).
//
// Rich text pasted from Word or Outlook arrives as Office's HTML dialect:
// lists are not <ul>/<ol> but paragraphs tagged ``mso-list:l0 level2`` with
// the bullet glyph as literal text, bold is often a styled <span>, and the
// whole thing is wrapped in conditional comments and <o:p> elements. This
// file cleans that up into ordinary HTML and hands it to Turndown (loaded
// from the CDN in base.html), whose output the server renders with
// ``helpdocs.render_markdown``. Anything Turndown can't express in the
// subset that renderer supports (images, colours, fonts) is dropped.
//
// Plain-text pastes are left to the browser.
(function () {
    'use strict';

    const WORD_LIST = /mso-list:\s*(l\d+)\s+level(\d+)/i;
    // An ordered marker: ``1.``, ``1)``, ``(a)``, ``iv.``, ``B.``.
    const ORDERED_MARKER = /^\(?([0-9]+|[a-z]|[ivxlcdm]+)[.)]/i;

    function unwrap(el) {
        el.replaceWith(...el.childNodes);
    }

    function stripOfficeNoise(body) {
        // Conditional comments (``<!--[if !supportLists]-->``) and the
        // StartFragment markers.
        const walker = document.createTreeWalker(body, NodeFilter.SHOW_COMMENT);
        const comments = [];
        while (walker.nextNode()) comments.push(walker.currentNode);
        comments.forEach(c => c.remove());

        body.querySelectorAll('style, script, meta, link, title, img').forEach(el => el.remove());
        // Namespaced Office elements: <o:p> holds real text (often just
        // an &nbsp;), the VML/Word ones (<v:shape>, <w:sdt>…) are
        // drawing/field scaffolding.
        Array.from(body.querySelectorAll('*'))
            .filter(el => el.tagName.includes(':'))
            .forEach(el => {
                if (el.tagName.toLowerCase().startsWith('o:')) unwrap(el);
                else el.remove();
            });
    }

    function styleOf(el) {
        return (el.getAttribute('style') || '').toLowerCase();
    }

    // Word bolds/italicises with inline styles as often as with <b>/<i>.
    function promoteStyledSpans(body) {
        body.querySelectorAll('span[style]').forEach(span => {
            const style = styleOf(span);
            let inner = null;
            // Skip when already inside <b>/<i>: nesting would emit
            // ``****text****``.
            if (/font-weight:\s*(bold|[6-9]00)/.test(style) && !span.closest('b, strong')) {
                inner = document.createElement('strong');
            }
            if (/font-style:\s*italic/.test(style) && !span.closest('i, em')) {
                const em = document.createElement('em');
                if (inner) inner.appendChild(em); else inner = em;
            }
            if (!inner) return;
            const deepest = inner.querySelector('em') || inner;
            deepest.append(...span.childNodes);
            span.appendChild(inner);
        });
        body.querySelectorAll('p.MsoTitle').forEach(p => {
            const h = document.createElement('h1');
            h.append(...p.childNodes);
            p.replaceWith(h);
        });
    }

    // Rebuild Word's paragraph-per-item lists as nested <ul>/<ol>.
    function rebuildWordLists(body) {
        const isListPara = el => el && el.tagName === 'P' && WORD_LIST.test(styleOf(el));
        const paras = Array.from(body.querySelectorAll('p')).filter(isListPara);
        const seen = new Set();
        for (const first of paras) {
            if (seen.has(first)) continue;
            // A run of adjacent list paragraphs is one list.
            const run = [];
            for (let el = first; isListPara(el); el = el.nextElementSibling) {
                run.push(el);
                seen.add(el);
            }
            const root = document.createElement('div');
            const stack = [];  // [{level, list}]
            for (const p of run) {
                const level = parseInt(styleOf(p).match(WORD_LIST)[2], 10);
                const marker = p.querySelector('span[style*="mso-list:ignore" i]');
                const ordered = marker ? ORDERED_MARKER.test(marker.textContent.trim()) : false;
                if (marker) marker.remove();

                while (stack.length && stack[stack.length - 1].level > level) stack.pop();
                let top = stack[stack.length - 1];
                if (!top || top.level < level) {
                    const list = document.createElement(ordered ? 'ol' : 'ul');
                    if (top) {
                        const parentItem = top.list.lastElementChild || top.list.appendChild(document.createElement('li'));
                        parentItem.appendChild(list);
                    } else {
                        root.appendChild(list);
                    }
                    top = {level, list};
                    stack.push(top);
                }
                const li = document.createElement('li');
                li.append(...p.childNodes);
                top.list.appendChild(li);
            }
            first.before(...root.childNodes);
            run.forEach(p => p.remove());
        }
    }

    function cellText(service, cell) {
        return service.turndown(cell.innerHTML)
            .replace(/\s*\n+\s*/g, ' ')
            .replace(/\|/g, '\\|')
            .trim();
    }

    // Markdown tables need a header row; Word/Outlook tables never mark
    // one, so the first row is promoted. Cells are flattened to a single
    // line, since a newline would end the table row.
    function addTableRule(service) {
        service.addRule('pipeTable', {
            filter: 'table',
            replacement: function (content, node) {
                const rows = Array.from(node.rows)
                    .map(tr => Array.from(tr.cells).map(c => cellText(service, c)))
                    .filter(cells => cells.some(c => c));
                if (!rows.length) return '';
                const width = Math.max(...rows.map(r => r.length));
                const line = cells => '| ' + Array.from({length: width}, (_, i) => cells[i] || '').join(' | ') + ' |';
                const out = [line(rows[0]), line(Array(width).fill('---'))];
                rows.slice(1).forEach(r => out.push(line(r)));
                return '\n\n' + out.join('\n') + '\n\n';
            },
        });
    }

    function makeService() {
        const service = new TurndownService({
            headingStyle: 'atx',
            bulletListMarker: '-',
            codeBlockStyle: 'fenced',
            emDelimiter: '*',
            strongDelimiter: '**',
            hr: '---',
        });
        addTableRule(service);
        return service;
    }

    function htmlToMarkdown(html) {
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const body = doc.body;
        stripOfficeNoise(body);
        promoteStyledSpans(body);
        rebuildWordLists(body);
        return makeService().turndown(body.innerHTML)
            .replace(/ /g, ' ')
            // A <br> in an otherwise empty Outlook <div> leaves a line of
            // bare spaces; elsewhere keep two trailing spaces (a hard break).
            .replace(/^[ \t]+$/gm, '')
            .replace(/[ \t]+$/gm, m => (m.length >= 2 ? '  ' : ''))
            .replace(/\n{3,}/g, '\n\n')
            .trim();
    }

    function insertAtCursor(textarea, text) {
        textarea.focus();
        // execCommand keeps the paste on the textarea's undo stack;
        // setRangeText is the fallback where it's unsupported.
        if (!document.execCommand || !document.execCommand('insertText', false, text)) {
            textarea.setRangeText(text, textarea.selectionStart, textarea.selectionEnd, 'end');
            textarea.dispatchEvent(new Event('input', {bubbles: true}));
        }
    }

    window.colonyMarkdownPaste = {htmlToMarkdown: htmlToMarkdown};

    // Alpine component for the note editor's textarea + Write/Preview tabs.
    window.colonyTextNoteEditor = function () {
        return {
            tab: 'write',
            onPaste(event) {
                const data = event.clipboardData;
                const html = data && data.getData('text/html');
                if (!html || typeof TurndownService === 'undefined') return;
                let markdown;
                try {
                    markdown = htmlToMarkdown(html);
                } catch (err) {
                    console.error('Markdown conversion failed; pasting plain text.', err);
                    return;
                }
                if (!markdown) return;
                event.preventDefault();
                insertAtCursor(event.target, markdown);
            },
        };
    };
})();
