export function bindMappingStudioViewActions(deps) {
  const {
    state,
    render,
    showToast,
    withActorHeaders,
  } = deps;

  document.querySelectorAll(".review-upload-input").forEach(input => {
    input.addEventListener("change", (event) => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      showToast("Analyzing uploaded file and preparing a review item...");
      const formData = new FormData();
      formData.append("file", file);

      fetch(`/api/v1/mapping/ai-generate?partner=${encodeURIComponent(state.partner)}`, {
        method: "POST",
        body: formData
      })
        .then(r => r.json().then(body => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          if (!ok) throw new Error(body.detail || "Upload analysis failed");
          state.studio.fileName = file.name;
          state.studio.headers = body.headers || [];
          state.studio.sampleRows = body.sampleRows || [];
          state.studio.config = body.config;
          state.studio.draftMappingId = body.draftMappingId || null;
          state.studio.reviewItemId = body.reviewItemId || null;
          state.studio.configStatus = body.configStatus || null;
          state.studio.isRuntimeEligible = body.isRuntimeEligible || false;
          state.studio.handoffConfirmed = false;
          if (body.reviewItemId) {
            state.selectedReviewPacketId = body.reviewItemId;
          }
          showToast("Review item created. Opening Review Center.");
          location.hash = "review-center";
          input.value = "";
        })
        .catch(err => {
          showToast(err.message || "Upload analysis failed");
          input.value = "";
        });
    });
  });

  const studioExcelUpload = document.getElementById("studio-excel-upload");
  if (studioExcelUpload) {
    studioExcelUpload.addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const partner = document.getElementById("studio-partner-select")?.value || "VNPAY";

      showToast("Uploading sample and generating a draft mapping...");
      state.studio.loading = true;
      render();

      const formData = new FormData();
      formData.append("file", file);

      fetch(`/api/v1/mapping/ai-generate?partner=${encodeURIComponent(partner)}`, {
        method: "POST",
        body: formData
      })
        .then(r => r.json().then(body => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          state.studio.loading = false;
          if (!ok) throw new Error(body.detail || "AI gen failed");

          state.studio.fileName = file.name;
          state.studio.headers = body.headers || [];
          state.studio.sampleRows = body.sampleRows || [];
          state.studio.config = body.config;
          state.studio.draftMappingId = body.draftMappingId || null;
          state.studio.reviewItemId = body.reviewItemId || null;
          state.studio.configStatus = body.configStatus || null;
          state.studio.isRuntimeEligible = body.isRuntimeEligible || false;
          state.studio.handoffConfirmed = false;
          state.studio.step = 2;
          if (body.reviewItemId) {
            state.selectedReviewPacketId = body.reviewItemId;
            showToast("Draft created. Opening Review Center with the review drawer.");
            location.hash = "review-center";
            return;
          }

          showToast("Draft created. Review now continues in the Review Center.");
          render();
        })
        .catch(err => {
          state.studio.loading = false;
          showToast("AI Gen failed: " + err.message);
          render();
        });
    });
  }

  const studioJsonUpload = document.getElementById("studio-json-upload");
  if (studioJsonUpload) {
    studioJsonUpload.addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const json = JSON.parse(event.target.result);
          state.studio.config = json;
          state.studio.fileName = file.name;
          state.studio.step = 2;
          state.studio.handoffConfirmed = false;
          state.studio.headers = (json.fieldMappings || []).map(fm => fm.path);
          state.studio.sampleRows = [];

          showToast("Existing mapping JSON schema loaded.");
          render();
        } catch {
          showToast("Invalid JSON file schema structure.");
        }
      };
      reader.readAsText(file);
    });
  }

  const studioPasteBtn = document.getElementById("studio-paste-btn");
  if (studioPasteBtn) {
    studioPasteBtn.addEventListener("click", () => {
      const template = {
        partner: "VNPAY",
        workflowType: "UPC",
        fileType: "SETTLEMENT",
        sheetName: "Sheet1",
        startRow: 2,
        configVersion: "v_manual",
        fieldMappings: [
          { path: "id", column: 1, type: "STRING", required: true },
          { path: "amount", column: 2, type: "DECIMAL", required: true },
          { path: "transDate", column: 3, type: "DATE", required: true }
        ]
      };
      state.studio.config = template;
      state.studio.step = 2;
      state.studio.handoffConfirmed = false;
      state.studio.headers = ["id", "amount", "transDate"];
      state.studio.sampleRows = [];

      showToast("Starting manual setup with default template.");
      render();
    });
  }

  const tabVisual = document.getElementById("studio-tab-visual");
  const tabJson = document.getElementById("studio-tab-json");
  if (tabVisual && tabJson) {
    tabVisual.addEventListener("click", () => {
      tabVisual.classList.add("active");
      tabJson.classList.remove("active");
      document.getElementById("studio-tab-visual-content").style.display = "block";
      document.getElementById("studio-tab-json-content").style.display = "none";
    });
    tabJson.addEventListener("click", () => {
      tabJson.classList.add("active");
      tabVisual.classList.remove("active");
      document.getElementById("studio-tab-json-content").style.display = "flex";
      document.getElementById("studio-tab-visual-content").style.display = "none";
    });
  }

  const addFieldBtn = document.getElementById("studio-add-field-btn");
  if (addFieldBtn) {
    addFieldBtn.addEventListener("click", () => {
      if (!state.studio.config) return;
      state.studio.config.fieldMappings.push({
        path: `custom_field_${state.studio.config.fieldMappings.length + 1}`,
        column: null,
        type: "STRING",
        required: false
      });
      render();
    });
  }

  document.querySelectorAll(".studio-mapping-col-select").forEach(el => {
    el.addEventListener("change", () => {
      const idx = parseInt(el.dataset.idx, 10);
      const val = el.value ? parseInt(el.value, 10) : null;
      if (state.studio.config && state.studio.config.fieldMappings[idx]) {
        state.studio.config.fieldMappings[idx].column = val;
        if (val !== null) delete state.studio.config.fieldMappings[idx].constant;
      }
    });
  });

  document.querySelectorAll(".studio-mapping-const-input").forEach(el => {
    el.addEventListener("change", () => {
      const idx = parseInt(el.dataset.idx, 10);
      const val = el.value;
      if (state.studio.config && state.studio.config.fieldMappings[idx]) {
        state.studio.config.fieldMappings[idx].constant = val;
        if (val !== "") delete state.studio.config.fieldMappings[idx].column;
      }
    });
  });

  document.querySelectorAll(".studio-mapping-type-select").forEach(el => {
    el.addEventListener("change", () => {
      const idx = parseInt(el.dataset.idx, 10);
      const val = el.value;
      if (state.studio.config && state.studio.config.fieldMappings[idx]) {
        state.studio.config.fieldMappings[idx].type = val;
      }
    });
  });

  const acceptSuggestionBtn = document.getElementById("studio-accept-suggestion-btn");
  if (acceptSuggestionBtn) {
    acceptSuggestionBtn.addEventListener("click", () => {
      if (!state.studio.config) return;
      const hasCurrency = state.studio.config.fieldMappings.some(fm => fm.path === "currency");
      if (!hasCurrency) {
        state.studio.config.fieldMappings.push({
          path: "currency",
          constant: "VND",
          type: "CONSTANT"
        });
      }
      showToast("AI Currency suggestion accepted.");
      render();
    });
  }

  const backTo1Btn = document.getElementById("studio-back-to-1-btn");
  if (backTo1Btn) {
    backTo1Btn.addEventListener("click", () => {
      state.studio.step = 1;
      state.studio.handoffConfirmed = false;
      render();
    });
  }

  const to3Btn = document.getElementById("studio-to-3-btn");
  if (to3Btn) {
    to3Btn.addEventListener("click", () => {
      const jsonTextarea = document.getElementById("studio-json-textarea");
      if (jsonTextarea && document.getElementById("studio-tab-json-content").style.display === "flex") {
        try {
          state.studio.config = JSON.parse(jsonTextarea.value);
        } catch {
          showToast("Failed to parse schema JSON before proceeding.");
          return;
        }
      }

      if (!state.studio.config) return;

      const configCopy = JSON.parse(JSON.stringify(state.studio.config));
      if (configCopy.fieldMappings && !configCopy.fieldMappings.some(fm => fm.path === "currency")) {
        configCopy.fieldMappings.push({
          path: "currency",
          type: "CONSTANT",
          constant: "VND",
          required: true
        });
      }

      showToast("Running validation rules engine...");

      fetch("/api/v1/mapping/validate", {
        method: "POST",
        headers: withActorHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(configCopy)
      })
        .then(r => r.json())
        .then(data => {
          state.studio.validation = data;
          state.studio.step = 3;
          state.studio.handoffConfirmed = false;
          return fetch(`/api/v1/mapping/versions?partner=${encodeURIComponent(state.studio.config.partner)}`);
        })
        .then(r => r ? r.json() : null)
        .then(vData => {
          if (vData) state.studio.versions = vData.versions || [];
          render();
        })
        .catch(err => showToast("Validation fetch error: " + err.message));
    });
  }

  const backTo2Btn = document.getElementById("studio-back-to-2-btn");
  if (backTo2Btn) {
    backTo2Btn.addEventListener("click", () => {
      state.studio.step = 2;
      render();
    });
  }

  const runTestBtn = document.getElementById("studio-run-test-btn");
  if (runTestBtn) {
    runTestBtn.addEventListener("click", () => {
      if (!state.studio.config) return;
      const row = state.studio.sampleRows[0] || ["TXN001", "150000", "SUCCESS"];

      showToast("Testing layout transformation output...");

      fetch("/api/v1/mapping/test", {
        method: "POST",
        headers: withActorHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          mapping: state.studio.config,
          sampleRow: row
        })
      })
        .then(r => r.json())
        .then(data => {
          state.studio.testOutput = data.output;
          showToast("Transformation test completed.");
          render();
        })
        .catch(err => showToast("Transformation test failed: " + err.message));
    });
  }

  const openReviewCenterBtn = document.getElementById("studio-open-review-center-btn");
  if (openReviewCenterBtn) {
    openReviewCenterBtn.addEventListener("click", () => {
      if (state.studio.reviewItemId) {
        state.selectedReviewPacketId = state.studio.reviewItemId;
      }
      location.hash = "review-center";
    });
  }

  const confirmHandoffBtn = document.getElementById("studio-confirm-handoff-btn");
  if (confirmHandoffBtn) {
    confirmHandoffBtn.addEventListener("click", () => {
      const draftId = state.studio.draftMappingId;
      if (!draftId) {
        showToast("No draft mapping to hand off. Save the draft mapping first.");
        return;
      }
      confirmHandoffBtn.disabled = true;
      confirmHandoffBtn.innerHTML = `<span class="spinner small"></span> Handing off...`;
      fetch(`/api/v1/review-packets/from-mapping/${encodeURIComponent(draftId)}`, {
        method: "POST",
        headers: withActorHeaders({ "Content-Type": "application/json" }),
      })
        .then(r => r.json().then(body => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          confirmHandoffBtn.disabled = false;
          confirmHandoffBtn.innerHTML = "Confirm Ready";
          if (!ok) throw new Error(body.detail || "Handoff failed");
          showToast("Mapping submitted for review.");
          state.studio.handoffConfirmed = false;
          location.hash = "review-center";
        })
        .catch(err => {
          confirmHandoffBtn.disabled = false;
          confirmHandoffBtn.innerHTML = "Confirm Ready";
          showToast(err.message || "Handoff failed");
        });
    });
  }

  document.querySelectorAll(".studio-restore-version-btn").forEach(el => {
    el.addEventListener("click", () => {
      const vId = el.dataset.id;
      showToast("Restoring schema version...");

      fetch(`/api/v1/mapping/version/${encodeURIComponent(vId)}`)
        .then(r => r.json())
        .then(data => {
          state.studio.config = data;
          state.studio.step = 2;
          showToast(`Restored schema version: ${data.configVersion}`);
          render();
        })
        .catch(err => showToast("Restore failed: " + err.message));
    });
  });
}
