// Отладка сбора: живой журнал запуска и проверка адреса.
(function () {
  const STAGES = {
    fetch: "запрос", parse: "разбор", skip: "пропуск", match: "найдено",
    article: "статья", saved: "сохранено", error: "ошибка", done: "итог",
  };
  const POLL_MS = 1000;

  const escapeHtml = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

  function fragmentsHtml(fragments) {
    return (fragments || [])
      .map((item) => `<p class="fragment">${escapeHtml(item.before)}<mark class="${item.strength === "weak" ? "weak" : ""}">${escapeHtml(item.match)}</mark>${escapeHtml(item.after)}</p>`)
      .join("");
  }

  function link(url, text) {
    return url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(text || url)}</a>` : escapeHtml(text);
  }

  // --- Журнал запуска ---
  const log = document.getElementById("log");
  if (log) {
    const onlyFound = document.getElementById("only-found");
    const state = document.getElementById("log-state");
    const counters = document.getElementById("log-counters");
    let lastId = 0;
    let wasRunning = false;

    function row(event) {
      const node = document.createElement("div");
      node.className = `log-row stage-row-${event.stage}`;
      node.dataset.stage = event.stage;
      const details = event.details || {};
      let extra = "";
      if (event.title) extra += `<div class="log-title">${link(event.url, event.title)}</div>`;
      if (details.objects) extra += `<div class="kv">${details.objects.map((o) => `<span>${escapeHtml(o.name)}: ${o.strong + o.weak} раз${o.in_title ? ", в заголовке" : ""}</span>`).join("")}</div>`;
      extra += fragmentsHtml(details.fragments);
      if (details.entities && details.entities.length) extra += `<div class="kv"><span>Сущности: ${escapeHtml(details.entities.join(", "))}</span></div>`;
      if (event.stage === "fetch" && details.content_type) extra += `<div class="kv"><span>${escapeHtml(details.content_type)}</span></div>`;
      node.innerHTML = `
        <span class="log-time">${event.at}</span>
        <span class="log-source" title="${escapeHtml(event.source)}">${escapeHtml(event.source)}</span>
        <span class="stage stage-${event.stage}">${STAGES[event.stage] || event.stage}</span>
        <div><div>${escapeHtml(event.message)}</div>${extra}</div>`;
      node.hidden = onlyFound.checked && event.stage === "skip";
      return node;
    }

    async function poll() {
      const response = await fetch(`/api/debug/runs/${log.dataset.run}/events?after=${lastId}`);
      const data = await response.json();
      const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
      data.events.forEach((event) => {
        log.appendChild(row(event));
        lastId = event.id;
      });
      if (nearBottom) log.scrollTop = log.scrollHeight;
      counters.innerHTML = Object.entries(data.counts)
        .map(([stage, count]) => `<span class="counter">${STAGES[stage] || stage}: ${count}</span>`)
        .join("");
      state.textContent = data.running ? "идёт сбор, журнал обновляется" : "запуск завершён";
      if (wasRunning && !data.running) {
        window.location.reload();  // обновить итоги в списке запусков
        return;
      }
      wasRunning = data.running;
      if (data.running || data.events.length) setTimeout(poll, data.running ? POLL_MS : 0);
    }

    onlyFound.addEventListener("change", () => {
      log.querySelectorAll('[data-stage="skip"]').forEach((node) => { node.hidden = onlyFound.checked; });
    });
    poll();
  }

  // --- Проверка адреса ---
  const form = document.getElementById("inspect-form");
  const result = document.getElementById("inspect-result");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    button.textContent = "Проверяю…";
    result.innerHTML = '<p class="hint">Запрашиваю адрес и анализирую записи…</p>';
    try {
      const response = await fetch("/api/debug/inspect", { method: "POST", body: new FormData(form) });
      const data = await response.json();
      const steps = data.steps
        .map((step) => `<div class="log-row"><span class="log-time">${step.at}</span><span class="log-source">проверка</span><span class="stage stage-${step.stage}">${STAGES[step.stage] || step.stage}</span><div>${escapeHtml(step.message)}</div></div>`)
        .join("");
      const found = data.items.filter((item) => item.found);
      const items = data.items
        .map((item) => {
          if (!item.found) return `<div class="inspect-item"><span class="muted">${item.published}</span> ${link(item.url, item.title)} <span class="muted">— упоминаний нет</span></div>`;
          const objects = item.objects.map((o) => `${escapeHtml(o.name)}: ${o.strong + o.weak}`).join(", ");
          const words = (item.evidence || []).map((e) => `<span class="word ${e.weight < 0 ? "word-neg" : "word-pos"}">${escapeHtml(e.word)}</span>`).join("");
          return `<div class="inspect-item found">
            <div><span class="muted">${item.published}</span> <strong>${link(item.url, item.title)}</strong></div>
            <div class="kv"><span>Объекты: ${objects}</span><span>Тема: ${escapeHtml(item.topic)}</span><span class="tone tone-${item.tone}">тональность ${item.tone_score.toFixed(2)}</span></div>
            ${fragmentsHtml(item.fragments)}
            ${item.entities.length ? `<div class="kv"><span>Сущности: ${escapeHtml(item.entities.join(", "))}</span></div>` : ""}
            ${words ? `<p class="evidence">Тональность определили: ${words}</p>` : ""}
          </div>`;
        })
        .join("");
      result.innerHTML = `<h3>Шаги</h3><div class="log">${steps}</div>
        <h3>Записи: ${data.items.length}, с упоминаниями: ${found.length}</h3>${items}`;
    } catch (error) {
      result.innerHTML = `<div class="notice notice-error">Проверка не удалась: ${escapeHtml(error.message)}</div>`;
    } finally {
      button.disabled = false;
      button.textContent = "Проверить";
    }
  });
})();
