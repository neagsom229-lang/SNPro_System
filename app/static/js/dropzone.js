// Progressive enhancement for file inputs: wrap any
// <div class="dropzone" data-for="inputId"> to support drag-and-drop,
// click-to-browse, and a filename/size preview. Falls back to a plain
// file input if JS fails, since the real <input> is still present.
(function () {
  function humanSize(bytes) {
    if (!bytes && bytes !== 0) return "";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    let n = bytes;
    while (n >= 1024 && i < units.length - 1) {
      n /= 1024;
      i += 1;
    }
    return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
  }

  function describeFiles(input) {
    const files = Array.from(input.files || []);
    if (files.length === 0) return null;
    if (files.length === 1) return `${files[0].name} · ${humanSize(files[0].size)}`;
    const total = files.reduce((sum, f) => sum + f.size, 0);
    return `${files.length} files selected · ${humanSize(total)}`;
  }

  function setup(zone) {
    const inputId = zone.dataset.for;
    const input = document.getElementById(inputId);
    if (!input) return;

    const label = zone.querySelector(".dropzone-label");
    const defaultText = label ? label.textContent : "";

    function refresh() {
      const desc = describeFiles(input);
      zone.classList.toggle("has-file", !!desc);
      if (label) label.textContent = desc || defaultText;
    }

    zone.addEventListener("click", () => input.click());
    zone.setAttribute("tabindex", "0");
    zone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        input.click();
      }
    });

    ["dragenter", "dragover"].forEach((evt) =>
      zone.addEventListener(evt, (e) => {
        e.preventDefault();
        zone.classList.add("drag-over");
      })
    );
    ["dragleave", "drop"].forEach((evt) =>
      zone.addEventListener(evt, (e) => {
        e.preventDefault();
        zone.classList.remove("drag-over");
      })
    );
    zone.addEventListener("drop", (e) => {
      const dropped = e.dataTransfer.files;
      if (dropped && dropped.length) {
        input.files = dropped;
        refresh();
      }
    });

    input.addEventListener("change", refresh);
    refresh();
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".dropzone[data-for]").forEach(setup);
  });
})();
