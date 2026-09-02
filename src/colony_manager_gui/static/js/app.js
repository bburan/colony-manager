// Attach the CSRF token to every HTMX request so Flask-WTF's
// CSRFProtect accepts non-form POSTs (PUT/DELETE/PATCH too).
(function () {
    const tokenMeta = document.querySelector('meta[name="csrf-token"]');
    if (!tokenMeta) return;
    const token = tokenMeta.getAttribute('content');
    document.body.addEventListener('htmx:configRequest', function (evt) {
        evt.detail.headers['X-CSRFToken'] = token;
    });
})();

// Before an htmx request that targets #modalBody, swap in a spinner
// and open the modal so the user has immediate feedback. The actual
// form content arrives via htmx's normal swap.
document.body.addEventListener('htmx:beforeRequest', function (evt) {
    const target = evt.detail.target;
    if (!target || target.id !== 'modalBody') return;
    target.innerHTML = `
        <div class="d-flex justify-content-center p-5">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
        </div>`;
    const editModalElement = document.getElementById('editModal');
    const modalInstance = bootstrap.Modal.getOrCreateInstance(editModalElement);
    if (!editModalElement.classList.contains('show')) {
        modalInstance.show();
    }
});

// After the swap completes, ensure the modal is visible (covers
// edge cases where beforeRequest did not fire — e.g. server-side
// triggered swaps).
document.body.addEventListener('htmx:afterOnLoad', function(evt) {
    if (evt.detail.target.id === 'modalBody') {
        const editModalElement = document.getElementById('editModal');
        const modalInstance = bootstrap.Modal.getOrCreateInstance(editModalElement);
        if (!editModalElement.classList.contains('show')) {
            modalInstance.show();
        }
    }
});

document.body.addEventListener('closeModal', function(evt) {
    const editModalElement = document.getElementById('editModal');
    const modalInstance = bootstrap.Modal.getInstance(editModalElement);
    if (modalInstance) {
        modalInstance.hide();
    }
});

document.body.addEventListener('htmx:beforeSwap', function(evt) {
    if (evt.detail.xhr.status >= 400) {
        evt.detail.shouldSwap = true;
    }
});

// Alpine component used by the file-upload modal
// (partials/upload_modal.html). Lives on ``window`` so the
// x-data attribute can reference it after HTMX swaps the modal
// body into the DOM. Stateless — re-rendering the modal is
// free.
//
// Tracks two pieces of UI state:
//   * ``targets`` — chip picker (Animal / Ear instances).
//   * ``files``   — one entry per file the user picked, with a
//                   per-file ``notes`` string. Repopulated on
//                   each change of the underlying file input,
//                   so re-picking files always re-syncs the
//                   notes rows.
window.colonyUploadModal = function (initialId, initialLabel) {
    // ``rawFiles`` lives in the closure, NOT inside the
    // x-data object. Alpine's reactivity wraps everything it
    // can reach with a Proxy, and Proxy-wrapped File objects
    // lose their prototype-chain getters — ``proxyFile.name``
    // returns ``undefined``. Keeping the File instances out of
    // the reactive tree preserves their getters. The reactive
    // ``files`` array carries only the plain strings the
    // template renders; the two arrays stay in lockstep order.
    const rawFiles = [];
    return {
        targets: [{id: initialId, label: initialLabel}],
        // ``files`` is the visible staging list: one
        // ``{name, notes}`` per ``rawFiles[i]``. Browse and
        // drag-drop APPEND to both; the X button on each row
        // splices both. The underlying ``<input type=file>``
        // is synced from ``rawFiles`` only at form-submit time
        // (``onSubmit``) — meanwhile the input is cleared
        // after each browse so the user can re-pick the same
        // file later if they removed it from the list.
        files: [],
        // ``dragDepth`` is a counter rather than a boolean
        // because ``dragenter`` / ``dragleave`` fire on every
        // child element as the cursor moves around the drop
        // zone — toggling a boolean would flicker. The drop
        // zone is "active" iff depth > 0.
        dragDepth: 0,
        add(id, label) {
            if (this.targets.find(t => t.id === id)) return;
            this.targets.push({id: id, label: label});
            const results = document.getElementById('targetSearchResults');
            if (results) results.innerHTML = '';
            if (this.$refs.q) this.$refs.q.value = '';
        },
        remove(id) {
            if (this.targets.length <= 1) return;
            this.targets = this.targets.filter(t => t.id !== id);
        },
        _appendFiles(fileList) {
            for (const f of fileList) {
                rawFiles.push(f);
                this.files.push({name: f.name, notes: ''});
            }
        },
        onFilesChanged(event) {
            this._appendFiles(event.target.files);
            // Clear the input so a subsequent browse of the
            // same file still fires ``change`` (browsers
            // suppress the event when ``value`` is unchanged).
            event.target.value = '';
        },
        removeFile(idx) {
            this.files.splice(idx, 1);
            rawFiles.splice(idx, 1);
        },
        onDragEnter() { this.dragDepth += 1; },
        onDragLeave() {
            this.dragDepth = Math.max(0, this.dragDepth - 1);
        },
        onDrop(event) {
            this.dragDepth = 0;
            const dropped = event.dataTransfer && event.dataTransfer.files;
            if (!dropped || dropped.length === 0) return;
            this._appendFiles(dropped);
        },
        onPaste(event) {
            // Pull image items out of the clipboard payload.
            // Screenshot tools and "Copy image" produce a
            // synthetic File named ``image.png``; copying a
            // real file from the OS file manager preserves
            // its filename. Non-image clipboard data (plain
            // text into the notes input, for example) is
            // left alone so the default paste behaviour
            // still works.
            if (!event.clipboardData) return;
            const items = event.clipboardData.items;
            if (!items) return;
            const pasted = [];
            for (const item of items) {
                if (item.kind === 'file' && item.type.startsWith('image/')) {
                    const f = item.getAsFile();
                    if (f) pasted.push(f);
                }
            }
            if (pasted.length === 0) return;
            event.preventDefault();
            this._appendFiles(pasted);
        },
        onSubmit(event) {
            // Rebuild the input's FileList from the staged
            // array right before multipart serialization. If
            // JS is somehow disabled or this handler doesn't
            // run, the form still submits whatever the input
            // currently holds — a graceful fallback to the
            // pre-staging behaviour.
            const input = this.$refs.filesInput;
            if (!input) return;
            const dt = new DataTransfer();
            for (const f of rawFiles) dt.items.add(f);
            input.files = dt.files;
        },
    };
};

