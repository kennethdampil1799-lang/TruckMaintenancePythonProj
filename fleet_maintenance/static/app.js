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
        fileInput.addEventListener('change', function () {
            var file = fileInput.files && fileInput.files[0];
            preview.innerHTML = '';
            preview.classList.remove('is-visible');

            if (!file || file.type.indexOf('image/') !== 0) return;

            var img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            img.alt = 'Selected photo preview';
            img.addEventListener('load', function () {
                URL.revokeObjectURL(img.src);
            });
            preview.appendChild(img);
            preview.classList.add('is-visible');
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
    var rows = Array.prototype.slice.call(document.querySelectorAll('tbody tr[data-status]'));
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

        if (searchInput) searchInput.addEventListener('input', applyFilters);

        statusButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                statusButtons.forEach(function (b) { b.classList.remove('is-active'); });
                btn.classList.add('is-active');
                activeStatus = btn.getAttribute('data-status-filter');
                applyFilters();
            });
        });
    }

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