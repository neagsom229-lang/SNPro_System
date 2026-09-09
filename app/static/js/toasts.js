// Converts server-rendered flash messages into slide-in toasts
// (top-right, auto-dismiss) instead of static inline banners.
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    const source = document.getElementById("flashSource");
    if (!source) return;

    let container = document.getElementById("toastStack");
    if (!container) {
      container = document.createElement("div");
      container.id = "toastStack";
      container.className = "toast-stack";
      document.body.appendChild(container);
    }

    const items = Array.from(source.querySelectorAll("[data-flash]"));
    items.forEach((item, i) => {
      const category = item.dataset.category || "info";
      const message = item.textContent.trim();
      setTimeout(() => spawnToast(container, message, category), i * 90);
    });
    source.remove();
  });

  const ICONS = {
    success: "bi-check-circle-fill",
    danger: "bi-exclamation-octagon-fill",
    warning: "bi-exclamation-triangle-fill",
    info: "bi-info-circle-fill",
  };

  function spawnToast(container, message, category) {
    const el = document.createElement("div");
    el.className = `snpro-toast ${category}`;
    el.setAttribute("role", "status");
    el.innerHTML = `
      <i class="bi ${ICONS[category] || ICONS.info}"></i>
      <span class="snpro-toast-msg"></span>
      <button type="button" class="snpro-toast-close" aria-label="Dismiss"><i class="bi bi-x"></i></button>
    `;
    el.querySelector(".snpro-toast-msg").textContent = message;
    container.appendChild(el);

    requestAnimationFrame(() => el.classList.add("in"));

    const remove = () => {
      el.classList.remove("in");
      el.classList.add("out");
      setTimeout(() => el.remove(), 220);
    };
    el.querySelector(".snpro-toast-close").addEventListener("click", remove);
    setTimeout(remove, 5000);
  }
})();
