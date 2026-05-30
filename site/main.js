'use strict';

// Debug diagnostic columns (co=N · n=M): add ?debug=1 to URL.
// ?scorer= URL param retired — use the blend slider instead.
const DEBUG = new URLSearchParams(window.location.search).get('debug') === '1';

// Co-occurrence fallback params (always used for fusion)
const COOC_ALPHA = 1.0;
const COOC_GAMMA = 1.0;

// ── State ──────────────────────────────────────────────────────────────────────
const state = {
    model:         null,   // loaded model_data.json
    ppmiMap:       null,   // {cid → Map{cid → ppmi_value}} — built at startup
    coocCounts:    null,   // {cid → Map{cid → raw count}} — for debug display
    bookList:      [],     // [{cid, title, author, n_voters}] — ordered
    ppmiRanked:    [],     // all PPMI-reachable candidates, full pool, ordered by PPMI rank
    coocRanked:    [],     // all co-occ-reachable candidates, full pool, ordered by co-occ rank
    baseCounts:    {},     // {cid: co-occ count sum} — from PPMI scorer, for debug display
    results:       [],     // [{cid, score, baseCount}] — fused top-50
    matchedCounts: {},     // {cid: count} — for "on Y lists" display
    blendT:        0.5,    // current slider value
    expandedCid:   null,   // currently expanded result cid (accordion: one open at a time)
};

const MAX_BOOKS = 15;

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

// ── Detail panel ──────────────────────────────────────────────────────────────

function computeExpansionDetail(cid, inputCids, model) {
    const inputSet  = new Set(inputCids);
    const tiers     = {};   // sharedCount → [voter_name, ...]
    const inputCooc = Object.fromEntries(inputCids.map(i => [i, 0]));

    for (const [voter, books] of Object.entries(model.voter_books)) {
        const voterSet = new Set(books.map(([c]) => c));
        if (!voterSet.has(cid)) continue;
        const shared = inputCids.filter(i => voterSet.has(i));
        if (!shared.length) continue;
        const k = shared.length;
        if (!tiers[k]) tiers[k] = [];
        tiers[k].push(voter);
        for (const i of shared) inputCooc[i]++;
    }

    const sortedTiers = Object.entries(tiers)
        .map(([k, voters]) => ({ k: +k, voters }))
        .sort((a, b) => b.k - a.k);

    // Top-2 connecting inputs (skip for single-input; omit if all tied)
    let topInputs = [];
    if (inputCids.length >= 2) {
        const sorted = inputCids.slice().sort((a, b) => inputCooc[b] - inputCooc[a]);
        topInputs = sorted.slice(0, 2);
        // Suppress if top-2 are tied with each other (all equally connected)
        if (inputCooc[topInputs[0]] === inputCooc[topInputs[topInputs.length - 1]]) {
            topInputs = [];
        }
    }

    return { sortedTiers, topInputs, inputCooc,
             totalMatchedVoters: Object.values(tiers).flat().length };
}

function renderDetailPanel(cid, detail, inputCids, model) {
    const info   = model.books[cid] || {};
    const nv     = info.n_voters || 0;
    const total  = model.n_voters;

    // ── Badge and headline ────────────────────────────────────────────────────
    let badge, headline;
    if (nv === 1) {
        badge    = 'Deep cut';
        headline = `A rare deep cut — on just 1 of ${total} reader lists — but the reader who loves it shares your taste.`;
    } else if (nv <= 5) {
        badge    = 'Distinctive pick';
        headline = `A distinctive pick — on ${nv} of ${total} reader lists — but the readers who love it also share your taste.`;
    } else if (nv <= 20) {
        badge    = 'Popular pick';
        headline = `A well-regarded book — on ${nv} of ${total} reader lists — and shared by readers who match your taste.`;
    } else {
        badge    = 'Widely loved';
        headline = `A widely-loved classic — on ${nv} of ${total} reader lists — and shared by readers with your taste.`;
    }

    // ── Tier bars ─────────────────────────────────────────────────────────────
    const maxTierSize = detail.sortedTiers.length
        ? Math.max(...detail.sortedTiers.map(t => t.voters.length))
        : 1;
    const NAME_CAP = 5;

    const tiersHTML = detail.sortedTiers.length === 0
        ? `<div class="detail-empty">No direct overlap in the data — surfaced by PPMI association.</div>`
        : detail.sortedTiers.map(({ k, voters }) => {
            const barPct  = Math.round(100 * voters.length / maxTierSize);
            const shown   = voters.slice(0, NAME_CAP);
            const extra   = voters.length - shown.length;
            const nameStr = shown.join(', ') + (extra > 0 ? `, +${extra} more` : '');
            const label   = inputCids.length === 1
                ? 'Readers who share your book'
                : `Readers who share ${k} of your book${k === 1 ? '' : 's'}`;
            return `<div class="detail-tier">
  <div class="detail-tier-label">${esc(label)}</div>
  <div class="tier-bar-row">
    <span class="tier-count">${voters.length}</span>
    <div class="tier-bar-track"><div class="tier-bar-fill" style="width:${barPct}%"></div></div>
  </div>
  <div class="tier-voters">${esc(nameStr)}</div>
</div>`;
        }).join('');

    // ── Connecting inputs ─────────────────────────────────────────────────────
    let connectHTML = '';
    if (detail.topInputs.length >= 2) {
        const names = detail.topInputs.map(iCid => {
            const t = (model.books[iCid] || {}).title || iCid;
            return `<em>${esc(t)}</em>`;
        });
        connectHTML = `<div class="detail-connections">Most often listed alongside your ${names.join(' and ')}.</div>`;
    } else if (detail.topInputs.length === 1) {
        const t = (model.books[detail.topInputs[0]] || {}).title || detail.topInputs[0];
        connectHTML = `<div class="detail-connections">Most often listed alongside your <em>${esc(t)}</em>.</div>`;
    }

    const el = document.createElement('div');
    el.className = 'result-detail';
    el.innerHTML =
        `<div class="detail-headline">${esc(headline)}</div>`
      + `<span class="detail-badge">${esc(badge)}</span>`
      + `<div class="detail-tiers">${tiersHTML}</div>`
      + connectHTML;
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
    const detail = computeExpansionDetail(cid, inputCids, state.model);
    const panel  = renderDetailPanel(cid, detail, inputCids, state.model);
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
    state.matchedCounts = computeMatchedVoterCounts(state.model, inputCids, top50Cids);
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
    state.baseCounts = ppmiRes.bookCounts;   // raw co-occ sums for ?debug=1

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
        const li    = document.createElement('li');
        li.title    = `Blend rank: ${score.toFixed(2)}`;
        li.style.cursor = 'pointer';
        li.innerHTML =
            `<span class="result-title">${esc(info.title || cid)}</span>`
          + `<span class="result-author">${esc(info.author || '')}</span>`
          + `<span class="result-count">on ${count} list${count === 1 ? '' : 's'} from voters who share your taste</span>`;
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

    elSearchInput.addEventListener('input',   onSearchInput);
    elSearchInput.addEventListener('keydown', onSearchKeydown);
    elSearchInput.addEventListener('blur',    onSearchBlur);
    elBlendSlider.addEventListener('input',   fuseAndRender);  // drag only re-fuses, no re-scoring

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
        // Expose internals for endpoint verification (?debug=1 or Playwright tests)
        window._k = { state, ppmiDirectScorer, coocScorer };
    } catch (e) {
        elLoading.textContent =
            'Could not load data. Start the server from the repo root: python3 -m http.server 8000';
    }
}

init();