document.addEventListener('show.bs.popover', function (e) {
    const allPopovers = document.querySelectorAll('[data-bs-toggle="popover"]');
    allPopovers.forEach(el => {
        if (el !== e.target) {
            const instance = bootstrap.Popover.getInstance(el);
            if (instance) instance.hide();
        }
    });
});

// Popover content (title/data-bs-content) is rendered as raw HTML
// outside htmx's normal swap path, so hx-* attrs inside that content
// need to be registered manually once the tip is in the DOM.
document.addEventListener('shown.bs.popover', function (e) {
    const instance = bootstrap.Popover.getInstance(e.target);
    const tip = instance && instance.tip;
    if (tip && window.htmx) {
        htmx.process(tip);
    }
});

// Hide all popovers when a modal is about to show
document.addEventListener('show.bs.modal', function () {
    const allPopovers = document.querySelectorAll('[data-bs-toggle="popover"]');
    allPopovers.forEach(el => {
        const instance = bootstrap.Popover.getInstance(el);
        if (instance) instance.hide();
    });
});

// Initialize Bootstrap tooltips/popovers under ``root`` (defaults to
// the whole document). Idempotent: elements that already have an
// instance are skipped, so this is safe to call on htmx-swapped
// subtrees as well as on initial page load.
function initBootstrapWidgets(root) {
    root = root || document;
    const scope = (root.querySelectorAll) ? root : document;
    const tooltipTriggers = scope.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltipTriggers.forEach(el => {
        if (bootstrap.Tooltip.getInstance(el)) return;
        new bootstrap.Tooltip(el);
    });

    const popoverTriggers = scope.querySelectorAll('[data-bs-toggle="popover"]');
    popoverTriggers.forEach(element => {
        if (bootstrap.Popover.getInstance(element)) return;
        const popover = new bootstrap.Popover(element, {
            html: true,
            sanitize: false,
            customClass: 'popover-wide'
        });

        if (element.classList.contains('ajax-popover')) {
            let isFetched = false;
            element.addEventListener('show.bs.popover', function () {
                if (isFetched) return;
                fetch(this.getAttribute('data-id'))
                    .then(response => {
                        if (!response.ok) throw new Error('Network error');
                        return response.text();
                    })
                    .then(data => {
                        isFetched = true;
                        popover.setContent({'.popover-body': data});
                        popover.update();
                    })
                    .catch(err => {
                        popover.setContent({'.popover-body': 'Error loading content.'});
                        console.error('Popover Fetch Error:', err);
                    });
            });
        }
    });
}

