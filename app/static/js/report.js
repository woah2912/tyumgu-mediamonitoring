// Страница отчёта: ход обработки, графики и таблица публикаций.
(function () {
  const root = document.querySelector("[data-report]");
  if (!root) return;
  const reportId = root.dataset.report;
  const PAGE_SIZE = 20;
  const POLL_MS = 700;

  const TONES = { positive: "Позитив", neutral: "Нейтрально", negative: "Негатив" };
  const TONE_COLORS = { positive: "#2a78d6", neutral: "#b5b4ac", negative: "#e34948" };
  const SURFACE = "#fcfcfb";
  const GRID = "#e1e0d9";
  const INK = "#52514e";

  function updateCounter(steps) {
    const counter = document.getElementById("process-count");
    if (!counter) return;
    const done = steps.filter((step) => step.status !== "pending").length;
    counter.textContent = `${done} из ${steps.length}`;
  }

  function renderSteps(steps) {
    steps.forEach((step) => {
      const node = document.querySelector(`[data-code="${step.code}"]`);
      if (!node) return;
      node.className = `step step-${step.status}`;
      node.title = step.detail;
      node.querySelector(".step-detail").textContent = step.detail;
    });
    updateCounter(steps);
  }

  async function poll() {
    const response = await fetch(`/api/reports/${reportId}/status`);
    const data = await response.json();
    renderSteps(data.steps);
    if (data.status !== "processing") {
      window.location.reload();
      return;
    }
    setTimeout(poll, POLL_MS);
  }

  if (root.dataset.status === "processing") {
    poll();
  } else {
    fetch(`/api/reports/${reportId}/status`).then((r) => r.json()).then((data) => updateCounter(data.steps));
  }

  const payload = document.getElementById("report-data");
  if (!payload) return;
  const metrics = JSON.parse(payload.textContent).metrics;
  if (!metrics.timeline) return;

  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = INK;

  function legend() {
    return {
      position: "top",
      align: "start",
      labels: { boxWidth: 10, boxHeight: 10, padding: 14, usePointStyle: true, pointStyle: "rectRounded" },
    };
  }

  function datasets(rows) {
    return Object.keys(TONES).map((key) => ({
      label: TONES[key],
      data: rows.map((row) => row[key]),
      backgroundColor: TONE_COLORS[key],
      borderColor: SURFACE,
      borderWidth: 1,
      borderRadius: 2,
      maxBarThickness: 24,
    }));
  }

  function stackedChart(id, labels, rows, horizontal) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    const valueAxis = {
      stacked: true,
      beginAtZero: true,
      grid: { color: GRID, drawTicks: false },
      border: { display: false },
      ticks: { precision: 0, padding: 6 },
    };
    const labelAxis = { stacked: true, grid: { display: false }, border: { color: GRID } };
    new Chart(canvas, {
      type: "bar",
      data: { labels, datasets: datasets(rows) },
      options: {
        indexAxis: horizontal ? "y" : "x",
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false, axis: horizontal ? "y" : "x" },
        plugins: { legend: legend(), tooltip: { backgroundColor: "#0b0b0b", padding: 10, cornerRadius: 6 } },
        scales: horizontal ? { x: valueAxis, y: labelAxis } : { x: labelAxis, y: valueAxis },
      },
    });
  }

  stackedChart("timeline-chart", metrics.timeline.points.map((p) => p.label), metrics.timeline.points, false);
  stackedChart("topics-chart", metrics.topics.map((r) => r.name), metrics.topics, true);
  stackedChart("sources-chart", metrics.sources.map((r) => r.name), metrics.sources, true);

  // --- Таблица публикаций ---
  const table = document.getElementById("publications-table");
  const pager = document.getElementById("publications-pager");
  const search = document.getElementById("filter-search");
  const tone = document.getElementById("filter-tone");
  const topic = document.getElementById("filter-topic");
  const role = document.getElementById("filter-role");
  const level = document.getElementById("filter-level");
  let items = [];
  let tab = "relevant";
  let page = 1;
  let opened = null;

  const escapeHtml = (value) =>
    String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

  function filtered() {
    const query = search.value.trim().toLowerCase();
    return items.filter((item) => {
      if ((item.status === "relevant") !== (tab === "relevant")) return false;
      if (tone.value && item.sentiment !== tone.value) return false;
      if (topic.value && item.topic !== topic.value) return false;
      if (role.value && item.role !== role.value) return false;
      if (level.value && item.level !== level.value) return false;
      if (query && !`${item.title} ${item.source}`.toLowerCase().includes(query)) return false;
      return true;
    });
  }

  function details(item) {
    const words = item.evidence
      .slice(0, 6)
      .map((entry) => `<span class="word ${entry.weight < 0 ? "word-neg" : "word-pos"}">${escapeHtml(entry.word)}</span>`)
      .join("");
    const link = item.is_synthetic ? "" : `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">Открыть оригинал</a>`;
    return `
      <p>${escapeHtml(item.excerpt)}…</p>
      <dl class="row-details">
        <div><dt>Оценка тональности</dt><dd>${item.score.toFixed(2)}</dd></div>
        <div><dt>Главный объект</dt><dd>${escapeHtml(item.main_entity)}</dd></div>
        <div><dt>Релевантность</dt><dd>${item.relevance.toFixed(2)}</dd></div>
        <div><dt>Источник</dt><dd>${escapeHtml(item.level)} уровень</dd></div>
        ${item.reprints ? `<div><dt>Перепечаток</dt><dd>${item.reprints}</dd></div>` : ""}
        ${item.weight ? `<div><dt>Репутационный вес</dt><dd>${item.weight}</dd></div>` : ""}
      </dl>
      ${words ? `<p class="evidence">Оценку определили: ${words}</p>` : ""}
      ${link}`;
  }

  function renderTable() {
    const rows = filtered();
    const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    page = Math.min(page, pages);
    const slice = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

    const lastColumn = tab === "relevant" ? "<th>Роль</th>" : "<th>Причина удаления</th>";
    const body = slice
      .map((item) => {
        const last = tab === "relevant" ? `<td>${escapeHtml(item.role)}</td>` : `<td>${escapeHtml(item.reason)}</td>`;
        const open = opened === item.id;
        return `
        <tr class="row-toggle" data-id="${item.id}" aria-expanded="${open}">
          <td class="nowrap">${item.date}</td>
          <td><span class="strong-link">${escapeHtml(item.title)}</span>
            <div class="muted">${escapeHtml(item.source)}${item.is_synthetic ? ' <em class="tag">тест</em>' : ""}</div></td>
          <td>${escapeHtml(item.topic)}</td>
          <td class="nowrap"><span class="tone tone-${item.sentiment}">${item.sentiment_label}</span></td>
          ${last}
        </tr>
        ${open ? `<tr class="row-open"><td colspan="5">${details(item)}</td></tr>` : ""}`;
      })
      .join("");

    table.innerHTML = rows.length
      ? `<thead><tr><th>Дата</th><th>Публикация</th><th>Тема</th><th>Тональность</th>${lastColumn}</tr></thead><tbody>${body}</tbody>`
      : '<tbody><tr><td class="muted">Нет публикаций по выбранным условиям.</td></tr></tbody>';

    pager.innerHTML =
      pages > 1
        ? Array.from({ length: pages }, (_, index) => {
            const number = index + 1;
            return `<button class="pager-item ${number === page ? "active" : ""}" data-page="${number}">${number}</button>`;
          }).join("")
        : "";
  }

  table.addEventListener("click", (event) => {
    if (event.target.closest("a")) return;
    const row = event.target.closest(".row-toggle");
    if (!row) return;
    const id = Number(row.dataset.id);
    opened = opened === id ? null : id;
    renderTable();
  });

  pager.addEventListener("click", (event) => {
    if (event.target.dataset.page) {
      page = Number(event.target.dataset.page);
      opened = null;
      renderTable();
    }
  });

  [search, tone, topic, role, level].forEach((control) =>
    control.addEventListener("input", () => {
      page = 1;
      opened = null;
      renderTable();
    })
  );

  document.querySelectorAll(".tab").forEach((button) =>
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((other) => other.classList.toggle("active", other === button));
      tab = button.dataset.tab;
      page = 1;
      opened = null;
      renderTable();
    })
  );

  fetch(`/api/reports/${reportId}/publications`)
    .then((response) => response.json())
    .then((data) => {
      items = data;
      renderTable();
    });
})();
