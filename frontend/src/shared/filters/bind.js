import { parseFlexibleDateInput, formatDisplayDate } from "../../core/date.js";
import { syncPartnerFilterOptions } from "./render.js";

let activePartnerFetchToken = 0;

export function fetchPartners({ state, render, container }) {
  const requestToken = ++activePartnerFetchToken;
  fetch("/api/v1/data/stats?date=" + state.date)
    .then(r => r.json())
    .then(data => {
      if (requestToken !== activePartnerFetchToken) return;
      const found = Object.keys(data.byPartner || {});
      const defaultPartners = ["MOMO", "VNPAY", "ZALOPAY", "ACMEPAY"];
      const partners = Array.from(new Set([...found, ...defaultPartners]));
      state.partnerOptions = partners;
      if (!partners.includes(state.partner) && partners.length) {
        state.partner = partners[0];
        render();
        return;
      }
      syncPartnerFilterOptions(state, container);
    })
    .catch(() => {
      if (requestToken !== activePartnerFetchToken) return;
      state.partnerOptions = ["MOMO", "VNPAY", "ZALOPAY", "ACMEPAY"];
      if (!state.partnerOptions.includes(state.partner)) {
        state.partner = state.partnerOptions[0];
      }
      syncPartnerFilterOptions(state, container);
    });
}

export function bindFilters({ state, render, showToast }) {
  document.querySelectorAll("#partner-filter").forEach(pf => {
    pf.addEventListener("change", () => {
      if (state.partner === pf.value) return;
      state.partner = pf.value;
      state.activeReconData = null;
      state.reconciliationRun = null;
      state.selectedEvidenceRowId = null;
      state.reconciliationPagination = { ...(state.reconciliationPagination || {}), offset: 0 };
      render();
    });
  });

  const applyMainDateInput = (input) => {
    if (!input) return;
    const parsed = parseFlexibleDateInput(input.value, state.date);
    if (!parsed) {
      showToast("Ngay khong hop le. Dung dd/mm/yyyy, dd/mm, 0707 hoac yyyy-mm-dd.");
      input.value = formatDisplayDate(state.date);
      return;
    }
    if (state.date === parsed) return;
    state.date = parsed;
    state.activeReconData = null;
    state.reconciliationRun = null;
    state.selectedEvidenceRowId = null;
    state.reconciliationPagination = { ...(state.reconciliationPagination || {}), offset: 0 };
    render();
  };

  document.querySelectorAll("#date-filter").forEach(input => {
    input.addEventListener("change", () => applyMainDateInput(input));
    input.addEventListener("blur", () => applyMainDateInput(input));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") applyMainDateInput(input);
    });
  });

  document.querySelectorAll("#date-picker").forEach(input => {
    input.addEventListener("change", () => {
      if (!input.value) return;
      if (state.date === input.value) return;
      state.date = input.value;
      state.activeReconData = null;
      state.reconciliationRun = null;
      state.selectedEvidenceRowId = null;
      state.reconciliationPagination = { ...(state.reconciliationPagination || {}), offset: 0 };
      render();
    });
  });

  document.querySelectorAll("[data-action='open-date-picker']").forEach(button => {
    button.addEventListener("click", () => {
      const picker = button.parentElement?.querySelector("#date-picker");
      if (!picker) return;
      if (typeof picker.showPicker === "function") {
        picker.showPicker();
        return;
      }
      picker.focus();
      picker.click();
    });
  });
}