document.addEventListener('DOMContentLoaded', function () {
    initBootstrapWidgets(document);
});

// Any content htmx swaps in needs its tooltips/popovers wired up too,
// otherwise they fall back to Bootstrap's defaults (html=false) and
// ``data-bs-content`` HTML renders as escaped text. ``htmx:load``
// fires per new element with ``evt.detail.elt`` pointing at it —
// unlike ``afterSwap``, this works for outerHTML swaps where the
// original swap target is detached before the event fires.
document.body.addEventListener('htmx:load', function (evt) {
    initBootstrapWidgets(evt.detail.elt);
});

// Dispose Bootstrap tooltips/popovers under ``root`` so their body-attached
// popups don't orphan when the trigger element is removed.
function disposeBootstrapWidgets(root) {
    if (!root || !root.querySelectorAll) return;
    const triggers = [root, ...root.querySelectorAll(
        '[data-bs-toggle="tooltip"], [data-bs-toggle="popover"]')];
    triggers.forEach(el => {
        const tip = bootstrap.Tooltip.getInstance(el);
        if (tip) tip.dispose();
        const pop = bootstrap.Popover.getInstance(el);
        if (pop) pop.dispose();
    });
}

// Before htmx swaps content out, tear down tooltips/popovers in the
// outgoing subtree. Otherwise a tooltip that's showing on the clicked
// element (e.g. a per-row action button swapped via outerHTML) stays
// stuck on screen after its trigger leaves the DOM.
document.body.addEventListener('htmx:beforeSwap', function (evt) {
    disposeBootstrapWidgets(evt.detail.target);
});

function markDirty(input) {
    // Access the form directly via the built-in 'form' property
    const activeForm = input.form;

    if (!activeForm) {
        console.error("Input is not linked to a form. Ensure form='id' is set correctly.");
        return;
    }

    const saveBtn = document.querySelector("#" + activeForm.id + "-save");

    elements = Array.from(activeForm.elements);
    let isDirty = elements.some(element => {
        if (element.type === 'checkbox' || element.type === 'radio') {
            return element.checked !== element.defaultChecked;
        } else if (element.tagName.toLowerCase() === 'select') {
            const optionsArray = Array.from(element.options);
            return optionsArray.some(option => option.selected !== option.defaultSelected);
        } else if (element.type !== 'button' && element.type !== 'submit' && element.type !== 'reset') {
            return element.value.trim() !== (element.defaultValue || "").trim();
        }
    });

    if (isDirty) {
        saveBtn.disabled = false;
        saveBtn.classList.add('is-dirty');
    } else {
        saveBtn.disabled = true;
        saveBtn.classList.remove('is-dirty');
    }
}

// The animal edit form exposes 'terminated' as its own checkbox, separate
// from 'termination_date'/'termination_reason' (the flag is the source of
// truth for is_active; historical animals may be terminated with no known
// date). Filling in a date or reason without also ticking the checkbox is
// an easy mistake, so nudge it on for the user — this never un-checks it,
// so explicitly clearing 'Terminated' to re-activate an animal still works.
function autoCheckTerminated(event) {
    const el = event.target;
    if (el.name !== 'termination_date' && el.name !== 'termination_reason') return;
    // QuerySelectField's blank option is valued "__None" (its allow_blank
    // default, see forms/animals.py), not "" — treat it as empty too.
    if (!el.value || el.value === '__None') return;
    const form = el.form;
    if (!form) return;
    const terminatedCheckbox = form.querySelector('[name="terminated"]');
    if (terminatedCheckbox && !terminatedCheckbox.checked) {
        terminatedCheckbox.checked = true;
    }
}
document.addEventListener('input', autoCheckTerminated);
document.addEventListener('change', autoCheckTerminated);

// The inverse: unchecking 'Terminated' clears termination_date/reason
// (the server does this too, in AnimalForm.populate_obj — this just
// keeps the form's display in sync so the user isn't left looking at a
// date/reason that's about to disappear on save).
function clearTerminationFieldsOnUncheck(event) {
    const el = event.target;
    if (el.name !== 'terminated' || el.checked) return;
    const form = el.form;
    if (!form) return;
    const dateInput = form.querySelector('[name="termination_date"]');
    const reasonSelect = form.querySelector('[name="termination_reason"]');
    if (dateInput) dateInput.value = '';
    // QuerySelectField's blank option is valued "__None" (its allow_blank
    // default), not "" — see forms/animals.py's termination_reason field.
    if (reasonSelect) reasonSelect.value = '__None';
}
document.addEventListener('change', clearTerminationFieldsOnUncheck);

