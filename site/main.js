'use strict';

// Debug diagnostic columns (co=N · n=M): add ?debug=1 to URL.
// ?scorer= URL param retired — use the blend slider instead.
const DEBUG = new URLSearchParams(window.location.search).get('debug') === '1';

// Co-occurrence fallback params (always used for fusion)
const COOC_ALPHA = 1.0;
const COOC_GAMMA = 1.0;

// /10 score display denominators (display-only — never feed into ranking)
// Empirically calibrated from 300 stratified input pairs (100 popular, 100 mixed, 100 rare).
// Co-occ: sqrt-compressed, not n-scaled. D=5.5 → Middlemarch+JE best book (raw=27) ≈ 9.4/10.
// PPMI: linear, per-input (×n). D=3.8 ≈ p99 of per-input PPMI distribution.
const SCORE_DENOM_COOC_SQRT = 5.5;
const SCORE_DENOM_PPMI      = 3.8;

// ── State ──────────────────────────────────────────────────────────────────────
const state = {
    model:         null,   // loaded model_data.json
    ppmiMap:       null,   // {cid → Map{cid → ppmi_value}} — built at startup
    coocCounts:    null,   // {cid → Map{cid → raw count}} — for debug display
    bookList:      [],     // [{cid, title, author, n_voters}] — ordered
    ppmiRanked:    [],     // all PPMI-reachable candidates, full pool, ordered by PPMI rank
    coocRanked:    [],     // all co-occ-reachable candidates, full pool, ordered by co-occ rank
    baseCounts:    {},     // {cid: co-occ count sum} — raw co-occ Σᵢ count(voters with input_i and rec)
    ppmiScores:    {},     // {cid: ppmi score sum} — Σᵢ PPMI(input_i, rec), for evidence display
    results:         [],   // [{cid, score, baseCount}] — fused top-50
    matchedCounts:   {},   // {cid: count} — voters with ≥1 input and rec book
    multiMatchCounts:{},   // {cid: count} — subset of matchedCounts with ≥2 inputs
    blendT:          0.25, // current slider value
    expandedCid:   null,   // currently expanded result cid (accordion: one open at a time)
};

const MAX_BOOKS     = 15;

// ── Browsable autocomplete state ───────────────────────────────────────────────
let sortedBooks          = [];   // all books sorted n_voters desc, cid asc tiebreak
let currentDropdownItems = [];   // current filtered list (all 1209 items or filtered subset)
let dropdownWindow       = 0;    // items currently mounted in DOM
const WINDOW_INITIAL     = 100;  // mount this many on first open
const WINDOW_PAGE        = 50;   // append this many on scroll

// ── DOM refs (set once in setupUI) ─────────────────────────────────────────────
let elMain, elLoading, elBookEntries, elSearchInput, elDropdown,
    elSearchContainer, elResultsPanel, elResultsHeader, elResultsList,
    elBlendSlider, elBlendValue;

// ── PPMI-direct scorer ─────────────────────────────────────────────────────────

