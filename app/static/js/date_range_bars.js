// static/js/date_range_bars.js
(function () {
  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function ymd(year, month, day) {
    return `${year}-${pad2(month)}-${pad2(day)}`;
  }

  function monthName(m) {
    const names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return names[m - 1] || String(m);
  }

  function getContextParams(root) {
    const artist = root.dataset.artist || "";
    const album = root.dataset.album || "";
    const track = root.dataset.track || "";

    const params = new URLSearchParams();
    if (artist) params.set("artist", artist);
    if (album) params.set("album", album);
    if (track) params.set("track", track);

    return params;
  }

  async function apiGet(path, params) {
    const url = `${path}?${params.toString()}`;
    const res = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`API ${res.status}: ${txt}`);
    }
    return res.json();
  }

  // ---------- NEW: URL navigation to force Python-side refresh ----------
  // Desired URL examples:
  // /library/artists?page=1&from=2025-01-01&rangetype=1day
  // /library/artists?page=1&from=2025-01-01&rangetype=1month
  // /library/artists?page=1&from=2025-01-01&rangetype=year
  // /library/artists?page=1&from=2022-01-01&to=2022-10-27
  function navigateWithRange(root, from, to, rangeType) {
    console.log("navigateWithRange called:", { from, to, rangeType });
    const url = new URL(window.location.href);

    // Reset paging whenever the time window changes
    url.searchParams.set("page", "1");

    // Use your naming: from/to/rangetype
    url.searchParams.set("from", from);

    if (to) url.searchParams.set("to", to);
    else url.searchParams.delete("to");

    if (rangeType) url.searchParams.set("rangetype", rangeType);
    else url.searchParams.delete("rangetype");

    // Preserve current selection context if needed
    // (doesn't hurt even if your backend ignores these today)
    const ctx = getContextParams(root);
    for (const [k, v] of ctx.entries()) {
      url.searchParams.set(k, v);
    }

    console.log("Navigating to:", url.toString());
    window.location.href = url.toString();
  }
function lastDayOfMonth(y, m) {
  return new Date(y, m, 0).getDate(); // m is 1..12
}

function computeRangeFromState(state) {
  // Returns { from, to, rangetype } or null for "all time"
  if (!state.year) return null;

  if (state.level === "months") {
    // Whole year selected
    return { from: `${state.year}-01-01`, to: null, rangetype: "year" };
  }

  if (state.level === "days") {
    // Whole month selected
    const from = ymd(state.year, state.month, 1);
    return { from, to: null, rangetype: "1month" };
  }

  if (state.level === "daily") {
    // Single day selected
    const from = ymd(state.year, state.month, state.day);
    return { from, to: null, rangetype: "1day" };
  }

  // Fallback: if year is set but level is weird, treat as year
  return { from: `${state.year}-01-01`, to: null, rangetype: "year" };
}

/**
 * Apply range by navigating (Option A).
 * - If range is null => remove from/to/rangetype and go to page 1.
 */
