(()=> {
  const dropzone = document.getElementById("dropzone");
  const picker = document.getElementById("filePicker");
  const progress = document.getElementById("progress");
  const statusEl = document.getElementById("status");
  const maxMb = Number(dropzone?.dataset?.maxMb || 25);


  // ----- Axios Instance (CSRF + same defaults) -----
  const api = axios.create({
    baseURL: "/",
    withCredentials: true,
    timeout: 60_000, // 60s
    xsrfCookieName: "csrftoken",
    xsrfHeaderName: "X-CSRFToken",
    headers: { "Accept": "application/json" }
  });


  // Response interceptor to normalize server errors
  api.interceptors.response.use(
    (resp) => resp,
    (err) => {
      // preference : server-provided message as available
      const data = err?.response?.data;
      const msg = 
        (data && (data.error || data.detail || data.message)) ||
        err.message ||
        "Unknown error";
      return Promise.reject(new Error(msg));
    }
  );


  // ----- UI Helper Functions -----
  function preventAll(e) { e.preventDefault(); e.stopPropagation(); }

  function setStatus(msg) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
  }

  function setProgress(pct) {
    if (!progress) return;
    const v = Math.max(0, Math.min(100, Number(pct) || 0));
    if (progress.style) progress.style.display = "block";
    if ("value" in progress) progress.value = v;
    if ("ariaValueNow" in progress) progress.ariaValueNow = String(v);
  }

  function showProgress() {
    if (!progress) return;
    if (progress.style) progress.style.display = "block";
    setProgress(0);
  }

  function hideProgress() {
    if (!progress) return;
    if (progress.style) progress.style.display = "none";
  }

  function validateFile(file) {
    if (!file) { throw new Error("No file selected."); }
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      throw new Error("Only .pdf files are allowed.");
    }
    if (file.size > maxMb * 1024 * 1024) {
      throw new Error(`File too large (>${maxMb}MB).`);
    }
  }

  // ----- Upload with retry (idempotent enough for single file posts) -----
  async function uploadFile(file) {
    validateFile(file);

    const form = new FormData();
    form.append("file", file);

    showProgress();
    setStatus("Uploading...");

    const doPost = () =>
      api.post("/api/upload/", form, {
        onUploadProgress: (e) => {
          if (e && e.total) {
            const pct = Math.round((e.loaded / e.total) * 100);
            setProgress(pct);
            setStatus(`Uploading... ${pct}%`);
          } else {
            // Some browsers won't supply totals; keep indeterminate text
            setStatus("Uploading...");
          }
        },
      });
    
    // Simple retry (1 retry on transient failure)
    try {
      const resp = await doPost();
      return resp.data;
    } catch (err1) {
      // retry only for network-ish errors; tweak as needed
      if (/timeout|network|Failed to fetch|Network Error/i.test(String(err1))) {
        setStatus("Retrying upload...");
        const resp2 = await doPost();
        return resp2.data;
      }
      throw err1;
    } finally {
      hideProgress();
    }
  }


  async function handleFile(file) {
    try {
      const data = await uploadFile(file);

      // Transient (no DB) path support
      if (data.job_id === "00000000-0000-0000-0000-000000000000" && data.status === "done") {
        sessionStorage.setItem("transient_result", JSON.stringify(data));
      }

      if (!data.job_id) {
        throw new Error("Upload succeeded, but server did not return job_id.");
      }

      setStatus("Processing...");
      window.location.href = `/results/${data.job_id}/`;
    } catch (err) {
      console.error(err);
      setStatus("");
      alert(String(err.message || err));
    }
  }


  // ----- Drag & Drop Wiring -----
  ["dragenter", "dragover", "dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, preventAll, false)
  );
  dropzone.addEventListener("dragover", () => dropzone.classList.add("is-dragover"));
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-dragover"));
  dropzone.addEventListener("drop", (e) => {
    dropzone.classList.remove("is-dragover");
    const file = e.dataTransfer?.files?.[0];
    if (file) handleFile(file);
  });


  // ----- Click / Keyboard Accessibility -----
  dropzone.addEventListener("click", () => picker.click());
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " " ) {
      e.preventDefault();
      picker.click();
    }
  });
  picker.addEventListener("change", () => {
    const file = picker.files?.[0];
    picker.value = ""; // reset for next selection
    if (file) handleFile(file);
  });
})();