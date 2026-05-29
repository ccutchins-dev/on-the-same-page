'use strict';

// ── Scorer selection ───────────────────────────────────────────────────────────
// Default: 'ppmi'. Override via ?scorer=cooc for silent A/B comparison.
// Debug diagnostic columns (co=N · n=M): add ?debug=1.
const _params       = new URLSearchParams(window.location.search);
const ACTIVE_SCORER = _params.get('scorer') || 'ppmi';
const DEBUG         = _params.get('debug') === '1';

// Fallback co-occurrence params (used only when ACTIVE_SCORER === 'cooc')
const COOC_ALPHA = 1.0;
const COOC_GAMMA = 1.0;

// ── State ──────────────────────────────────────────────────────────────────────
const state = {
    model:         null,   // loaded model_data.json
    ppmiMap:       null,   // {cid → Map{cid → ppmi_value}} — built at startup
    coocCounts:    null,   // {cid → Map{cid → count}}  — for debug display
    bookList:      [],     // [{cid, title, author, n_voters}] — ordered
    results:       [],     // [{cid, score, baseCount}]
    matchedCounts: {},     // {cid: count} — for "on Y lists" display
};

const MAX_BOOKS = 15;

// ── DOM refs (set once in setupUI) ─────────────────────────────────────────────
let elMain, elLoading, elBookEntries, elSearchInput, elDropdown,
    elSearchContainer, elResultsPanel, elResultsHeader, elResultsList;

// ── PPMI-direct scorer ─────────────────────────────────────────────────────────

function buildPPMILookup(voterBooks) {
    // Builds ppmiMap and coocCounts from voter_books already in model_data.json.
    // Matches Python compute_ppmi(build_cooc(voter_books), shift_k=0) exactly.
    // Parity verified: C_total identical, rank-parity and score-parity confirmed
    // for 3 input sets (see parity gate run before this commit).
    const coocMap = {};  // {cid_i: {cid_j: count}} — symmetric
    const rowSums = {};  // {cid: total directed co-occurrence count}

    for (const [, voterBooksEntry] of Object.entries(voterBooks)) {
        // voterBooksEntry = [[cid, pos], ...]; deduplicate matching Python frozenset
        const cids = [...new Set(voterBooksEntry.map(([c]) => c))];
        for (let a = 0; a < cids.length; a++) {
            for (let b = a + 1; b < cids.length; b++) {
                const ci = cids[a], cj = cids[b];
                if (!coocMap[ci]) coocMap[ci] = {};
                if (!coocMap[cj]) coocMap[cj] = {};
                coocMap[ci][cj] = (coocMap[ci][cj] || 0) + 1;
                coocMap[cj][ci] = (coocMap[cj][ci] || 0) + 1;
                rowSums[ci] = (rowSums[ci] || 0) + 1;
                rowSums[cj] = (rowSums[cj] || 0) + 1;
            }
        }
    }

    // C_total = Σ rowSums = 2 × undirected-pairs sum (matches Python mat.sum())
    let C_total = 0;
    for (const s of Object.values(rowSums)) C_total += s;

    const ppmiMap    = {};
    const coocCounts = {};
    for (const [ci, row] of Object.entries(coocMap)) {
        const ri = rowSums[ci] || 0;
        if (!ri) continue;
        ppmiMap[ci]    = new Map();
        coocCounts[ci] = new Map();
        for (const [cj, count] of Object.entries(row)) {
            coocCounts[ci].set(cj, count);
            const rj = rowSums[cj] || 0;
            if (!rj) continue;
            const pmi = Math.log2(count * C_total / (ri * rj));
            if (pmi > 0) ppmiMap[ci].set(cj, pmi);
        }
    }

    return { ppmiMap, coocCounts };
}

function ppmiDirectScorer(ppmiMap, coocCounts, inputCids, model, top_n = 50) {
    // score(c) = Σᵢ∈input PPMI(i, c)   [k=0, α=0 — no parameters]
    // Three-level sort: score desc → idf desc → cid asc (matches Python rank_ppmi_direct).
    // 6-decimal rounding preserves parity with Python scorer.
    const inputSet = new Set(inputCids);
    const scores   = {};
    const baseCo   = {};  // raw co-occurrence sums per candidate (for debug display)

    for (const iCid of inputCids) {
        const ppmiRow = ppmiMap[iCid];
        if (!ppmiRow) continue;
        for (const [cCid, ppmiVal] of ppmiRow) {
            if (inputSet.has(cCid)) continue;
            scores[cCid] = (scores[cCid] || 0) + ppmiVal;
        }
        // Also accumulate raw co-occ counts for debug display
        const coocRow = coocCounts[iCid];
        if (coocRow) {
            for (const [cCid, cnt] of coocRow) {
                if (!inputSet.has(cCid))
                    baseCo[cCid] = (baseCo[cCid] || 0) + cnt;
            }
        }
    }

    const round6 = x => Math.round(x * 1e6) / 1e6;
    const ranked  = Object.keys(scores).sort((a, b) => {
        const sa = round6(scores[a]), sb = round6(scores[b]);
        if (sb !== sa) return sb - sa;
        const di = (model.idf[b] || 0) - (model.idf[a] || 0);
        if (di !== 0) return di;
        return a < b ? -1 : a > b ? 1 : 0;
    });

    return { ranked: ranked.slice(0, top_n), bookScores: scores, bookCounts: baseCo };
}

