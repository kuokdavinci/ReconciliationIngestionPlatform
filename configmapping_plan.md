# Feature: Partner Mapping Studio v2

## Objective

Transform the current "Import Ingestion Mapping Schema" screen into a guided onboarding experience for partner data ingestion.

The goal is to reduce mapping errors, improve user confidence, and make schema onboarding easier for both developers and operations teams.

Target users:

* Backend Engineers
* Data Engineers
* Operations Team
* Business Analysts

The UI should support:

1. Upload existing mapping schema
2. Paste raw JSON schema
3. Generate schema using AI from sample files
4. Validate mappings
5. Preview transformed output
6. Test mapping before publishing
7. Version management

---

# Design Principles

* Minimize user mistakes
* Visual over JSON whenever possible
* AI suggestions must always be reviewable
* Show confidence and validation status
* Avoid hidden system behavior
* Keep workflow simple and linear

---

# New Workflow

## Step 1 — Choose Source

Replace current 3 independent panels with a unified onboarding flow.

Card options:

### Option A

Upload Sample Partner File

Supported:

* Excel (.xlsx)
* CSV

Purpose:
Generate mapping automatically.

---

### Option B

Upload Existing Mapping

Supported:

* JSON

Purpose:
Reuse previously created schema.

---

### Option C

Paste Mapping JSON

Purpose:
Manual configuration.

---

# Step 2 — Data Preview

After upload, show detected file structure.

Example:

Rows Preview

| Row | Transaction ID | Amount | Status  |
| --- | -------------- | ------ | ------- |
| 1   | TXN001         | 100000 | SUCCESS |
| 2   | TXN002         | 50000  | FAILED  |

Requirements:

* First 10 rows preview
* Highlight empty columns
* Highlight duplicate headers
* Detect sheet names for Excel files

---

# Step 3 — AI Mapping Review

After AI generates schema:

Display mapping table.

| Source Column | Canonical Field | Confidence |
| ------------- | --------------- | ---------- |
| Mã GD         | transaction_id  | 99%        |
| Số Tiền       | amount          | 98%        |
| Trạng Thái    | status          | 97%        |
| Loại Tiền     | currency        | 62%        |

Confidence Rules:

> = 90%
> Status = High Confidence

80% - 89%
Status = Medium Confidence

< 80%
Status = Needs Review

Low-confidence fields must show warning badge.

Example:

⚠ Review Required

---

# Step 4 — Mapping Visualization

Provide 2 tabs.

## Tab 1 — Visual Mapping

| Canonical Field | Mapping Source  |
| --------------- | --------------- |
| transaction_id  | Column A        |
| amount          | Column C        |
| currency        | Constant(VND)   |
| partner_id      | Constant(VNPAY) |

---

## Tab 2 — Raw JSON

Show generated schema JSON.

Include:

* Syntax highlighting
* JSON validation
* Copy button

---

# Step 5 — Validation Engine

Perform validation immediately.

Checks:

### Required Fields

Required:

* transaction_id
* amount
* transaction_time

Missing fields:

Show error.

---

### Type Validation

Example:

amount -> DECIMAL

If source column contains text:

Show warning.

---

### Duplicate Mapping

One source column mapped to multiple canonical fields.

Show warning.

---

### Empty Mapping

Canonical field has no source.

Show warning.

---

# Validation Summary Panel

Example:

Validation Result

✓ JSON Syntax Valid

✓ Required Fields Present

✓ Type Validation Passed

⚠ Currency Inferred Automatically

0 Errors
1 Warning

---

# Step 6 — Test Mapping

Add button:

[Test Mapping]

When clicked:

Transform first sample row using current schema.

Show result:

{
"transaction_id": "TXN001",
"amount": 100000,
"currency": "VND",
"status": "SUCCESS"
}

Purpose:

Allow users to verify actual output before publishing.

---

# Step 7 — Mapping Quality Score

Introduce quality scoring.

Formula:

Quality Score =
Field Coverage +
Validation Score +
Confidence Score

Display:

92 / 100

Breakdown:

✓ Required Fields

✓ Type Match

✓ Mapping Consistency

⚠ Inferred Constants

Color Rules:

90-100 = Excellent

75-89 = Good

Below 75 = Review Needed

---

# Step 8 — AI Suggestions

Allow AI to suggest:

* Missing fields
* Constant values
* Data types
* Date formats

Example:

Suggested:

currency = "VND"

Reason:
All transactions appear to be Vietnamese Dong.

User must explicitly accept suggestion.

Never auto-publish inferred mappings.

---

# Step 9 — Schema Versioning

Support version history.

Partner:

VNPAY

Schema Versions:

* v1
* v2
* v3

Current:
v3

Features:

* View version history
* Compare versions
* Restore previous version

---

# Step 10 — Publish Flow

Replace button:

"Apply Ingestion Config Schema"

with:

"Publish Schema"

Before publish:

Show summary dialog.

Partner:
VNPAY

Version:
v3

Quality Score:
92/100

Validation:
Passed

Ready to Publish

[Cancel]
[Publish]

---

# Technical Requirements

## Backend

Create APIs:

POST /mapping/ai-generate

POST /mapping/validate

POST /mapping/test

POST /mapping/publish

GET /mapping/versions

GET /mapping/version/{id}

---

## AI Requirements

AI Output:

{
"mapping": [],
"confidence_scores": [],
"warnings": [],
"suggested_constants": []
}

Never return mapping only.

Confidence scores are mandatory.

---

## Success Criteria

A user should be able to:

1. Upload partner file
2. Review AI mapping
3. Validate schema
4. Test transformed output
5. Publish safely

without manually editing JSON in most cases.
