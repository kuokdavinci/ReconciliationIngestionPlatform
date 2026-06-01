(function () {
  window.AdapterMockData = {
    partners: ["MOMO", "VNPAY", "ZALOPAY"],
    services: [
      { name: "MongoDB", status: "healthy", latency: "12 ms", detail: "reconciliation / indexes ready" },
      { name: "SFTP", status: "healthy", latency: "28 ms", detail: "localhost:2222 / upload" },
      { name: "FastAPI", status: "healthy", latency: "41 ms", detail: "0.1.0 / insights API" },
      { name: "Scheduler", status: "warning", latency: "5m grace", detail: "daily_partner_fetch waiting" },
      { name: "AI Provider", status: "healthy", latency: "30s timeout", detail: "openai / gpt-4o-mini" }
    ],
    overview: {
      MOMO: { files: 18, rows: 279420, success: 276511, failed: 2909, mismatchRate: 3.8, alerts: 2, volume: "72.4B VND" },
      VNPAY: { files: 11, rows: 154880, success: 153912, failed: 968, mismatchRate: 1.6, alerts: 0, volume: "41.8B VND" },
      ZALOPAY: { files: 9, rows: 98920, success: 97318, failed: 1602, mismatchRate: 5.7, alerts: 3, volume: "26.1B VND" }
    },
    fetchConfigs: [
      { partner: "MOMO", method: "SFTP", enabled: true, schedule: "0 0 * * *", source: "sftp.momo.vn:/outgoing/*.xlsx", archive: "./archive/MOMO", cleanup: true, lastFetch: "2024-07-08 00:03" },
      { partner: "VNPAY", method: "API", enabled: true, schedule: "10 0 * * *", source: "https://api.vnpay.vn/reconciliation", archive: "./archive/VNPAY", cleanup: true, lastFetch: "2024-07-08 00:11" },
      { partner: "ZALOPAY", method: "FILEDROP", enabled: false, schedule: "20 0 * * *", source: "/data/partner-drops/ZALOPAY/*.xlsx", archive: "./archive/ZALOPAY", cleanup: false, lastFetch: "2024-07-07 00:20" }
    ],
    schedulerJobs: [
      { id: "daily_partner_fetch", name: "Daily Partner Data Fetch", nextRun: "2024-07-09 00:00", trigger: "cron[0 0 * * *]", status: "scheduled" },
      { id: "momo_retry_window", name: "MOMO Retry Window", nextRun: "2024-07-08 01:00", trigger: "cron[0 1 * * *]", status: "paused" }
    ],
    runHistory: [
      { time: "00:03", partner: "MOMO", event: "FETCH_SUCCESS", status: "success", detail: "m4becomvsp_07072024_combine.xlsx / 14.8 MB" },
      { time: "00:04", partner: "MOMO", event: "INGESTION_TRIGGERED", status: "success", detail: "276,511 rows accepted" },
      { time: "00:11", partner: "VNPAY", event: "FETCH_SUCCESS", status: "success", detail: "api_data_20240707.xlsx / 8.2 MB" },
      { time: "00:20", partner: "ZALOPAY", event: "FETCH_FAILED", status: "failed", detail: "FileDrop directory has no ready files" }
    ],
    mappingConfigs: [
      { partner: "MOMO", workflow: "UPC", fileType: "SETTLEMENT", sheet: "data", startRow: 8, version: "v_template", updated: "2024-07-06 18:21" },
      { partner: "VNPAY", workflow: "UPC", fileType: "SETTLEMENT", sheet: "Data", startRow: 3, version: "v2", updated: "2024-07-05 11:12" },
      { partner: "ZALOPAY", workflow: "UPC", fileType: "RECONCILIATION", sheet: "Sheet1", startRow: 5, version: "v1", updated: "2024-07-04 09:45" }
    ],
    fieldMappings: [
      { path: "id", column: "2", type: "STRING", required: true, sample: "61838642196" },
      { path: "trace", column: "11", type: "STRING", required: false, sample: "2407055711887385978413624" },
      { path: "amount", column: "5", type: "DECIMAL", required: false, sample: "259200" },
      { path: "currency", column: "constant", type: "CONSTANT", required: false, sample: "VND" },
      { path: "status", column: "18", type: "MAPPING", required: false, sample: "Thanh cong -> SUCCESS" },
      { path: "transDate", column: "8", type: "DATE", required: false, sample: "2024-07-05" },
      { path: "extra.provider", column: "constant", type: "CONSTANT", required: false, sample: "MOMO" }
    ],
    ingestionFiles: [
      { partner: "MOMO", file: "m4becomvsp_07072024_combine.xlsx", status: "COMPLETED", total: 279420, success: 276511, failed: 2909, duration: "3m 42s", hash: "9ab2...f84c" },
      { partner: "VNPAY", file: "api_data_20240707.xlsx", status: "COMPLETED", total: 154880, success: 153912, failed: 968, duration: "2m 08s", hash: "80c1...2b01" },
      { partner: "ZALOPAY", file: "zalopay_20240707.xlsx", status: "FAILED", total: 98920, success: 97318, failed: 1602, duration: "1m 53s", hash: "64df...7a91" }
    ],
    rowErrors: [
      { row: 142, field: "amount", reason: "invalid decimal value", trace: "2407055711887385978401" },
      { row: 318, field: "status", reason: "invalid status value", trace: "2407055711887385978402" },
      { row: 519, field: "transDate", reason: "unsupported date format", trace: "2407055711887385978403" },
      { row: 1220, field: "duplicate", reason: "file already processed", trace: "2407055711887385978404" }
    ],
    reconciliation: [
      { partner: "MOMO", key: "2407055711887385978413624", status: "MATCHED", partnerAmount: 259200, internalAmount: 259200, partnerStatus: "SUCCESS", internalStatus: "SUCCESS" },
      { partner: "MOMO", key: "2407055711887385978413625", status: "AMOUNT_MISMATCH", partnerAmount: 259200, internalAmount: 100000, partnerStatus: "SUCCESS", internalStatus: "SUCCESS" },
      { partner: "MOMO", key: "2407055711887385978413626", status: "STATUS_MISMATCH", partnerAmount: 88000, internalAmount: 88000, partnerStatus: "FAILED", internalStatus: "SUCCESS" },
      { partner: "MOMO", key: "internal_only_txn_999", status: "MISSING_PARTNER", partnerAmount: null, internalAmount: 15000, partnerStatus: "-", internalStatus: "SUCCESS" },
      { partner: "VNPAY", key: "vnp_240707_0091", status: "MATCHED", partnerAmount: 340000, internalAmount: 340000, partnerStatus: "SUCCESS", internalStatus: "SUCCESS" },
      { partner: "ZALOPAY", key: "zlp_240707_0007", status: "MISSING_INTERNAL", partnerAmount: 78000, internalAmount: null, partnerStatus: "SUCCESS", internalStatus: "-" }
    ],
    insights: [
      { partner: "MOMO", focus: "operational", severity: "high", title: "Missing partner/internal records increased", affected: 42, recommendation: "Check scheduler run window and source file completeness." },
      { partner: "MOMO", focus: "inconsistency", severity: "medium", title: "Amount mismatch cluster in low value range", affected: 18, recommendation: "Compare fee and rounding rules for UPC settlement." },
      { partner: "VNPAY", focus: "partner", severity: "low", title: "Partner stable under alert threshold", affected: 3, recommendation: "Continue normal monitoring." },
      { partner: "ZALOPAY", focus: "operational", severity: "critical", title: "FileDrop source unavailable", affected: 71, recommendation: "Verify mounted drop directory and retry daily fetch job." }
    ],
    reports: [
      { partner: "MOMO", total: 279420, matched: 268802, mismatchRate: 3.8, totalMismatch: "2.1B VND", alerts: 2 },
      { partner: "VNPAY", total: 154880, matched: 152402, mismatchRate: 1.6, totalMismatch: "420M VND", alerts: 0 },
      { partner: "ZALOPAY", total: 98920, matched: 93282, mismatchRate: 5.7, totalMismatch: "880M VND", alerts: 3 }
    ],
    collections: {
      reconciliation_file: [
        { _id: "rf_001", partner: "MOMO", processingStatus: "COMPLETED", totalRows: 279420, fileHash: "9ab2...f84c" },
        { _id: "rf_002", partner: "VNPAY", processingStatus: "COMPLETED", totalRows: 154880, fileHash: "80c1...2b01" },
        { _id: "rf_003", partner: "ZALOPAY", processingStatus: "FAILED", totalRows: 98920, fileHash: "64df...7a91" }
      ],
      data_container: [
        { _id: "dc_001", identify: "MOMO", trace: "2407055711887385978413624", operationStatus: "SUCCESS", amount: "259200" },
        { _id: "dc_002", identify: "VNPAY", trace: "vnp_240707_0091", operationStatus: "SUCCESS", amount: "340000" },
        { _id: "dc_003", identify: "ZALOPAY", trace: "zlp_240707_0007", operationStatus: "FAILED", amount: "78000" }
      ],
      reconciliation_result: [
        { _id: "2407055711887385978413624", partnerTxnId: "2407055711887385978413624", reconciliationStatus: "MATCHED", partnerAmount: "259200" },
        { _id: "2407055711887385978413625", partnerTxnId: "2407055711887385978413625", reconciliationStatus: "AMOUNT_MISMATCH", partnerAmount: "259200" }
      ],
      internal_transaction: [
        { _id: "internal_matched_01", partner: "MOMO", partnerTxnId: "2407055711887385978413624", amount: "259200", status: "SUCCESS" },
        { _id: "internal_missing_partner_01", partner: "MOMO", partnerTxnId: "internal_only_txn_999", amount: "15000", status: "SUCCESS" }
      ]
    },
    settings: [
      { key: "APP_MONGODB_URL", value: "mongodb://admin:********@localhost:27017/reconciliation?authSource=admin", group: "Application" },
      { key: "APP_DB_NAME", value: "reconciliation", group: "Application" },
      { key: "APP_LOG_FORMAT", value: "json", group: "Application" },
      { key: "AI_PROVIDER", value: "openai", group: "AI" },
      { key: "AI_MODEL", value: "gpt-4o-mini", group: "AI" },
      { key: "AI_API_KEY", value: "********", group: "AI" },
      { key: "SFTP_HOST", value: "localhost", group: "Fetch" },
      { key: "SFTP_PASS", value: "********", group: "Fetch" }
    ]
  };
})();
