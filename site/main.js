'use strict';

// ── State ──────────────────────────────────────────────────────────────────────
const state = {
    model:         null,   // loaded model_data.json
    bookList:      [],     // [{cid, title, author, n_voters}] — ordered
    results:       [],     // [[cid, affinity], ...] — from recommend()
    matchedCounts: {},     // {cid: count}
    hasRun:        false,
    isDirty:       false,
};

const MAX_BOOKS = 15;

// ── DOM refs (set once in setupUI) ─────────────────────────────────────────────
let elMain, elLoading, elInputPanel, elBookEntries, elSearchInput, elDropdown,
    elSearchContainer, elRunBtn, elStaleNotice, elResultsPanel, elResultsHeader,
    elResultsList;

// ── Algorithm ──────────────────────────────────────────────────────────────────

function positionFactor(pos, pw) {
    return 1.0 - pw * (pos - 1) / 9;
}

function recommend(model, inputCids) {
    const inputSet = new Set(inputCids);
    const { idf, voter_books, position_weight: pw } = model;

    // Step 1 — voter similarity: IDF weight × position factor, summed over shared books
    const voterSim = {};
    for (const [voter, books] of Object.entries(voter_books)) {
        let sim = 0;
        for (const [cid, pos] of books) {
            if (inputSet.has(cid)) sim += (idf[cid] || 0) * positionFactor(pos, pw);
        }
        if (sim > 0) voterSim[voter] = sim;
    }

    // Step 2 — book affinity: sum voter sims for each non-input book
    const bookAff = {};
    for (const [voter, sim] of Object.entries(voterSim)) {
        for (const [cid] of voter_books[voter]) {
            if (!inputSet.has(cid)) bookAff[cid] = (bookAff[cid] || 0) + sim;
        }
    }

    // Sort: affinity descending (rounded to 6 dp to match phase2_model.py),
    // tiebreak by IDF weight descending
    const round6 = x => Math.round(x * 1e6) / 1e6;
    return Object.entries(bookAff).sort(([cA, aA], [cB, aB]) => {
        const a = round6(aA), b = round6(aB);
        if (b !== a) return b - a;
        return (idf[cB] || 0) - (idf[cA] || 0);
    });
}

function computeMatchedVoterCounts(model, inputCids, resultCids) {
    // For each recommended book: count voters in the matched pool
    // (any overlap with input books) who also have that book.
    const inputSet  = new Set(inputCids);
    const resultSet = new Set(resultCids);
    const counts    = Object.fromEntries(resultCids.map(c => [c, 0]));
    for (const [, books] of Object.entries(model.voter_books)) {
        const hasInput = books.some(([c]) => inputSet.has(c));
        if (!hasInput) continue;
        for (const [cid] of books) {
            if (resultSet.has(cid)) counts[cid]++;
        }
    }
    return counts;
}

// ── Utilities ──────────────────────────────────────────────────────────────────

