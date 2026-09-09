(function () {
  const el = document.getElementById("jobStatusRoot");
  if (!el) return;

  const jobId = el.dataset.jobId;
  const statusUrl = `/tools/job/${jobId}/status.json`;

  const bar = document.getElementById("jobProgressBar");
  const pill = document.getElementById("jobStatusPill");
  const msg = document.getElementById("jobMessage");
  const downloadWrap = document.getElementById("jobDownloadWrap");

  function render(data) {
    if (bar) bar.style.width = (data.progress || 0) + "%";
    if (msg) msg.textContent = data.message || "";
    if (pill) {
      pill.textContent = data.status;
      pill.className = "status-pill " + data.status;
    }
    const track = bar ? bar.closest(".progress-snpro") : null;
    if (track) track.classList.toggle("is-active", data.status === "pending" || data.status === "running");
    if (data.status === "success" && data.has_result && downloadWrap) {
      downloadWrap.classList.remove("d-none");
    }
    return data.status === "success" || data.status === "failure";
  }

async function poll() {
  try {
    const res = await fetch(statusUrl);
    if (res.status === 429) {
      // Back off and retry after 10 seconds
      setTimeout(poll, 10000);
      return;
    }
    const data = await res.json();
    const done = render(data);
    if (!done) setTimeout(poll, 5000); // 5 seconds between normal polls
  } catch (e) {
    setTimeout(poll, 5000);
  }
}

  poll();
})();