// Navbar "jump to" search (base.html #globalSearchWrapper). The results
// list is real <a href> elements swapped in by htmx
// (partials/global_search_results.html) — this just adds keyboard
// navigation and the '/' shortcut on top of that.
(function () {
    const input = document.getElementById('globalSearchInput');
    const resultsBox = document.getElementById('globalSearchResults');
    if (!input || !resultsBox) return;

    function resultItems() {
        return Array.from(resultsBox.querySelectorAll('.global-search-result'));
    }

    function setActiveResult(el) {
        resultItems().forEach(i => i.classList.remove('active'));
        if (el) el.classList.add('active');
    }

    input.addEventListener('keydown', function (event) {
        const items = resultItems();
        if (event.key === 'Escape') {
            input.value = '';
            resultsBox.innerHTML = '';
            input.blur();
            return;
        }
        if (!items.length) return;
        const current = resultsBox.querySelector('.global-search-result.active');
        const idx = current ? items.indexOf(current) : -1;
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            setActiveResult(items[(idx + 1) % items.length]);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            setActiveResult(items[(idx - 1 + items.length) % items.length]);
        } else if (event.key === 'Enter') {
            event.preventDefault();
            const target = current || items[0];
            if (target) window.location.href = target.href;
        }
    });

    // Clicking a result navigates via its href; clicking anywhere else
    // closes the dropdown.
    document.addEventListener('click', function (event) {
        if (!event.target.closest('#globalSearchWrapper')) {
            resultsBox.innerHTML = '';
        }
    });

    // '/' jumps into the search box from anywhere, unless the user is
    // already typing in some other field.
    const navCollapse = document.getElementById('appNav');
    const navToggler = document.querySelector('.navbar-toggler');
    document.addEventListener('keydown', function (event) {
        if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return;
        const active = document.activeElement;
        const isTyping = active && (
            active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' ||
            active.tagName === 'SELECT' || active.isContentEditable
        );
        if (isTyping) return;
        event.preventDefault();

        // Below the navbar's collapse breakpoint the search box lives
        // inside #appNav, which is hidden until the hamburger toggler is
        // used — focus() on a hidden input is silently ignored, so open
        // it first. The toggler itself is only visible in that collapsed
        // mode (Bootstrap hides it via CSS at the expand breakpoint), so
        // its visibility is what tells us which mode we're in.
        const isCollapsedMode = navToggler && getComputedStyle(navToggler).display !== 'none';
        if (isCollapsedMode && navCollapse && !navCollapse.classList.contains('show')) {
            const collapseInstance = bootstrap.Collapse.getOrCreateInstance(navCollapse, { toggle: false });
            navCollapse.addEventListener('shown.bs.collapse', function focusOnce() {
                navCollapse.removeEventListener('shown.bs.collapse', focusOnce);
                input.focus();
                input.select();
            });
            collapseInstance.show();
        } else {
            input.focus();
            input.select();
        }
    });
})();

function addField(fieldsetName) {
    const container = document.getElementById(`${fieldsetName}-container`);
    const fieldsets = container.getElementsByClassName(`${fieldsetName}-group`);
    const newGroup = fieldsets[0].cloneNode(true);
    const itemCount = fieldsets.length;
    newGroup.id = `${fieldsetName}-{itemCount}`;
    container.appendChild(newGroup);
    reindexFields(fieldsetName);
};

function removeField(fieldsetName, button) {
    const fieldset = button.closest(`.${fieldsetName}-group`);
    const containers = document.getElementById(`${fieldsetName}-container`).getElementsByClassName(`${fieldsetName}-group`);
    if (containers.length > 1) {
        fieldset.remove();
        reindexFields(fieldsetName);
    };
};

function reindexFields(fieldsetName) {
    const containers = document.getElementById(fieldsetName + '-container').getElementsByClassName(`${fieldsetName}-group`);
    Array.from(containers).forEach((group, index) => {
        group.id = fieldsetName + `${index}`;
        const elements = group.querySelectorAll('input, select');
        elements.forEach(el => {
            const idRegex = new RegExp(`${fieldsetName}-\\d+-`);
            const replacement = `${fieldsetName}-${index}-`;
            if (el.id) el.id = el.id.replace(idRegex, replacement);
            if (el.name) el.name = el.name.replace(idRegex, replacement);
        });
    });
};

