import type { ReviewPacket } from "@/types/review-center";

export const mockReviewPackets: ReviewPacket[] = [
  {
    _id: "packet_1",
    partner: "MOMO",
    fileName: "MOMO_SETTLEMENT_20260610.xlsx",
    fileTypeDetected: "SETTLEMENT",
    status: "PENDING",
    draftMappingId: "mapping_1",
    recommendedAction: {
      actionType: "APPROVE_REQUIRED_BEFORE_RUNTIME",
      reason: "File has a draft mapping ready. Review and approve to activate.",
    },
    parseStrategy: {
      sheetName: "Sheet1",
      startRow: 2,
      fieldMappingCount: 8,
    },
    mappingConstraints: [
      { label: "Partner", value: "MOMO" },
      { label: "Currency", value: "VND" },
      { label: "Method", value: "Scheduler" },
      { label: "Sheet", value: "Sheet1" },
      { label: "Start row", value: "2" },
    ],
    validationGates: [
      { gateKey: "column_count", status: "pass", label: "Column Count", message: "Expected 12, found 12" },
      { gateKey: "header_match", status: "pass", label: "Header Match", message: "All required headers present" },
      {
        gateKey: "runtime_validation",
        status: "warn",
        label: "Runtime Validation",
        message: "3 rows have missing fields",
        details: {
          sampledRows: 20,
          successRows: 17,
          failedRows: 3,
          traceSamples: [
            {
              row: 2,
              normalizedData: {
                transactionId: "MOMO_1001",
                amount: "105000",
                status: "SUCCESS",
                paidAt: "2026-06-10 09:15",
                currency: "VND",
              },
              fieldTraces: [
                { path: "transactionId", sourceField: "msTransId", status: "ok" },
                { path: "amount", sourceField: "msTotalAmount", status: "ok" },
                { path: "status", sourceField: "msTrangThaiGd", status: "ok" },
                { path: "paidAt", sourceField: "msNgayHoanThanh", status: "ok" },
                { path: "currency", sourceField: null, status: "ok" },
              ],
            },
            {
              row: 3,
              normalizedData: {
                transactionId: "MOMO_1002",
                amount: "110000",
                status: "SUCCESS",
                paidAt: "",
                currency: "VND",
              },
              fieldTraces: [
                { path: "transactionId", sourceField: "msTransId", status: "ok" },
                { path: "amount", sourceField: "msTotalAmount", status: "ok" },
                { path: "status", sourceField: "msTrangThaiGd", status: "ok" },
                { path: "paidAt", sourceField: "msNgayHoanThanh", status: "error", errorCode: "missing_date", errorMessage: "Missing paidAt value" },
                { path: "currency", sourceField: null, status: "ok" },
              ],
            },
          ],
          failedExamples: [{ row: 3 }, { row: 8 }, { row: 15 }],
        },
      },
    ],
    riskSummary: { severity: "medium", summary: "Runtime validation passed with a small number of row-level warnings." },
    createdAt: "2026-06-10T10:00:00Z",
    scopeRecommendation: {
      scopeType: "FULL_SNAPSHOT",
      confidence: 0.91,
      reason: [
        "File name matches the daily settlement pattern.",
        "Record volume is aligned with the existing day snapshot.",
      ],
    },
    runtimeValidation: {
      validationStatus: "WARNING",
      canSave: true,
      summary: {
        rowsChecked: 20,
        mappedFields: 8,
        totalFields: 9,
        requiredFieldsPassed: 6,
        requiredFieldsTotal: 6,
        validRows: 17,
        errorRows: 3,
        validRowsPercent: 85,
      },
      fieldResults: [
        { canonicalField: "transactionId", sourceColumn: "msTransId", status: "OK", issue: null },
        { canonicalField: "amount", sourceColumn: "msTotalAmount", status: "OK", issue: null },
        { canonicalField: "status", sourceColumn: "msTrangThaiGd", status: "OK", issue: null },
        { canonicalField: "paidAt", sourceColumn: "msNgayHoanThanh", status: "WARNING", issue: "3 rows missing paidAt value" },
        { canonicalField: "currency", sourceColumn: null, status: "OK", issue: null },
      ],
      previewRows: [
        { id: "2", values: { transactionId: "MOMO_1001", amount: "105000", status: "SUCCESS", paidAt: "2026-06-10 09:15", currency: "VND" } },
        { id: "3", values: { transactionId: "MOMO_1002", amount: "110000", status: "SUCCESS", paidAt: "", currency: "VND" }, invalidFields: ["paidAt"] },
      ],
      topIssues: [
        { type: "MISSING_PAID_AT", message: "Missing paidAt values in sampled rows", affectedRows: 3, severity: "WARNING" },
      ],
    },
  },
  {
    _id: "packet_2",
    partner: "MOMO",
    fileName: "MOMO_RECON_20260609.xlsx",
    fileTypeDetected: "SETTLEMENT",
    status: "PENDING",
    recommendedAction: {
      actionType: "APPROVE_REQUIRED_BEFORE_RUNTIME",
      reason: "New file format detected. Requires mapping verification.",
    },
    parseStrategy: {
      sheetName: "Transactions",
      startRow: 1,
    },
    mappingConstraints: [
      { label: "Partner", value: "MOMO" },
      { label: "Currency", value: "VND" },
      { label: "Method", value: "Manual upload" },
      { label: "Sheet", value: "Transactions" },
      { label: "Start row", value: "1" },
    ],
    validationGates: [
      { gateKey: "column_count", status: "pass", label: "Column Count", message: "Expected 10, found 10" },
      { gateKey: "header_match", status: "fail", label: "Header Match", message: "Missing column: internal_ref" },
      { gateKey: "runtime_validation", status: "pass", label: "Runtime Validation", message: "Parser accepts format" },
    ],
    riskSummary: { severity: "high", summary: "Missing required headers block this mapping from promotion." },
    createdAt: "2026-06-09T08:30:00Z",
    scopeRecommendation: {
      scopeType: "FULL_SNAPSHOT",
      confidence: 0.73,
      reason: [
        "The file name indicates a full-day export.",
        "Header mismatch must be fixed before activation.",
      ],
    },
    runtimeValidation: {
      validationStatus: "FAILED",
      canSave: false,
      summary: {
        rowsChecked: 20,
        mappedFields: 5,
        totalFields: 7,
        requiredFieldsPassed: 4,
        requiredFieldsTotal: 6,
        validRows: 9,
        errorRows: 11,
        validRowsPercent: 45,
      },
      fieldResults: [
        { canonicalField: "transactionId", sourceColumn: "id", status: "OK", issue: null },
        { canonicalField: "amount", sourceColumn: "amount", status: "OK", issue: null },
        { canonicalField: "status", sourceColumn: null, status: "MISSING", issue: "Required field" },
        { canonicalField: "paidAt", sourceColumn: "paid_time", status: "INVALID", issue: "11 rows invalid datetime format" },
      ],
      previewRows: [
        { id: "1", values: { transactionId: "MOMO_FAIL_1", amount: "250000", status: null, paidAt: "10/06/2026", currency: "VND" }, invalidFields: ["status", "paidAt"] },
      ],
      topIssues: [
        { type: "MISSING_REQUIRED_FIELD", message: "Missing required field: status", affectedRows: null, severity: "ERROR" },
        { type: "INVALID_DATE", message: "Invalid paidAt format", affectedRows: 11, severity: "ERROR" },
      ],
    },
  },
  {
    _id: "packet_3",
    partner: "MOMO",
    fileName: "ZALOPAY_DAILY_20260608.xlsx",
    fileTypeDetected: "SETTLEMENT",
    status: "PENDING",
    recommendedAction: {
      actionType: "APPROVE_REQUIRED_BEFORE_RUNTIME",
      reason: "Pending mapping review for new partner format.",
    },
    parseStrategy: {
      sheetName: "Sheet1",
      startRow: 3,
    },
    validationGates: [
      { gateKey: "column_count", status: "pass", label: "Column Count", message: "Expected 8, found 8" },
      { gateKey: "header_match", status: "pass", label: "Header Match", message: "All headers matched" },
    ],
    riskSummary: { severity: "low", summary: "Draft mapping looks stable and can likely be promoted after a quick review." },
    createdAt: "2026-06-08T14:00:00Z",
    scopeRecommendation: {
      scopeType: "INCREMENTAL_APPEND",
      confidence: 0.82,
      reason: [
        "File naming indicates a partner daily incremental batch.",
      ],
    },
    runtimeValidation: {
      validationStatus: "PASSED",
      canSave: true,
      summary: {
        rowsChecked: 20,
        mappedFields: 6,
        totalFields: 6,
        requiredFieldsPassed: 6,
        requiredFieldsTotal: 6,
        validRows: 20,
        errorRows: 0,
        validRowsPercent: 100,
      },
      fieldResults: [
        { canonicalField: "transactionId", sourceColumn: "id", status: "OK", issue: null },
        { canonicalField: "amount", sourceColumn: "amount", status: "OK", issue: null },
        { canonicalField: "status", sourceColumn: "status", status: "OK", issue: null },
      ],
      previewRows: [
        { id: "1", values: { transactionId: "ZALO_1", amount: "98000", status: "SUCCESS", paidAt: "2026-06-08 11:12", currency: "VND" } },
      ],
      topIssues: [],
    },
  },
];

export function summarizeReviewPacket(packet: ReviewPacket) {
  const gateSummary = (packet.validationGates || []).reduce<Record<string, number>>((acc, gate) => {
    const status = String(gate.status || "").toLowerCase();
    acc[status] = (acc[status] || 0) + 1;
    return acc;
  }, {});
  const hasFailedGates = !!((gateSummary.fail || 0) + (gateSummary.failed || 0));
  const runtimeGate = (packet.validationGates || []).find((gate) => gate.gateKey === "runtime_validation");
  const runtimeValidated = String(runtimeGate?.status || "").toLowerCase() === "pass";
  const mappingReady = !!packet.draftMappingId;
  return {
    gateSummary,
    hasFailedGates,
    runtimeGate,
    runtimeValidated,
    mappingReady,
    readyToActivate: mappingReady && runtimeValidated && !hasFailedGates,
  };
}
