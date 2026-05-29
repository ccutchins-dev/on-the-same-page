'use strict';

// ── State ──────────────────────────────────────────────────────────────────────
const state = {
    model:         null,   // loaded model_data.json
    bookList:      [],     // [{cid, title, author, n_voters}] — ordered
    results:       [],     // [{cid, score, baseCount}]
    matchedCounts: {},     // {cid: count} — for "on Y lists" display
};

const MAX_BOOKS = 15;

// ── DOM refs (set once in setupUI) ─────────────────────────────────────────────
let elMain, elLoading, elBookEntries, elSearchInput, elDropdown,
    elSearchContainer, elResultsPanel, elResultsHeader, elResultsList,
    elRarityDetails, elInputAlpha, elInputGamma;

// ── Algorithm ──────────────────────────────────────────────────────────────────

function rawIdf(nVoters, N) {
    // Matches Python _raw_idf: log((N+1)/(n+1)), decoupled from RARITY_ALPHA.
    // Used for scoring. Tiebreak uses model.idf (stored), which equals rawIdf
    // when RARITY_ALPHA=1.0 (current default). See DECISIONS.md for details.
    return Math.log((N + 1) / (nVoters + 1));
}

function coocScorer(model, inputCids, alpha, gamma) {
    // Matches Python _cooc_score exactly (parity gate: 9 cases × 15 books verified).
    // score(c) = (Σᵢ co(i,c) × rawIdf(nᵢ)^α) × rawIdf(nᶜ)^γ
    //
    // bookScores: weighted edge sum (one per voter × input_book × candidate edge).
    // bookCounts: DISTINCT voter count (one per voter per candidate, outside input
    //             loop) — this is the "co=" shown in the diagnostic display.
    const inputSet   = new Set(inputCids);
    const N          = model.n_voters;
    const books      = model.books;
    const bookScores = {};
    const bookCounts = {};

    for (const [, voterBooks] of Object.entries(model.voter_books)) {
        const voterInputs     = voterBooks.filter(([c]) => inputSet.has(c));
        if (voterInputs.length === 0) continue;
        const voterCandidates = voterBooks.filter(([c]) => !inputSet.has(c));

        // Distinct voter count: one per voter per candidate (outside input loop)
        for (const [cCid] of voterCandidates) {
            bookCounts[cCid] = (bookCounts[cCid] || 0) + 1;
        }

        // Weighted score: one contribution per (voter × input book × candidate)
        for (const [iCid] of voterInputs) {
            const nI = books[iCid] ? books[iCid].n_voters : 1;
            const wI = alpha !== 0 ? Math.pow(rawIdf(nI, N), alpha) : 1.0;
            for (const [cCid] of voterCandidates) {
                bookScores[cCid] = (bookScores[cCid] || 0) + wI;
            }
        }
    }

    if (gamma !== 0) {
        for (const cid of Object.keys(bookScores)) {
            const nC = books[cid] ? books[cid].n_voters : 1;
            bookScores[cid] *= Math.pow(rawIdf(nC, N), gamma);
        }
    }

    // Three-level sort: score desc, idf desc, cid asc (stable tiebreak for equal
    // scores — matches the Python sort key with cid as third term).
    const round6 = x => Math.round(x * 1e6) / 1e6;
    const ranked = Object.keys(bookScores).sort((a, b) => {
        const sa = round6(bookScores[a]);
        const sb = round6(bookScores[b]);
        if (sb !== sa) return sb - sa;
        const di = (model.idf[b] || 0) - (model.idf[a] || 0);
        if (di !== 0) return di;
        return a < b ? -1 : a > b ? 1 : 0;
    });

    return { ranked, bookScores, bookCounts };
}

function computeMatchedVoterCounts(model, inputCids, resultCids) {
    // Count distinct voters in the matched pool (any input overlap) who also have
    // each result book. Used for "on Y lists from voters who share your taste."
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
                e.preventDefault();
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
    setTimeout(() => {
        closeDropdown();
        elSearchInput.value = '';
    }, 150);
}

// ── Book selection / removal ───────────────────────────────────────────────────