// For the weight/daily log
document.addEventListener('input', function(event) {
    if (event.target.classList.contains('feed-quantity')) {
        const weight = document.getElementById(event.target.id.replace('quantity', 'feed_weight'));
        const total = document.getElementById(event.target.id.replace('quantity', 'total'));
        total.textContent = (weight.value * event.target.value).toFixed(1) + 'g';

        let total_food = 0;
        const quantities = document.querySelectorAll('.feed-quantity');
        quantities.forEach(el => {
            const weight = document.getElementById(el.id.replace('quantity', 'feed_weight'));
            total_food += (el.value * weight.value);
        });
        document.getElementById('feedings-all-total').textContent = total_food.toFixed(1) + 'g';
    };
});

document.addEventListener('input', function(event) {
    if (event.target.classList.contains('current-weight')) {
        const current_weight = event.target.value;
        const current_baseline = document.getElementById('current_baseline').value;
        const current_baseline_pct = document.getElementById('current_baseline_pct');
        console.log(current_weight);
        console.log(current_baseline);
        console.log(current_baseline_pct);
        current_baseline_pct.value = Math.round(current_weight / current_baseline * 100);
    }
});

// Delegate click for dynamically rendered data-status-btn
document.addEventListener('click', async function(e) {
    const btn = e.target.closest('.data-status-btn');
    if (!btn) return;
    e.preventDefault();

    const url = btn.getAttribute('data-url');
    const setStatus = btn.getAttribute('data-set-status');
    const group = btn.closest('.data-status-group');

    try {
        // Post data
        const formData = new FormData();
        formData.append('status', setStatus);
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const headers = { 'X-Requested-With': 'XMLHttpRequest' };
        if (csrfMeta) headers['X-CSRFToken'] = csrfMeta.getAttribute('content');
        const res = await fetch(url, {
            method: 'POST',
            headers: headers,
            body: formData
        });

        if (res.ok) {
            const data = await res.json();

            if (data.status === 'success') {
                // Update status logic in DOM
                group.setAttribute('data-status', data.new_status);

                // Update every status indicator for this data file
                // (a file can appear multiple times on the page).
                const dataId = group.getAttribute('data-data-id');
                if (dataId) {
                    const statusClass = data.new_status === 'reviewed'
                        ? 'reviewed'
                        : data.new_status === 'exclude'
                            ? 'excluded'
                            : 'unreviewed';
                    const tooltipTitle = data.new_status === 'reviewed'
                        ? 'Reviewed'
                        : data.new_status === 'exclude'
                            ? 'Excluded'
                            : 'Unreviewed';
                    document.querySelectorAll(
                        '.df-status-icon[data-data-id="' + dataId + '"]'
                    ).forEach(function (icon) {
                        icon.classList.remove('reviewed', 'excluded', 'unreviewed');
                        icon.classList.add(statusClass);
                        icon.setAttribute('title', tooltipTitle);
                        icon.setAttribute('data-bs-original-title', tooltipTitle);
                    });
                }
            } else {
                console.error('Failed to update status', data);
            }
        }
    } catch (err) {
        console.error('AJAX error', err);
    }
});

function _loadBokehResources(jsUrls, cssUrls) {
    for (const url of (cssUrls || [])) {
        if (!document.querySelector(`link[href="${url}"]`)) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = url;
            document.head.appendChild(link);
        }
    }
    // Load JS files sequentially — bokeh-widgets depends on bokeh core.
    const pending = (jsUrls || []).filter(
        url => !document.querySelector(`script[src="${url}"]`)
    );
    return pending.reduce((chain, url) => chain.then(
        () => new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = url;
            s.onload = resolve;
            s.onerror = reject;
            document.head.appendChild(s);
        })
    ), Promise.resolve());
}

