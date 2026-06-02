// Initialize MongoDB collections and indexes for Reconciliation Ingestion Platform

db = db.getSiblingDB("reconciliation");

// Create collections (explicit creation for clarity)
db.createCollection("reconciliation_file");
db.createCollection("reconciliation_mapping_config");
db.createCollection("data_container");

// reconciliation_file indexes
db.reconciliation_file.createIndex(
  { fileHash: 1 },
  { unique: true, name: "idx_file_hash_unique" }
);
db.reconciliation_file.createIndex(
  { partner: 1, reconciliationDate: 1 },
  { name: "idx_partner_date" }
);

// reconciliation_mapping_config indexes
db.reconciliation_mapping_config.createIndex(
  { partner: 1, workflowType: 1, fileType: 1 },
  { name: "idx_partner_workflow_type" }
);

// data_container indexes
db.data_container.createIndex(
  { "partnerData.trace": 1 },
  { name: "idx_trace" }
);
db.data_container.createIndex(
  { identify: 1, reconciliationDate: 1 },
  { name: "idx_identify_date" }
);
db.data_container.createIndex(
  { operationStatus: 1 },
  { name: "idx_operation_status" }
);
db.data_container.createIndex(
  { "partnerData.status": 1 },
  { name: "idx_partner_status" }
);
db.data_container.createIndex(
  { sourceFileId: 1 },
  { name: "idx_source_file" }
);

// Seeds for default partner configurations
db.reconciliation_mapping_config.deleteMany({ partner: "MOMO" });
db.reconciliation_mapping_config.insertOne({
  _id: "77777777-7777-7777-7777-777777777777",
  partner: "MOMO",
  workflowType: "UPC",
  fileType: "SETTLEMENT",
  sheetName: "data",
  startRow: 8,
  fieldMappings: [
    { path: "id", column: 2, type: "STRING", required: true },
    { path: "trace", column: 11, type: "STRING" },
    { path: "amount", column: 5, type: "DECIMAL" },
    { path: "currency", constant: "VND", type: "CONSTANT" },
    { path: "status", column: 18, type: "MAPPING", mapping: { "Thành công": "SUCCESS", "others": "FAILED" } },
    { path: "transDate", column: 8, type: "DATE" },
    { path: "extra.service", constant: "PAYMENT", type: "CONSTANT" },
    { path: "extra.portal", constant: "PaymentGateway", type: "CONSTANT" },
    { path: "extra.provider", constant: "MOMO", type: "CONSTANT" }
  ],
  configVersion: "v_template",
  createdAt: new Date()
});

db.reconciliation_mapping_config.deleteMany({ partner: "VNPAY" });
db.reconciliation_mapping_config.insertOne({
  _id: "88888888-8888-8888-8888-888888888888",
  partner: "VNPAY",
  workflowType: "UPC",
  fileType: "SETTLEMENT",
  sheetName: "Sheet1",
  startRow: 2,
  fieldMappings: [
    { path: "id", column: 1, type: "STRING", required: true },
    { path: "trace", column: 2, type: "STRING" },
    { path: "amount", column: 3, type: "DECIMAL" },
    { path: "currency", constant: "VND", type: "CONSTANT" },
    { path: "status", column: 4, type: "MAPPING", mapping: { "SUCCESS": "SUCCESS", "FAILED": "FAILED", "PENDING": "PENDING" } },
    { path: "transDate", column: 5, type: "DATE" },
    { path: "extra.service", constant: "PAYMENT", type: "CONSTANT" },
    { path: "extra.portal", constant: "VNPayPortal", type: "CONSTANT" },
    { path: "extra.provider", constant: "VNPAY", type: "CONSTANT" }
  ],
  configVersion: "v1",
  createdAt: new Date()
});

print("MongoDB initialized successfully — collections, indexes, and default MOMO/VNPAY configs created.");
