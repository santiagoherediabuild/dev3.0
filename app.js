(function () {
  "use strict";

  const state = {
    all: [],
    filtered: [],
  };

  const els = {
    list: document.getElementById("manifest-list"),
    empty: document.getElementById("empty-state"),
    noResults: document.getElementById("no-results"),
    search: document.getElementById("search"),
    minScore: document.getElementById("min-score"),
    minScoreValue: document.getElementById("min-score-value"),
    jurisdiction: document.getElementById("jurisdiction"),
    capability: document.getElementById("capability"),
    sortBy: document.getElementById("sort-by"),
    resetBtn: document.getElementById("reset-filters"),
    statCount: document.getElementById("stat-count"),
    statTop: document.getElementById("stat-top"),
    statUpdated: document.getElementById("stat-updated"),
  };

  function currency(value) {
    if (value === null || value === undefined || isNaN(value)) return null;
    return new Intl.NumberFormat("en-AU", {
      style: "currency",
      currency: "AUD",
      maximumFractionDigits: 0,
    }).format(value);
  }

  function daysUntil(dateStr) {
    if (!dateStr) return null;
    const target = new Date(dateStr);
    if (isNaN(target.getTime())) return null;
    const now = new Date();
    const diffMs = target.setHours(0, 0, 0, 0) - now.setHours(0, 0, 0, 0);
    return Math.round(diffMs / 86400000);
  }

  function formatDate(dateStr) {
    if (!dateStr) return "No close date listed";
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
  }

  function scoreClass(score) {
    if (score >= 8) return "high";
    if (score >= 6) return "mid";
    return "";
  }

  function populateFilterOptions(tenders) {
    const jurisdictions = new Set();
    const capabilities = new Set();
    tenders.forEach((t) => {
      if (t.state) jurisdictions.add(t.state);
      if (t.recommended_capability) capabilities.add(t.recommended_capability);
    });

    [...jurisdictions].sort().forEach((j) => {
      const opt = document.createElement("option");
      opt.value = j;
      opt.textContent = j;
      els.jurisdiction.appendChild(opt);
    });

    [...capabilities].sort().forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      els.capability.appendChild(opt);
    });
  }

  function renderEntry(t, index) {
    const li = document.createElement("li");
    li.className = "manifest-entry";

    const days = daysUntil(t.close_date);
    let dayLabel = "";
    if (days !== null) {
      if (days < 0) dayLabel = "Closed";
      else if (days === 0) dayLabel = "Closes today";
      else dayLabel = `${days} day${days === 1 ? "" : "s"} to close`;
    }

    const valueLabel = currency(t.value);
    const warn = days !== null && days >= 0 && days <= 7;

    const reasonsHtml = (t.match_reasons || [])
      .map((r) => `<span class="reason-chip">${escapeHtml(r)}</span>`)
      .join("");

    const titleHtml = t.url
      ? `<a href="${escapeAttr(t.url)}" target="_blank" rel="noopener">${escapeHtml(t.title)}</a>`
      : escapeHtml(t.title);

    li.innerHTML = `
      <div class="rank-col">${index + 1}</div>
      <div class="entry-body">
        <h2 class="entry-title">${titleHtml}</h2>
        <div class="entry-meta">
          <span>${escapeHtml(t.agency || "Agency not listed")}</span>
          <span>${formatDate(t.close_date)}</span>
          ${dayLabel ? `<span class="${warn ? "meta-warn" : ""}">${dayLabel}</span>` : ""}
          ${valueLabel ? `<span>${valueLabel}</span>` : ""}
        </div>
        ${t.description ? `<p class="entry-description">${escapeHtml(t.description)}</p>` : ""}
        <div class="entry-reasons">${reasonsHtml}</div>
        <div class="entry-capability"><span class="dot"></span>${escapeHtml(t.recommended_capability || "Supply Chain & Operations Advisory")}</div>
      </div>
      <div class="score-col">
        <div class="score-number ${scoreClass(t.match_score)}">${t.match_score.toFixed(1)}</div>
        <div class="score-out-of">out of 10</div>
        <div class="score-gauge"><div class="score-gauge-fill" style="width:${(t.match_score / 10) * 100}%"></div></div>
      </div>
    `;
    return li;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
  }

  function escapeAttr(str) {
    return (str || "").replace(/"/g, "&quot;");
  }

  function applyFilters() {
    const q = els.search.value.trim().toLowerCase();
    const minScore = parseFloat(els.minScore.value);
    const jurisdiction = els.jurisdiction.value;
    const capability = els.capability.value;
    const sortBy = els.sortBy.value;

    let out = state.all.filter((t) => {
      if (t.match_score < minScore) return false;
      if (jurisdiction && t.state !== jurisdiction) return false;
      if (capability && t.recommended_capability !== capability) return false;
      if (q) {
        const hay = `${t.title} ${t.agency} ${t.description}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    if (sortBy === "score") {
      out.sort((a, b) => b.match_score - a.match_score);
    } else if (sortBy === "close") {
      out.sort((a, b) => {
        const da = a.close_date ? new Date(a.close_date).getTime() : Infinity;
        const db = b.close_date ? new Date(b.close_date).getTime() : Infinity;
        return da - db;
      });
    } else if (sortBy === "value") {
      out.sort((a, b) => (b.value || 0) - (a.value || 0));
    }

    state.filtered = out;
    render();
  }

  function render() {
    els.list.innerHTML = "";
    const hasSource = state.all.length > 0;
    els.empty.hidden = hasSource;
    els.noResults.hidden = !hasSource || state.filtered.length > 0;

    if (!hasSource || state.filtered.length === 0) return;

    state.filtered.forEach((t, i) => els.list.appendChild(renderEntry(t, i)));
  }

  function updateStats(data) {
    els.statCount.textContent = state.all.length;
    const top = state.all.reduce((m, t) => Math.max(m, t.match_score), 0);
    els.statTop.textContent = state.all.length ? top.toFixed(1) : "–";
    if (data.generated_at) {
      const d = new Date(data.generated_at);
      els.statUpdated.textContent = isNaN(d.getTime())
        ? "–"
        : d.toLocaleDateString("en-AU", { day: "numeric", month: "short" });
    }
  }

  function bindEvents() {
    els.search.addEventListener("input", applyFilters);
    els.minScore.addEventListener("input", () => {
      els.minScoreValue.textContent = els.minScore.value;
      applyFilters();
    });
    els.jurisdiction.addEventListener("change", applyFilters);
    els.capability.addEventListener("change", applyFilters);
    els.sortBy.addEventListener("change", applyFilters);
    els.resetBtn.addEventListener("click", () => {
      els.search.value = "";
      els.minScore.value = 0;
      els.minScoreValue.textContent = "0";
      els.jurisdiction.value = "";
      els.capability.value = "";
      els.sortBy.value = "score";
      applyFilters();
    });
  }

  async function init() {
    bindEvents();
    try {
      const res = await fetch("data/tenders.json", { cache: "no-store" });
      const data = await res.json();
      state.all = (data.tenders || []).slice();
      populateFilterOptions(state.all);
      updateStats(data);
      applyFilters();
    } catch (e) {
      console.error("Could not load data/tenders.json", e);
      els.empty.hidden = false;
    }
  }

  init();
})();