async function openPlotModal(url, title) {
    const plotModalElement = document.getElementById('plotModal');
    const plotModalTitle = document.getElementById('plotModalTitle');
    const plotModalBody = document.getElementById('plotModalBody');

    // Get or create modal instance
    let modalInstance = bootstrap.Modal.getInstance(plotModalElement);
    if (!modalInstance) {
        modalInstance = new bootstrap.Modal(plotModalElement);
    }

    plotModalTitle.textContent = title || 'Data Plot';
    plotModalBody.innerHTML = `
        <div class="d-flex justify-content-center p-5">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
        </div>`;
    modalInstance.show();

    try {
        const response = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const contentType = response.headers.get("content-type");
        if (!response.ok) {
            if (contentType && contentType.indexOf("application/json") !== -1) {
                const errData = await response.json();
                throw new Error(errData.error || 'Server returned an error');
            } else {
                throw new Error('Network response was not ok');
            }
        }
        const plotData = await response.json();

        if (plotData.type === 'bokeh') {
            await _loadBokehResources(plotData.js_urls, plotData.css_urls);

            if (plotData.figure_div) {
                // Image plot: figure wrapped in a CSS aspect-ratio container
                // so the browser maintains square pixels on every resize
                // without any JS resize handler.
                const ar = plotData.image_width / plotData.image_height;
                plotModalBody.innerHTML = '';

                const figWrapper = document.createElement('div');
                figWrapper.style.cssText = 'width:100%;aspect-ratio:' + ar + ';';
                figWrapper.innerHTML = plotData.figure_div;
                const bkRoot = figWrapper.querySelector('[data-root-id]');
                if (bkRoot) bkRoot.style.cssText = 'width:100%;height:100%;';
                plotModalBody.appendChild(figWrapper);

                const ctrlEl = document.createElement('div');
                ctrlEl.innerHTML = plotData.controls_div || '';
                plotModalBody.appendChild(ctrlEl);
            } else {
                plotModalBody.innerHTML = plotData.div;
            }

            const parser = new DOMParser();
            const scriptEl = parser.parseFromString(plotData.script, 'text/html').querySelector('script');
            if (scriptEl) {
                const s = document.createElement('script');
                s.textContent = scriptEl.textContent;
                document.body.appendChild(s);
            }
        } else {
            plotModalBody.innerHTML = '<div id="plotly-chart" style="width:100%; height: 600px;"></div>';
            Plotly.newPlot('plotly-chart', plotData.data || plotData, plotData.layout || {}, {responsive: true});
        }

    } catch (error) {
        plotModalBody.innerHTML = `
            <div class="alert alert-danger m-3">
                Error loading plot: ${error.message}
            </div>`;
    }
}

async function openDictModal(url, title) {
    const modalElement = document.getElementById('dictModal');
    const titleEl = document.getElementById('dictModalTitle');
    const bodyEl = document.getElementById('dictModalBody');
    titleEl.textContent = title || 'Settings';
    bodyEl.innerHTML = '<div class="d-flex justify-content-center p-5"><div class="spinner-border text-primary" role="status"></div></div>';
    const inst = bootstrap.Modal.getOrCreateInstance(modalElement);
    inst.show();
    try {
        const resp = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        if (!resp.ok) throw new Error(await resp.text() || 'Server returned an error');
        bodyEl.innerHTML = await resp.text();
    } catch (e) {
        bodyEl.innerHTML = '<div class="alert alert-danger m-3">' + e.message + '</div>';
    }
}

function openImageModal(url, title) {
    const modalElement = document.getElementById('imageModal');
    const titleEl = document.getElementById('imageModalTitle');
    const bodyEl = document.getElementById('imageModalBody');
    titleEl.textContent = title || 'Image';
    bodyEl.innerHTML = '<div class="d-flex justify-content-center p-5"><div class="spinner-border text-primary" role="status"></div></div>';
    const inst = bootstrap.Modal.getOrCreateInstance(modalElement);
    inst.show();
    const img = new Image();
    img.onload = function() {
        bodyEl.innerHTML = '';
        img.className = 'img-fluid';
        bodyEl.appendChild(img);
    };
    img.onerror = function() {
        bodyEl.innerHTML = '<div class="alert alert-danger m-3">Failed to load image.</div>';
    };
    img.src = url;
}

function openVideoModal(url, title) {
    const modalElement = document.getElementById('videoModal');
    const titleEl = document.getElementById('videoModalTitle');
    const bodyEl = document.getElementById('videoModalBody');
    titleEl.textContent = title || 'Video';
    bodyEl.innerHTML = '<video class="w-100" controls><source src="' + url + '"></video>';
    const inst = bootstrap.Modal.getOrCreateInstance(modalElement);
    inst.show();
    modalElement.addEventListener('hidden.bs.modal', function cleanup() {
        bodyEl.innerHTML = '';
        modalElement.removeEventListener('hidden.bs.modal', cleanup);
    });
}
