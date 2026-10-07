(function () {
    'use strict';

    /* ---------- Mobile navigation ---------- */
    var sidebar = document.getElementById('sidebar');
    var toggle = document.querySelector('[data-nav-toggle]');
    var scrim = document.querySelector('[data-nav-close]');

    function setNav(open) {
        if (!sidebar) return;
        sidebar.classList.toggle('is-open', open);
        if (toggle) toggle.setAttribute('aria-expanded', String(open));
        if (scrim) scrim.hidden = !open;
    }

    if (toggle) {
        toggle.addEventListener('click', function () {
            setNav(!sidebar.classList.contains('is-open'));
        });
    }

    if (scrim) {
        scrim.addEventListener('click', function () {
            setNav(false);
        });
    }

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') setNav(false);
    });

    /* ---------- Default date inputs to today ---------- */
    document.querySelectorAll('input[type="date"][data-today]').forEach(function (input) {
        if (!input.value) {
            var now = new Date();
            var month = String(now.getMonth() + 1).padStart(2, '0');
            var day = String(now.getDate()).padStart(2, '0');
            input.value = now.getFullYear() + '-' + month + '-' + day;
        }
    });

    /* ---------- Photo preview ---------- */
    var fileInput = document.querySelector('input[type="file"][data-preview]');
    var preview = document.querySelector('[data-preview-target]');

    if (fileInput && preview) {
        var maxPhotos = Number(fileInput.getAttribute('data-preview')) || 5;

        fileInput.addEventListener('change', function () {
            var files = Array.prototype.slice.call(fileInput.files || []);
            preview.innerHTML = '';
            preview.classList.remove('is-visible');

            files.slice(0, maxPhotos).forEach(function (file, index) {
                if (file.type.indexOf('image/') !== 0) return;

                var img = document.createElement('img');
                img.src = URL.createObjectURL(file);
                img.alt = 'Selected photo ' + (index + 1) + ' preview';
                img.addEventListener('load', function () {
                    URL.revokeObjectURL(img.src);
                });
                preview.appendChild(img);
            });

            if (files.length > maxPhotos) {
                var notice = document.createElement('p');
                notice.className = 'preview__notice';
                notice.textContent = 'Only the first ' + maxPhotos +
                    ' of ' + files.length + ' selected photos will be uploaded.';
                preview.appendChild(notice);
            }

            if (preview.childElementCount) {
                preview.classList.add('is-visible');
            }
        });
    }

    /* ---------- Textarea character counter ---------- */
    document.querySelectorAll('textarea[data-counter]').forEach(function (area) {
        var out = document.createElement('span');
        out.className = 'counter';
        var label = area.closest('.field').querySelector('label');
        if (label) label.appendChild(out);

        var max = Number(area.getAttribute('maxlength')) || 500;

        function update() {
            out.textContent = area.value.length + ' / ' + max;
        }

        area.setAttribute('maxlength', String(max));
        area.addEventListener('input', update);
        update();
    });

    /* ---------- Confirm destructive actions ---------- */
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
        form.addEventListener('submit', function (e) {
            if (!window.confirm(form.getAttribute('data-confirm'))) {
                e.preventDefault();
            }
        });
    });

    /* ---------- Request table filtering ---------- */
    var searchInput = document.querySelector('[data-table-filter]');
    var statusButtons = document.querySelectorAll('[data-status-filter]');
    /* Rows opt in by carrying data-search (and, where they can be filtered
       by state, data-status). The account list is search-only. */
    var rows = Array.prototype.slice.call(
        document.querySelectorAll('tbody tr[data-search], tbody tr[data-status]')
    );
    var noMatch = document.querySelector('[data-no-match]');

    if (rows.length && (searchInput || statusButtons.length)) {
        var activeStatus = 'all';

        function applyFilters() {
            var term = (searchInput ? searchInput.value : '').trim().toLowerCase();
            var visible = 0;

            rows.forEach(function (row) {
                var statusOk = activeStatus === 'all' || row.getAttribute('data-status') === activeStatus;
                var textOk = !term || (row.getAttribute('data-search') || '').toLowerCase().indexOf(term) !== -1;
                var show = statusOk && textOk;
                row.hidden = !show;
                if (show) visible++;
            });

            if (noMatch) noMatch.hidden = visible !== 0;
        }

        function selectStatus(value) {
            var match = null;

            statusButtons.forEach(function (btn) {
                if (btn.getAttribute('data-status-filter') === value) match = btn;
            });

            if (!match) return false;

            statusButtons.forEach(function (b) { b.classList.remove('is-active'); });
            match.classList.add('is-active');
            activeStatus = value;
            return true;
        }

        /* Dashboard stat cards link here with ?status=..., so the list should
           open on the matching filter instead of always landing on "All". */
        var requested = new URLSearchParams(window.location.search).get('status');
        if (requested) selectStatus(requested.replace(/\+/g, ' ').trim());

        if (searchInput) searchInput.addEventListener('input', applyFilters);

        statusButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                statusButtons.forEach(function (b) { b.classList.remove('is-active'); });
                btn.classList.add('is-active');
                activeStatus = btn.getAttribute('data-status-filter');
                applyFilters();
            });
        });

        applyFilters();
    }

    /* ---------- Highlight a deep-linked request row ---------- */
    if (window.location.hash) {
        var target = document.querySelector(window.location.hash);
        if (target && target.tagName === 'TR') {
            target.classList.add('is-highlight');
            target.scrollIntoView({ block: 'center' });
        }
    }

    /* ---------- Submitting state ---------- */
    document.querySelectorAll('form').forEach(function (form) {
        form.addEventListener('submit', function (e) {
            /* A cancelled data-confirm handler above already stopped this
               submit; marking it busy would leave the button stuck. */
            if (e.defaultPrevented) return;

            var button = form.querySelector('button[type="submit"]');
            if (!button || button.dataset.busyApplied === '1') return;

            var icon = button.querySelector('.icon');

            button.dataset.busyApplied = '1';
            button.dataset.idleHtml = button.innerHTML;
            button.classList.add('is-busy');
            button.setAttribute('aria-busy', 'true');

            /* Rebuild as icon + label so the wording can be swapped without
               depending on whether the text sat inside a <span>. */
            button.innerHTML = '';
            if (icon) button.appendChild(icon);

            var label = document.createElement('span');
            label.textContent = button.getAttribute('data-busy-label') || 'Working…';
            button.appendChild(label);
        });
    });

    /* ---------- Auto-dismiss flash messages ---------- */
    document.querySelectorAll('.alert').forEach(function (alert) {
        window.setTimeout(function () {
            alert.classList.add('is-leaving');
            window.setTimeout(function () {
                alert.remove();
            }, 400);
        }, 6000);
    });

    /* ---------- Enlarge request photos ---------- */
    document.querySelectorAll('.thumb').forEach(function (thumb) {
        thumb.addEventListener('click', function () {
            var box = document.createElement('div');
            box.style.cssText =
                'position:fixed;inset:0;z-index:99;display:grid;place-items:center;' +
                'padding:32px;background:rgba(10,18,15,.82);cursor:zoom-out';
            var img = document.createElement('img');
            img.src = thumb.src;
            img.alt = thumb.alt || 'Request photo';
            img.style.cssText =
                'max-width:min(900px,92vw);max-height:88vh;border-radius:14px;' +
                'box-shadow:0 30px 80px rgba(0,0,0,.6)';
            box.appendChild(img);
            box.addEventListener('click', function () {
                box.remove();
            });
            document.body.appendChild(box);
        });
    });
})();