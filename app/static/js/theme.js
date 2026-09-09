(function () {
  const root = document.documentElement;
  const stored = localStorage.getItem("snpro-theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const initial = stored || (prefersDark ? "dark" : "light");
  root.setAttribute("data-theme", initial);

  document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("themeToggle");
    const icon = document.getElementById("themeIcon");

    function paintIcon(theme) {
      if (!icon) return;
      icon.className = theme === "dark" ? "bi bi-sun" : "bi bi-moon-stars";
    }
    paintIcon(initial);

    if (btn) {
      btn.addEventListener("click", function () {
        const current = root.getAttribute("data-theme");
        const next = current === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        localStorage.setItem("snpro-theme", next);
        paintIcon(next);
      });
    }
  });
})();
