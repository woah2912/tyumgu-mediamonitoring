// Общее поведение форм: период, выбор источников, состояние отправки.
(function () {
  const presets = document.querySelector("[data-presets]");
  if (presets) {
    const from = document.getElementById("date_from");
    const to = document.getElementById("date_to");
    presets.addEventListener("click", (event) => {
      const days = event.target.dataset.days;
      if (!days) return;
      const end = new Date(presets.dataset.today);
      const start = new Date(end);
      start.setDate(start.getDate() - Number(days));
      from.value = start.toISOString().slice(0, 10);
      to.value = end.toISOString().slice(0, 10);
    });
  }

  const toggle = document.querySelector("[data-toggle-sources]");
  if (toggle) {
    const boxes = () => [...document.querySelectorAll('input[name="source_ids"]')];
    const refresh = () => {
      toggle.textContent = boxes().every((box) => box.checked) ? "Снять все" : "Выбрать все";
    };
    toggle.addEventListener("click", () => {
      const checked = !boxes().every((box) => box.checked);
      boxes().forEach((box) => { box.checked = checked; });
      refresh();
    });
    boxes().forEach((box) => box.addEventListener("change", refresh));
    refresh();
  }

  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", () => {
      const button = form.querySelector("button[data-busy]");
      if (button) {
        button.textContent = button.dataset.busy;
        button.disabled = true;
      }
    });
  });

  // Поле реакции нужно только для влиятельных упоминаний.
  document.querySelectorAll("[data-mention]").forEach((mention) => {
    const reaction = mention.querySelector("[data-reaction]");
    mention.querySelectorAll('input[type="radio"]').forEach((radio) => {
      radio.addEventListener("change", () => {
        reaction.hidden = !(radio.checked && radio.value === "yes");
      });
    });
  });
})();