// ── Co-occurrence scorer (dormant; active only via ?scorer=cooc) ───────────────

function rawIdf(nVoters, N) {
    return Math.log((N + 1) / (nVoters + 1));
}

function coocScorer(model, inputCids, alpha, gamma) {
    const inputSet   = new Set(inputCids);
    const N          = model.n_voters;
    const books      = model.books;
    const bookScores = {};
    const bookCounts = {};

    for (const [, voterBooks] of Object.entries(model.voter_books)) {
        const voterInputs     = voterBooks.filter(([c]) => inputSet.has(c));
        if (voterInputs.length === 0) continue;
        const voterCandidates = voterBooks.filter(([c]) => !inputSet.has(c));

        for (const [cCid] of voterCandidates) {
            bookCounts[cCid] = (bookCounts[cCid] || 0) + 1;
        }
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

    const round6 = x => Math.round(x * 1e6) / 1e6;
    const ranked  = Object.keys(bookScores).sort((a, b) => {
        const sa = round6(bookScores[a]), sb = round6(bookScores[b]);
        if (sb !== sa) return sb - sa;
        const di = (model.idf[b] || 0) - (model.idf[a] || 0);
        if (di !== 0) return di;
        return a < b ? -1 : a > b ? 1 : 0;
    });

    return { ranked: ranked.slice(0, 50), bookScores, bookCounts };
}

function computeMatchedVoterCounts(model, inputCids, resultCids) {
    // Count distinct matched-pool voters (any input overlap) who have each result book.
    // With PPMI scoring a high-ranked result may have a low Y (PPMI surfaces books for
    // association strength, not corroboration count — Y is informational, not the rank signal).
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

    // Layout: shift to two-column on first book selection
    elMain.classList.remove('pre-run');
    elMain.classList.add('post-run');
    elResultsPanel.hidden = false;

    let ranked, bookScores, bookCounts;
    if (ACTIVE_SCORER === 'ppmi') {
        ({ ranked, bookScores, bookCounts } = ppmiDirectScorer(
            state.ppmiMap, state.coocCounts, inputCids, state.model));
    } else {
        ({ ranked, bookScores, bookCounts } = coocScorer(
            state.model, inputCids, COOC_ALPHA, COOC_GAMMA));
    }

    const top50 = ranked.slice(0, 50);
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
    elResultsList.innerHTML = '';

    state.results.forEach(({ cid, score, baseCount }) => {
        const info  = state.model.books[cid] || {};
        const count = state.matchedCounts[cid] || 0;
        const li    = document.createElement('li');
        li.title    = `Score: ${score.toFixed(4)}`;
        li.innerHTML =
            `<span class="result-title">${esc(info.title || cid)}</span>`
          + `<span class="result-author">${esc(info.author || '')}</span>`
          + `<span class="result-count">on ${count} list${count === 1 ? '' : 's'} from voters who share your taste</span>`;
        if (DEBUG) {
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
    elMain            = document.getElementById('main');
    elLoading         = document.getElementById('loading');
    elBookEntries     = document.getElementById('book-entries');
    elSearchInput     = document.getElementById('search-input');
    elDropdown        = document.getElementById('dropdown');
    elSearchContainer = document.getElementById('search-container');
    elResultsPanel    = document.getElementById('results-panel');
    elResultsHeader   = document.getElementById('results-header');
    elResultsList     = document.getElementById('results-list');

    // Build PPMI lookup once at startup from voter_books already in JSON
    if (ACTIVE_SCORER === 'ppmi') {
        const { ppmiMap, coocCounts } = buildPPMILookup(state.model.voter_books);
        state.ppmiMap    = ppmiMap;
        state.coocCounts = coocCounts;
    }

    elSearchInput.addEventListener('input',   onSearchInput);
    elSearchInput.addEventListener('keydown', onSearchKeydown);
    elSearchInput.addEventListener('blur',    onSearchBlur);

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