function selectBook(cid, title, author, n_voters) {
    if (state.bookList.some(b => b.cid === cid)) return;
    if (state.bookList.length >= MAX_BOOKS) return;
    state.bookList.push({ cid, title, author, n_voters });
    closeDropdown();
    elSearchInput.value = '';
    renderEntries();
    liveRecompute();
    if (state.bookList.length < MAX_BOOKS) elSearchInput.focus();
}

function removeBook(cid) {
    state.bookList = state.bookList.filter(b => b.cid !== cid);
    renderEntries();
    liveRecompute();
    elSearchInput.focus();
}

// ── Live recompute ─────────────────────────────────────────────────────────────

function liveRecompute() {
    const inputCids = state.bookList.map(b => b.cid);

    if (inputCids.length === 0) {
        elMain.classList.remove('post-run');
        elMain.classList.add('pre-run');
        elResultsPanel.hidden = true;
        state.results       = [];
        state.matchedCounts = {};
        renderResults();
        return;
    }

    // Layout: shift to two-column the moment ≥1 book is selected
    elMain.classList.remove('pre-run');
    elMain.classList.add('post-run');
    elResultsPanel.hidden = false;

    const alpha = parseFloat(elInputAlpha.value);
    const gamma = parseFloat(elInputGamma.value);
    const { ranked, bookScores, bookCounts } = coocScorer(
        state.model, inputCids,
        isNaN(alpha) ? 1.0 : alpha,
        isNaN(gamma) ? 1.0 : gamma
    );

    const top50      = ranked.slice(0, 50);
    state.results    = top50.map(cid => ({
        cid,
        score:     bookScores[cid],
        baseCount: bookCounts[cid] || 0,
    }));
    state.matchedCounts = computeMatchedVoterCounts(state.model, inputCids, top50);
    renderResults();
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
    // Display-only — reads from state.results, never calls liveRecompute().
    // Also called by the rarity <details> toggle to show/hide diagnostic columns
    // without re-scoring (opening the panel is display-only, not a recompute).
    elResultsList.innerHTML = '';
    const showDiag = elRarityDetails.open;

    state.results.forEach(({ cid, score, baseCount }) => {
        const info  = state.model.books[cid] || {};
        const count = state.matchedCounts[cid] || 0;
        const li    = document.createElement('li');
        li.title    = `Score: ${score.toFixed(4)}`;
        li.innerHTML =
            `<span class="result-title">${esc(info.title || cid)}</span>`
          + `<span class="result-author">${esc(info.author || '')}</span>`
          + `<span class="result-count">on ${count} list${count === 1 ? '' : 's'} from voters who share your taste</span>`;
        if (showDiag) {
            li.innerHTML +=
                `<span class="result-diag">co=${baseCount} · n=${info.n_voters ?? '?'}</span>`;
        }
        elResultsList.appendChild(li);
    });

    elResultsHeader.textContent = state.results.length > 0
        ? `${state.results.length} recommendation${state.results.length === 1 ? '' : 's'}`
        : '';
}

// ── Init ───────────────────────────────────────────────────────────────────────

function setupUI() {
    elMain           = document.getElementById('main');
    elLoading        = document.getElementById('loading');
    elBookEntries    = document.getElementById('book-entries');
    elSearchInput    = document.getElementById('search-input');
    elDropdown       = document.getElementById('dropdown');
    elSearchContainer = document.getElementById('search-container');
    elResultsPanel   = document.getElementById('results-panel');
    elResultsHeader  = document.getElementById('results-header');
    elResultsList    = document.getElementById('results-list');
    elRarityDetails  = document.getElementById('rarity-details');
    elInputAlpha     = document.getElementById('input-alpha');
    elInputGamma     = document.getElementById('input-gamma');

    // Seed α/γ from JSON (single source of truth)
    elInputAlpha.value = state.model.cooc_input_exp  ?? 1.0;
    elInputGamma.value = state.model.cooc_output_exp ?? 1.0;

    elSearchInput.addEventListener('input',   onSearchInput);
    elSearchInput.addEventListener('keydown', onSearchKeydown);
    elSearchInput.addEventListener('blur',    onSearchBlur);
    elInputAlpha.addEventListener('input',    liveRecompute);
    elInputGamma.addEventListener('input',    liveRecompute);
    // Toggle re-renders display only (no recompute — panel open/close ≠ scoring change)
    elRarityDetails.addEventListener('toggle', renderResults);

    renderEntries();

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