function esc(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ── Autocomplete ───────────────────────────────────────────────────────────────

function getMatches(query) {
    if (!query) return [];
    const q = query.toLowerCase();
    const selected = new Set(state.bookList.map(b => b.cid));
    const starts = [], contains = [];
    for (const [cid, info] of Object.entries(state.model.books)) {
        const tl = info.title.toLowerCase();
        const al = info.author.toLowerCase();
        const match = { cid, title: info.title, author: info.author,
                        n_voters: info.n_voters, isSelected: selected.has(cid) };
        if (tl.startsWith(q) || al.startsWith(q)) {
            starts.push(match);
        } else if (tl.includes(q) || al.includes(q)) {
            contains.push(match);
        }
        if (starts.length + contains.length >= 60) break;
    }
    return [...starts, ...contains].slice(0, 20);
}

function renderDropdown(matches) {
    elDropdown.innerHTML = '';
    if (matches.length === 0) {
        const li = document.createElement('li');
        li.className = 'dropdown-no-matches';
        li.textContent = 'No matches';
        elDropdown.appendChild(li);
        elDropdown.hidden = false;
        return;
    }
    matches.forEach(({ cid, title, author, n_voters, isSelected }) => {
        const li = document.createElement('li');
        li.className = 'dropdown-item' + (isSelected ? ' disabled' : '');
        li.setAttribute('role', 'option');
        li.dataset.cid = cid;
        li.innerHTML = `<span class="item-title">${esc(title)}</span>`
                     + `<span class="item-author">${esc(author)}</span>`;
        if (!isSelected) {
            li.addEventListener('mousedown', e => {
                e.preventDefault(); // prevent blur firing before click
                selectBook(cid, title, author, n_voters);
            });
        }
        elDropdown.appendChild(li);
    });
    elDropdown.hidden = false;
}

function closeDropdown() {
    elDropdown.hidden = true;
    elDropdown.innerHTML = '';
}

function activateItem(delta) {
    const items = [...elDropdown.querySelectorAll('.dropdown-item:not(.disabled)')];
    if (!items.length) return;
    const cur  = elDropdown.querySelector('.dropdown-item.active');
    const idx  = cur ? items.indexOf(cur) : -1;
    const next = items[Math.max(0, Math.min(idx + delta, items.length - 1))];
    if (cur) cur.classList.remove('active');
    next.classList.add('active');
    next.scrollIntoView({ block: 'nearest' });
}

function onSearchInput() {
    const q = elSearchInput.value.trim();
    if (!q) { closeDropdown(); return; }
    renderDropdown(getMatches(q));
}

function onSearchKeydown(e) {
    if (elDropdown.hidden) return;
    if (e.key === 'ArrowDown')  { e.preventDefault(); activateItem(+1); return; }
    if (e.key === 'ArrowUp')    { e.preventDefault(); activateItem(-1); return; }
    if (e.key === 'Escape')     { closeDropdown(); elSearchInput.value = ''; return; }
    if (e.key === 'Enter') {
        e.preventDefault();
        const active = elDropdown.querySelector('.dropdown-item.active');
        const target = active || elDropdown.querySelector('.dropdown-item:not(.disabled)');
        if (target) {
            const cid  = target.dataset.cid;
            const info = state.model.books[cid];
            selectBook(cid, info.title, info.author, info.n_voters);
        }
    }
}

function onSearchBlur() {
    // Delay so mousedown on a dropdown item fires first
    setTimeout(() => {
        closeDropdown();
        elSearchInput.value = '';
    }, 150);
}

// ── Book selection / removal ───────────────────────────────────────────────────

function selectBook(cid, title, author, n_voters) {
    if (state.bookList.some(b => b.cid === cid)) return; // duplicate
    if (state.bookList.length >= MAX_BOOKS) return;
    state.bookList.push({ cid, title, author, n_voters });
    closeDropdown();
    elSearchInput.value = '';
    if (state.hasRun) { state.isDirty = true; markStale(); }
    renderEntries();
    updateRunButton();
    if (state.bookList.length < MAX_BOOKS) elSearchInput.focus();
}

function removeBook(cid) {
    state.bookList = state.bookList.filter(b => b.cid !== cid);
    if (state.hasRun) { state.isDirty = true; markStale(); }
    renderEntries();
    updateRunButton();
    elSearchInput.focus();
}

// ── Rendering ──────────────────────────────────────────────────────────────────

function renderEntries() {
    elBookEntries.innerHTML = '';
    state.bookList.forEach(({ cid, title, author, n_voters }) => {
        const div = document.createElement('div');
        div.className = 'book-entry';
        div.innerHTML =
            `<div class="book-main">`
          +   `<span class="book-title">${esc(title)}</span>`
          +   `<span class="book-sep"> · </span>`
          +   `<span class="book-author">${esc(author)}</span>`
          + `</div>`
          + `<div class="book-meta">`
          +   `<span class="voter-count">on ${n_voters} voter list${n_voters === 1 ? '' : 's'}</span>`
          +   `<button class="remove-btn" title="Remove">×</button>`
          + `</div>`;
        div.querySelector('.remove-btn').addEventListener('click', () => removeBook(cid));
        elBookEntries.appendChild(div);
    });

    elSearchInput.placeholder = state.bookList.length === 0
        ? 'Search for a book…'
        : 'Search for another book…';
    elSearchContainer.hidden = state.bookList.length >= MAX_BOOKS;
}

function renderResults() {
    elResultsList.innerHTML = '';
    state.results.forEach(([cid, aff]) => {
        const info  = state.model.books[cid] || {};
        const count = state.matchedCounts[cid] || 0;
        const li    = document.createElement('li');
        li.title    = `Affinity: ${aff.toFixed(4)}`;
        li.innerHTML =
            `<span class="result-title">${esc(info.title || cid)}</span>`
          + `<span class="result-author">${esc(info.author || '')}</span>`
          + `<span class="result-count">on ${count} list${count === 1 ? '' : 's'} from voters who share your taste</span>`;
        elResultsList.appendChild(li);
    });
    elResultsHeader.textContent =
        `${state.results.length} recommendation${state.results.length === 1 ? '' : 's'}`;
}

function updateRunButton() {
    elRunBtn.disabled = state.bookList.length === 0;
}

function markStale() {
    elResultsPanel.classList.add('stale');
    elStaleNotice.hidden = false;
}

function clearStale() {
    elResultsPanel.classList.remove('stale');
    elStaleNotice.hidden = true;
}

// ── Run model ──────────────────────────────────────────────────────────────────

function runModel() {
    const inputCids = state.bookList.map(b => b.cid);
    const ranked    = recommend(state.model, inputCids);
    const top50     = ranked.slice(0, 50);
    const resultCids = top50.map(([c]) => c);
    const counts    = computeMatchedVoterCounts(state.model, inputCids, resultCids);

    state.results       = top50;
    state.matchedCounts = counts;
    state.hasRun        = true;
    state.isDirty       = false;

    // Switch to two-column layout
    elMain.classList.replace('pre-run', 'post-run');
    elResultsPanel.hidden = false;

    renderResults();
    clearStale();
}

// ── Init ───────────────────────────────────────────────────────────────────────

function setupUI() {
    elMain           = document.getElementById('main');
    elLoading        = document.getElementById('loading');
    elInputPanel     = document.getElementById('input-panel');
    elBookEntries    = document.getElementById('book-entries');
    elSearchInput    = document.getElementById('search-input');
    elDropdown       = document.getElementById('dropdown');
    elSearchContainer = document.getElementById('search-container');
    elRunBtn         = document.getElementById('run-btn');
    elStaleNotice    = document.getElementById('stale-notice');
    elResultsPanel   = document.getElementById('results-panel');
    elResultsHeader  = document.getElementById('results-header');
    elResultsList    = document.getElementById('results-list');

    elSearchInput.addEventListener('input',   onSearchInput);
    elSearchInput.addEventListener('keydown', onSearchKeydown);
    elSearchInput.addEventListener('blur',    onSearchBlur);
    elRunBtn.addEventListener('click', runModel);

    renderEntries();
    updateRunButton();

    elLoading.hidden = true;
    elMain.hidden    = false;
    elSearchInput.focus();
}

async function init() {
    try {
        const res = await fetch('../data/model_data.json');
        if (!res.ok) throw new Error(res.status);
        state.model = await res.json();
        setupUI();
    } catch (e) {
        elLoading.textContent =
            'Could not load data. Start the server from the repo root: python3 -m http.server 8000';
    }
}

init();