function buildPPMILookup(voterBooks) {
    // Builds ppmiMap and coocCounts from voter_books already in model_data.json.
    // Parity verified vs Python compute_ppmi(build_cooc(), shift_k=0):
    // C_total exact match (33294), rank-parity and score-parity confirmed for 3 input sets.
    const coocMap = {};  // {cid_i: {cid_j: count}} — symmetric
    const rowSums = {};  // {cid: total directed co-occurrence count}

    for (const [, voterBooksEntry] of Object.entries(voterBooks)) {
        const cids = [...new Set(voterBooksEntry.map(([c]) => c))];  // dedup (frozenset parity)
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
    // score(c) = Σᵢ∈input PPMI(i, c)   [k=0, α=0]
    // Pass top_n=Infinity for fusion (full reachable pool, no cap).
    // Three-level sort: score desc → idf desc → cid asc.
    const inputSet = new Set(inputCids);
    const scores   = {};
    const baseCo   = {};

    for (const iCid of inputCids) {
        const ppmiRow = ppmiMap[iCid];
        if (!ppmiRow) continue;
        for (const [cCid, ppmiVal] of ppmiRow) {
            if (inputSet.has(cCid)) continue;
            scores[cCid] = (scores[cCid] || 0) + ppmiVal;
        }
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

    const out = top_n === Infinity ? ranked : ranked.slice(0, top_n);
    return { ranked: out, bookScores: scores, bookCounts: baseCo };
}

// ── Co-occurrence scorer ───────────────────────────────────────────────────────

function rawIdf(nVoters, N) {
    return Math.log((N + 1) / (nVoters + 1));
}

function coocScorer(model, inputCids, alpha, gamma, top_n = 50) {
    // Pass top_n=Infinity for fusion (full reachable pool, no cap).
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

    const out = top_n === Infinity ? ranked : ranked.slice(0, top_n);
    return { ranked: out, bookScores, bookCounts };
}

function computeMatchedVoterCounts(model, inputCids, resultCids) {
    const inputSet    = new Set(inputCids);
    const resultSet   = new Set(resultCids);
    const counts      = Object.fromEntries(resultCids.map(c => [c, 0]));
    const multiCounts = Object.fromEntries(resultCids.map(c => [c, 0]));
    for (const [, books] of Object.entries(model.voter_books)) {
        const sharedCount = books.filter(([c]) => inputSet.has(c)).length;
        if (sharedCount === 0) continue;
        for (const [cid] of books) {
            if (resultSet.has(cid)) {
                counts[cid]++;
                if (sharedCount >= 2) multiCounts[cid]++;
            }
        }
    }
    return { matchedCounts: counts, multiMatchCounts: multiCounts };
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function buildVoterCards(cid, inputCids, model) {
    // Returns voter cards sorted by influence: shared-input-count desc → idfSum desc.
    // pos values are already integers in model_data.json (_parse_position applied
    // during Python export). Tied integers occur for cross-source voters (e.g. "1;5"
    // and "1;6" both → 1); the n_voters-then-title tie-break handles these.
    const N   = model.n_voters;
    const cards = [];

    for (const [voter, books] of Object.entries(model.voter_books)) {
        const bookSet = new Set(books.map(([c]) => c));
        if (!bookSet.has(cid)) continue;
        const shared = inputCids.filter(i => bookSet.has(i));
        if (!shared.length) continue;

        const idfSum = shared.reduce((s, i) => {
            const nv = (model.books[i] || {}).n_voters || 1;
            return s + Math.log((N + 1) / (nv + 1));
        }, 0);

        // Within-card order: position asc → n_voters asc (rarer first) → title alpha
        const bookList = books.map(([c, pos]) => ({
            cid: c, pos,
            nv:    (model.books[c] || {}).n_voters || 999,
            title: (model.books[c] || {}).title    || c,
        })).sort((a, b) =>
            a.pos   !== b.pos   ? a.pos   - b.pos   :
            a.nv    !== b.nv    ? a.nv    - b.nv    :
            a.title < b.title   ? -1 : 1
        );

        cards.push({ voter, sharedCount: shared.length, idfSum, bookList });
    }

    // Card order: shared-count desc → idf-sum desc (slider-independent)
    cards.sort((a, b) =>
        b.sharedCount !== a.sharedCount ? b.sharedCount - a.sharedCount
                                        : b.idfSum      - a.idfSum
    );
    return cards;
}

function renderDetailPanel(cid, inputCids, model) {
    const coocScore = state.baseCounts[cid]  || 0;
    const ppmiScore = state.ppmiScores[cid]  || 0;
    const cards     = buildVoterCards(cid, inputCids, model);
    const inputSet  = new Set(inputCids);

    const n        = inputCids.length;
    const coocNorm = Math.min(10, Math.sqrt(coocScore) / SCORE_DENOM_COOC_SQRT * 10).toFixed(1);
    const ppmiNorm = Math.min(10, ppmiScore / (SCORE_DENOM_PPMI * n) * 10).toFixed(1);

    // ── Scores ────────────────────────────────────────────────────────────────
    const scoresEl = document.createElement('div');
    scoresEl.className = 'detail-scores';
    scoresEl.innerHTML =
        `<div class="detail-score">`
      +   `<span class="detail-score-label">Co-occurrence</span>`
      +   `<span class="detail-score-value">${coocNorm} / 10</span>`
      + `</div>`
      + `<div class="detail-score">`
      +   `<span class="detail-score-label">Distinctiveness (PPMI)</span>`
      +   `<span class="detail-score-value">${ppmiNorm} / 10</span>`
      + `</div>`;

    // ── Voter strip ────────────────────────────────────────────────────────────
    const wrapper = document.createElement('div');
    wrapper.className = 'detail-strip-wrapper';

    if (cards.length === 0) {
        wrapper.innerHTML = `<div class="detail-empty">No voters matching your inputs have this book — surfaced by PPMI association.</div>`;
    } else {
        const strip = document.createElement('div');
        strip.className = 'detail-strip';

        for (const { voter, bookList } of cards) {
            const card = document.createElement('div');
            card.className = 'voter-card';

            const header = document.createElement('div');
            header.className = 'voter-card-header';
            header.title = voter;
            header.textContent = voter;
            card.appendChild(header);

            const booksEl = document.createElement('div');
            booksEl.className = 'voter-card-books';
            for (const { cid: bCid, title } of bookList) {
                const row = document.createElement('div');
                row.className = 'voter-book'
                    + (bCid === cid        ? ' is-rec'   : '')
                    + (inputSet.has(bCid)  ? ' is-input' : '');
                row.title     = title;
                row.textContent = title;
                booksEl.appendChild(row);
            }
            card.appendChild(booksEl);
            strip.appendChild(card);
        }
        wrapper.appendChild(strip);
    }

    const el = document.createElement('div');
    el.className = 'result-detail';
    el.appendChild(scoresEl);
    el.appendChild(wrapper);
    return el;
}

function collapseAll() {
    if (!state.expandedCid) return;
    const open = elResultsList.querySelector('.result-detail');
    if (open) open.remove();
    const openLi = elResultsList.querySelector('.result-expanded');
    if (openLi) openLi.classList.remove('result-expanded');
    state.expandedCid = null;
}

function toggleExpansion(cid, li) {
    const inputCids = state.bookList.map(b => b.cid);
    if (state.expandedCid === cid) {
        collapseAll();
        return;
    }
    collapseAll();   // close any previously open
    state.expandedCid = cid;
    li.classList.add('result-expanded');
    const panel = renderDetailPanel(cid, inputCids, state.model);
    li.appendChild(panel);
}

// ── Rank fusion ────────────────────────────────────────────────────────────────

function fuseAndRender() {
    collapseAll();   // collapse open expansion — re-ranking changes evidence
    const inputCids = state.bookList.map(b => b.cid);
    const t = parseFloat(elBlendSlider.value);
    state.blendT = t;
    elBlendValue.textContent = t.toFixed(2);

    if (inputCids.length === 0) {
        renderResults();
        return;
    }

    const ppmiRankMap = new Map(state.ppmiRanked.map((cid, i) => [cid, i + 1]));
    const coocRankMap = new Map(state.coocRanked.map((cid, i) => [cid, i + 1]));

    // Single shared sentinel — symmetric penalty for absence from either scorer.
    // A book absent from co-occurrence and one absent from PPMI both pay N_sentinel,
    // so neither scorer gets a hidden advantage from pool size differences.
    const N_sentinel = Math.max(state.ppmiRanked.length, state.coocRanked.length) + 1;

    const allCands = new Set([...state.ppmiRanked, ...state.coocRanked]);
    const fused    = [];
    for (const cid of allCands) {
        const rPpmi = ppmiRankMap.has(cid) ? ppmiRankMap.get(cid) : N_sentinel;
        const rCooc = coocRankMap.has(cid) ? coocRankMap.get(cid) : N_sentinel;
        fused.push({ cid, rank: (1 - t) * rCooc + t * rPpmi });
    }

    // Sort ascending by fused rank; break ties by cid alphabetically (deterministic)
    fused.sort((a, b) => a.rank !== b.rank ? a.rank - b.rank : (a.cid < b.cid ? -1 : 1));

    const top50 = fused.slice(0, 50);
    const top50Cids = top50.map(f => f.cid);
    state.results    = top50.map(({ cid, rank }) => ({
        cid,
        score:     rank,
        baseCount: state.baseCounts[cid] || 0,
    }));
    const { matchedCounts, multiMatchCounts } =
        computeMatchedVoterCounts(state.model, inputCids, top50Cids);
    state.matchedCounts    = matchedCounts;
    state.multiMatchCounts = multiMatchCounts;
    renderResults();
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

function getDropdownItems(query) {
    // Always uses sortedBooks (n_voters desc, cid asc) — no text-match reordering.
    // On keystroke the list is filtered but stays in the same popularity order,
    // so there's no jarring reshuffle as the user types.
    const q        = query.toLowerCase();
    const selected = new Set(state.bookList.map(b => b.cid));
    const base     = q
        ? sortedBooks.filter(b => b.title.toLowerCase().includes(q)
                               || b.author.toLowerCase().includes(q))
        : sortedBooks;
    return base.map(b => ({ ...b, isSelected: selected.has(b.cid) }));
}

function renderDropdown(items, windowSize) {
    elDropdown.innerHTML = '';
    const visible = items.slice(0, windowSize);
    if (items.length === 0) {
        const li = document.createElement('li');
        li.className = 'dropdown-no-matches';
        li.textContent = 'No matches';
        elDropdown.appendChild(li);
    } else {
        visible.forEach(({ cid, title, author, n_voters, isSelected }) => {
            const li = document.createElement('li');
            li.className = 'dropdown-item' + (isSelected ? ' disabled' : '');
            li.setAttribute('role', 'option');
            li.dataset.cid = cid;
            li.innerHTML =
                `<span class="item-left">`
              +   `<span class="item-title">${esc(title)}</span>`
              +   `<span class="item-sep"> · </span>`
              +   `<span class="item-author">${esc(author || '')}</span>`
              + `</span>`
              + `<span class="item-count">on ${n_voters} list${n_voters === 1 ? '' : 's'}</span>`;
            if (!isSelected) {
                li.addEventListener('mousedown', e => {
                    e.preventDefault();
                    const info = state.model.books[cid];
                    selectBook(cid, title, info.author || '', n_voters);
                });
            }
            elDropdown.appendChild(li);
        });
    }
    elDropdown.hidden = false;
}

function renderDropdownWithWindow() {
    renderDropdown(currentDropdownItems, dropdownWindow);
}

function closeDropdown() {
    elDropdown.hidden = true;
    elDropdown.innerHTML = '';
}

function activateItem(delta) {
    let items = [...elDropdown.querySelectorAll('.dropdown-item:not(.disabled)')];
    if (!items.length) return;
    const cur = elDropdown.querySelector('.dropdown-item.active');
    const idx = cur ? items.indexOf(cur) : -1;

    // Arrow down past last mounted item → grow window, re-render, then advance
    if (delta > 0 && idx === items.length - 1 && dropdownWindow < currentDropdownItems.length) {
        dropdownWindow = Math.min(dropdownWindow + WINDOW_PAGE, currentDropdownItems.length);
        renderDropdownWithWindow();
        items = [...elDropdown.querySelectorAll('.dropdown-item:not(.disabled)')];
    }

    const next = items[Math.max(0, Math.min(idx + delta, items.length - 1))];
    if (cur) cur.classList.remove('active');
    if (next) { next.classList.add('active'); next.scrollIntoView({ block: 'nearest' }); }
}

function onSearchFocus() {
    if (!state.model) return;
    if (!elDropdown.hidden) return;   // already open — don't reset scroll mid-browse
    elDropdown.scrollTop = 0;
    const q = elSearchInput.value.trim();
    currentDropdownItems = getDropdownItems(q);
    dropdownWindow = Math.min(WINDOW_INITIAL, Math.max(currentDropdownItems.length, 1));
    renderDropdownWithWindow();
}

function onSearchInput() {
    const q = elSearchInput.value.trim();
    currentDropdownItems = getDropdownItems(q);
    dropdownWindow = Math.min(WINDOW_INITIAL, Math.max(currentDropdownItems.length, 1));
    renderDropdownWithWindow();
    elDropdown.scrollTop = 0;   // reset scroll on keystroke so filtered list starts at top
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

function onDropdownScroll() {
    if (elDropdown.hidden) return;
    if (elDropdown.scrollTop + elDropdown.clientHeight >= elDropdown.scrollHeight - 80) {
        if (dropdownWindow < currentDropdownItems.length) {
            dropdownWindow = Math.min(dropdownWindow + WINDOW_PAGE, currentDropdownItems.length);
            renderDropdownWithWindow();
        }
    }
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
    collapseAll();   // book edits change both scores and evidence
    const inputCids = state.bookList.map(b => b.cid);

    if (inputCids.length === 0) {
        elMain.classList.remove('post-run');
        elMain.classList.add('pre-run');
        elResultsPanel.hidden = true;
        state.ppmiRanked    = [];
        state.coocRanked    = [];
        state.baseCounts    = {};
        state.results       = [];
        state.matchedCounts = {};
        fuseAndRender();   // clears header text via renderResults
        return;
    }

    // Layout: shift to two-column on first book selection
    elMain.classList.remove('pre-run');
    elMain.classList.add('post-run');
    elResultsPanel.hidden = false;

    // Both scorers run with full candidate pools (top_n=Infinity — no cap).
    // Fusion correctness requires complete rank lists; a lingering top-50 cutoff
    // would break the t=0 and t=1 endpoint guarantees.
    const ppmiRes = ppmiDirectScorer(
        state.ppmiMap, state.coocCounts, inputCids, state.model, Infinity);
    const coocRes = coocScorer(
        state.model, inputCids, COOC_ALPHA, COOC_GAMMA, Infinity);

    state.ppmiRanked = ppmiRes.ranked;
    state.coocRanked = coocRes.ranked;
    state.baseCounts = ppmiRes.bookCounts;   // raw co-occ sums (Σᵢ co-count)
    state.ppmiScores = ppmiRes.bookScores;   // PPMI sums (Σᵢ PPMI(input_i, rec))

    fuseAndRender();
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
        const multi = state.multiMatchCounts[cid] || 0;
        const bylineParts = [info.author, info.year].filter(Boolean);
        const byline = bylineParts.length ? ` · ${bylineParts.join(' · ')}` : '';
        const multiClause = (state.bookList.length > 1 && multi > 0)
            ? ` — ${multi} of them share multiple`
            : '';
        const li    = document.createElement('li');
        li.title    = `Blend rank: ${score.toFixed(2)}`;
        li.style.cursor = 'pointer';
        li.innerHTML =
            `<div class="result-title-row">`
          +   `<span class="result-title">${esc(info.title || cid)}</span>`
          +   `<span class="result-byline">${esc(byline)}</span>`
          + `</div>`
          + `<span class="result-count">on ${count} list${count === 1 ? '' : 's'} from voters who share at least one input${multiClause}</span>`
          + `<span class="result-chevron">›</span>`;
        if (DEBUG) {
            li.innerHTML +=
                `<span class="result-diag">co=${baseCount} · n=${info.n_voters ?? '?'}</span>`;
        }
        li.addEventListener('click', () => toggleExpansion(cid, li));
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
    elBlendSlider     = document.getElementById('blend-slider');
    elBlendValue      = document.getElementById('blend-value');

    // Build PPMI lookup once at startup (always needed for fusion)
    const { ppmiMap, coocCounts } = buildPPMILookup(state.model.voter_books);
    state.ppmiMap    = ppmiMap;
    state.coocCounts = coocCounts;

    // Pre-sort books for browsable dropdown (n_voters desc, cid asc tiebreak)
    sortedBooks = Object.entries(state.model.books)
        .sort(([cidA, a], [cidB, b]) => (b.n_voters - a.n_voters) || cidA.localeCompare(cidB))
        .map(([cid, info]) => ({ cid, title: info.title, author: info.author, n_voters: info.n_voters }));

    elSearchInput.addEventListener('focus',   onSearchFocus);
    elSearchInput.addEventListener('click',   onSearchFocus);  // handles stale-focus after book selection
    elSearchInput.addEventListener('input',   onSearchInput);
    elSearchInput.addEventListener('keydown', onSearchKeydown);
    elSearchInput.addEventListener('blur',    onSearchBlur);
    elDropdown.addEventListener('scroll',     onDropdownScroll, { passive: true });
    elBlendSlider.addEventListener('input',   fuseAndRender);  // drag only re-fuses, no re-scoring

    renderEntries();

    elLoading.hidden = true;
    elMain.hidden    = false;
}

async function init() {
    try {
        const res = await fetch('../data/model_data.json');
        if (!res.ok) throw new Error(res.status);
        state.model = await res.json();
        setupUI();
        // Expose internals for endpoint verification (?debug=1 or Playwright tests)
        window._k = { state, ppmiDirectScorer, coocScorer, buildVoterCards };
    } catch (e) {
        elLoading.textContent =
            'Could not load data. Start the server from the repo root: python3 -m http.server 8000';
    }
}

init();
