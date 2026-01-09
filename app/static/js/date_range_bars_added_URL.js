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

    // Always: All time
    parts.push(crumbButton("All time", () => {
      state.level = "years";
      state.year = null;
      state.month = null;
      state.day = null;
      refresh(root, state);
    }));

    if (state.year) {
      parts.push(document.createTextNode(" / "));
      parts.push(crumbButton(String(state.year), () => {
        state.level = "months";
        state.month = null;
        state.day = null;
        refresh(root, state);
      }));
    }

    if (state.month) {
      parts.push(document.createTextNode(" / "));
      parts.push(crumbButton(`${monthName(state.month)} ${state.year}`, () => {
        state.level = "days";
        state.day = null;
        refresh(root, state);
      }));
    }

    if (state.day) {
      parts.push(document.createTextNode(" / "));
      parts.push(document.createTextNode(ymd(state.year, state.month, state.day)));
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

  // ✅ Updated: removed "Statistics" (Top artists / Top albums) entirely.
  function renderResults(root, payload, state) {
    const label = root.querySelector("[data-drb-rangeLabel]");
    const results = root.querySelector("[data-drb-results]");

    label.textContent = `${payload.range.from} → ${payload.range.to}`;
    results.innerHTML = "";

    const isDaily = state.level === "daily";

    // Non-daily: keep results area clean (no statistics panels)
    if (!isDaily) {
      const p = document.createElement("div");
      p.className = "drb__small drb__muted";
      p.textContent = "Select a day to see scrobbles.";
      results.appendChild(p);
      return;
    }

    // Daily: show raw scrobbles list (so user sees what actually happened that day)
    const secC = document.createElement("div");
    secC.className = "drb__resultsSection";
    const hC = document.createElement("h4");
    hC.textContent = "Scrobbles that day";
    secC.appendChild(hC);

    const rows = payload.rows || [];
    if (!rows.length) {
      const p = document.createElement("div");
      p.className = "drb__small drb__muted";
      p.textContent = "No scrobbles on this day for the current selection.";
      secC.appendChild(p);
    } else {
      const ul = document.createElement("ul");
      ul.className = "drb__list";
      rows.slice(0, 200).forEach(r => {
        const li = document.createElement("li");
        li.className = "drb__small";
        li.textContent = `${r.played_at} — ${r.artist} — ${r.album} — ${r.track}`;
        ul.appendChild(li);
      });
      secC.appendChild(ul);
    }

    results.appendChild(secC);
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
          state.year = item.year;
          state.level = "months";
          state.month = null;
          state.day = null;
          await refresh(root, state);

          // Results for whole year (now: just range label + muted text)
          await fetchAndRenderResults(root, state, `${state.year}-01-01`, `${state.year}-12-31`);
        }
      );

      // Initial results = all time (now: just range label + muted text)
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
          state.month = item.month;
          state.level = "days";
          state.day = null;
          await refresh(root, state);

          const y = state.year;
          const m = state.month;
          const lastDay = new Date(y, m, 0).getDate();
          await fetchAndRenderResults(root, state, ymd(y, m, 1), ymd(y, m, lastDay));
        }
      );

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
          state.day = item.day;
          state.level = "daily"; // lowest level
          renderCrumbs(root, state);

          // Daily does NOT render more bars
          const bars = root.querySelector("[data-drb-bars]");
          bars.innerHTML = "";

          const from = ymd(state.year, state.month, state.day);
          const to = from;
          await fetchAndRenderResults(root, state, from, to);
        }
      );

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
    const state = {
      level: "years",
      year: null,
      month: null,
      day: null,
    };
    refresh(root, state).catch(err => {
      const bars = root.querySelector("[data-drb-bars]");
      bars.innerHTML = `<div class="drb__small" style="color:#b00020;">${err.message}</div>`;
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-drb]").forEach(initOne);
  });
})();
