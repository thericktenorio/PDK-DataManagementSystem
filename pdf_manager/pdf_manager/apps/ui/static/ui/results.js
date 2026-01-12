(function () {
  const statusEl = document.getElementById("status");
  const fieldsEl = document.getElementById("fields");
  const messageEl = document.getElementById("message");
  const pagesEl = document.getElementById("pages");
  const copyBtn = document.getElementById("copyBtn");
  const downloadLink = document.getElementById("downloadLink");
  const jobId = window.__JOB_ID__;

  function render(j) {
    if (j.fields) fieldsEl.textContent = JSON.stringify(j.fields, null, 2);
    if (j.message) messageEl.value = j.message;
    if (j.pages) {
      pagesEl.innerHTML = "";
      j.pages.forEach((p, idx) => {
        const div = document.createElement("div");
        div.className = "tags";
        div.textContent = `Page ${idx + 1}: ${Array.isArray(p.tags) ? p.tags.join(", ") : ""}`;
        pagesEl.appendChild(div);
      });
    }
    if (j.job_id && j.job_id !== "00000000-0000-0000-0000-000000000000") {
      // only show link if at least one output path present
      if (j.output_pdf_path || j.signature_pdf_path || j.payment_voucher_pdf_path) {
        downloadLink.href = `/api/jobs/${j.job_id}/outputs`;
      } else {
        downloadLink.remove();
      }
    } else {
      downloadLink.remove();
    }
  }

  copyBtn.addEventListener("click", () => {
    messageEl.select();
    document.execCommand("copy");
  });

  // Transient flow (no DB job)
  if (jobId === "00000000-0000-0000-0000-000000000000") {
    const stored = sessionStorage.getItem("transient_result");
    if (stored) {
      const j = JSON.parse(stored);
      statusEl.textContent = "done";
      render(j);
    } else {
      statusEl.textContent = "Unavailable";
    }
    return;
  }

  // DB-backed flow: fetch status then fetch output details
  fetch(`/api/jobs/${jobId}`)
    .then(r => r.json())
    .then(j => {
      statusEl.textContent = j.status;
      if (j.status === "done") {
        // check for one or more outputs present
        return fetch(`/api/jobs/${jobId}/outputs`, { method: "HEAD" })
          .then(() => {
            // fetch detailed payload for fields/pages/message + paths
            return fetch(`/api/jobs/${jobId}?detail=1`);
          })
          .then(r2 => r2.json())
          .then(detail => { render(detail); });
      }
    })
    .catch(() => { statusEl.textContent = "error"; });

  // Optional: if you extend job_status_api to honor ?detail=1, return fields/pages/message there.
})();