function navigateFromState(root, state) {
  const range = computeRangeFromState(state);

  const url = new URL(window.location.href);
  url.searchParams.set("page", "1");

  if (!range) {
    url.searchParams.delete("from");
    url.searchParams.delete("to");
    url.searchParams.delete("rangetype");
  } else {
    url.searchParams.set("from", range.from);
    if (range.to) url.searchParams.set("to", range.to);
    else url.searchParams.delete("to");
    url.searchParams.set("rangetype", range.rangetype);
  }

  // preserve context params
  const ctx = getContextParams(root);
  for (const [k, v] of ctx.entries()) url.searchParams.set(k, v);

  window.location.href = url.toString();
}

  // Read current URL filter (so refresh/bookmark keeps drilldown consistent)
  function readUrlRange() {
    const url = new URL(window.location.href);
    const from = url.searchParams.get("from") || "";
    const to = url.searchParams.get("to") || "";
    const rangetype = url.searchParams.get("rangetype") || "";
    return { from, to, rangetype };
  }

  function parseYmd(s) {
    // expects YYYY-MM-DD
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s));
    if (!m) return null;
    const y = Number(m[1]);
    const mo = Number(m[2]);
    const d = Number(m[3]);
    if (!y || !mo || !d) return null;
    return { y, mo, d };
  }

  function renderCrumbs(root, state) {
  const el = root.querySelector("[data-drb-crumbs]");
  const parts = [];

  function crumbButton(label, onClick) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = label;
    btn.addEventListener("click", onClick);
    return btn;
  }

  el.innerHTML = "";

  // All time
  parts.push(crumbButton("All time", () => {
    // If you want "All time" to mean remove filters in URL:
    state.level = "years";
    state.year = null;
    state.month = null;
    state.day = null;
    navigateFromState(root, state); // ✅ updates URL + reload
  }));

  if (state.year) {
    parts.push(document.createTextNode(" / "));
    parts.push(crumbButton(String(state.year), () => {
      // Clicking the year crumb should select the whole year (rangetype=year)
      state.level = "months";
      state.month = null;
      state.day = null;
      navigateFromState(root, state); // ✅ updates URL + reload
    }));
  }

  if (state.month) {
    parts.push(document.createTextNode(" / "));
    parts.push(crumbButton(`${monthName(state.month)} ${state.year}`, () => {
      // Clicking the month crumb should select the whole month (rangetype=1month)
      state.level = "days";
      state.day = null;
      navigateFromState(root, state); // ✅ updates URL + reload
    }));
  }

  if (state.day) {
    parts.push(document.createTextNode(" / "));
    parts.push(crumbButton(ymd(state.year, state.month, state.day), () => {
      // Optional: clicking the day crumb re-applies the single-day range
      state.level = "daily";
      navigateFromState(root, state); // ✅ updates URL + reload
    }));
  }

  parts.forEach(p => el.appendChild(p));
}


  function renderBars(root, items, maxCount, labelKey, countKey, onClickRow) {
    const bars = root.querySelector("[data-drb-bars]");
    bars.innerHTML = "";

    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "drb__small drb__muted";
      empty.textContent = "No data in this range.";
      bars.appendChild(empty);
      return;
    }

    items.forEach(item => {
      const row = document.createElement("div");
      row.className = "drb__barRow drb__clickable";

      const label = document.createElement("div");
      label.className = "drb__label";
      label.textContent = item[labelKey];

      const track = document.createElement("div");
      track.className = "drb__barTrack";

      const fill = document.createElement("div");
      fill.className = "drb__barFill";
      const pct = maxCount > 0 ? (item[countKey] / maxCount) * 100 : 0;
      fill.style.width = `${pct}%`;
      track.appendChild(fill);

      const count = document.createElement("div");
      count.className = "drb__count";
      count.textContent = String(item[countKey]);

      row.appendChild(label);
      row.appendChild(track);
      row.appendChild(count);

      row.addEventListener("click", () => onClickRow(item));

      bars.appendChild(row);
    });
  }

  // Keep your existing results area behavior (daily shows list; non-daily shows muted prompt)
  function renderResults(root, payload, state) {
    const label = root.querySelector("[data-drb-rangeLabel]");
    const results = root.querySelector("[data-drb-results]");

    label.textContent = `${payload.range.from} → ${payload.range.to}`;
    results.innerHTML = "";

    const isDaily = state.level === "daily";

    if (!isDaily) {
      const p = document.createElement("div");
      p.className = "drb__small drb__muted";
      p.textContent = "Select a day to see scrobbles.";
      results.appendChild(p);
      return;
    }

    return;
  }

  async function fetchAndRenderResults(root, state, from, to) {
    const params = getContextParams(root);
    params.set("from", from);
    params.set("to", to);
    params.set("limit", "50");

    const payload = await apiGet("/api/daterange/results", params);
    renderResults(root, payload, state);
  }

  async function refresh(root, state) {
    renderCrumbs(root, state);

    const ctx = getContextParams(root);

    if (state.level === "years") {
      const data = await apiGet("/api/daterange/years", ctx);
      const maxCount = data.reduce((m, x) => Math.max(m, x.count), 0);

      renderBars(
        root,
        data.map(x => ({ label: String(x.year), year: x.year, count: x.count })),
        maxCount,
        "label",
        "count",
        async (item) => {
          // Clicking a year should change the Artists page range and reload
          console.log("Year bar clicked:", item.year);
          const from = `${item.year}-01-01`;
          navigateWithRange(root, from, null, "year");
        }
      );

      // Keep the left-side "range label" consistent even before clicking
      if (data.length) {
        const first = data[0].year;
        const last = data[data.length - 1].year;
        await fetchAndRenderResults(root, state, `${first}-01-01`, `${last}-12-31`);
      }
      return;
    }

    if (state.level === "months") {
      ctx.set("year", String(state.year));
      const data = await apiGet("/api/daterange/months", ctx);
      const maxCount = data.reduce((m, x) => Math.max(m, x.count), 0);

      renderBars(
        root,
        data.map(x => ({ label: monthName(x.month), month: x.month, count: x.count })),
        maxCount,
        "label",
        "count",
        async (item) => {
          // Clicking a month should change range and reload
          const from = ymd(state.year, item.month, 1);
          navigateWithRange(root, from, null, "1month");
        }
      );

      // Results label for the current year
      await fetchAndRenderResults(root, state, `${state.year}-01-01`, `${state.year}-12-31`);
      return;
    }

    if (state.level === "days") {
      ctx.set("year", String(state.year));
      ctx.set("month", String(state.month));
      const data = await apiGet("/api/daterange/days", ctx);
      const maxCount = data.reduce((m, x) => Math.max(m, x.count), 0);

      renderBars(
        root,
        data.map(x => ({ label: pad2(x.day), day: x.day, count: x.count })),
        maxCount,
        "label",
        "count",
        async (item) => {
          // Clicking a day should change range and reload
          const from = ymd(state.year, state.month, item.day);
          navigateWithRange(root, from, null, "1day");
        }
      );

      // Results label for the month
      const y = state.year;
      const m = state.month;
      const lastDay = new Date(y, m, 0).getDate();
      await fetchAndRenderResults(root, state, ymd(y, m, 1), ymd(y, m, lastDay));
      return;
    }

    if (state.level === "daily") {
      const from = ymd(state.year, state.month, state.day);
      await fetchAndRenderResults(root, state, from, from);
    }
  }

  function initOne(root) {
    console.log("Date range bars initializing...");
    // Default state
    const state = {
      level: "years",
      year: null,
      month: null,
      day: null,
    };

    // If URL already contains from/to/rangetype, align drilldown level on load.
    // This does NOT reload; it only selects the correct bar level display.
    const { from, to, rangetype } = readUrlRange();

    // If custom range (from+to), keep years level (no precise drilldown),
    // but the right panel will already be filtered by Python.
    if (from && to) {
      state.level = "years";
    } else if (from && rangetype) {
      const p = parseYmd(from);
      if (p) {
        if (rangetype === "year") {
          state.level = "months";
          state.year = p.y;
        } else if (rangetype === "1month") {
          state.level = "days";
          state.year = p.y;
          state.month = p.mo;
        } else if (rangetype === "1day") {
          // your UI shows daily results only at lowest level; we jump to daily
          state.level = "daily";
          state.year = p.y;
          state.month = p.mo;
          state.day = p.d;
        }
      }
    }

    refresh(root, state).catch(err => {
      const bars = root.querySelector("[data-drb-bars]");
      bars.innerHTML = `<div class="drb__small" style="color:#b00020;">${err.message}</div>`;
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-drb]").forEach(initOne);
  });
})();
