"""Seed a deterministic Copilot demo flow for the embedded dashboard UI.

Creates one partner/date scenario:
    partner = MOMO
    date    = 2026-06-05

Resulting UI state:
    - Data Intake shows a failed latest file
    - Copilot Panel returns `needs_review`
    - Review Queue contains one pending packet
    - Reviewer actions can approve, keep current, or reject
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.settings import settings


PARTNER = "MOMO"
RECON_DATE = datetime(2026, 6, 5, tzinfo=timezone.utc)
NOW = datetime.now(timezone.utc)


def _mapping_doc(config_id: str, *, status: str, version: str, reasoning: str) -> dict:
    return {
        "_id": config_id,
        "partner": PARTNER,
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 2,
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True, "sourceField": "txn_id"},
            {"path": "amount", "column": 2, "type": "DECIMAL", "required": True, "sourceField": "amount"},
            {"path": "transDate", "column": 3, "type": "DATE", "required": True, "sourceField": "trans_date"},
            {"path": "status", "column": 4, "type": "MAPPING", "mapping": {"SUCCESS": "SUCCESS", "FAILED": "FAILED"}},
            {"path": "currency", "constant": "VND", "type": "CONSTANT"},
        ],
        "configVersion": version,
        "status": status,
        "configHealth": {
            "stale": False,
            "status": status,
            "confidence": 0.93 if status == "PENDING_APPROVAL" else 1.0,
            "reasoning": reasoning,
            **({"approvedAt": NOW, "approvedBy": "demo-seed"} if status == "APPROVED" else {}),
        },
        "approvedAt": NOW if status == "APPROVED" else None,
        "approvedBy": "demo-seed" if status == "APPROVED" else None,
        "createdAt": NOW,
    }


async def seed():
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]

    file_id = str(uuid4())
    approved_config_id = str(uuid4())
    proposal_config_id = str(uuid4())
    action_id = str(uuid4())
    packet_id = str(uuid4())

    await db["review_packet"].delete_many({"partner": PARTNER})
    await db["copilot_action"].delete_many({"partner": PARTNER})
    await db["reconciliation_file"].delete_many({"partner": PARTNER, "reconciliationDate": RECON_DATE})
    await db["reconciliation_mapping_config"].delete_many({"partner": PARTNER})

    await db["reconciliation_file"].insert_one({
        "_id": file_id,
        "partner": PARTNER,
        "fileName": "settlement_MOMO_20260605_demo.xlsx",
        "fileHash": f"demo-{file_id}",
        "fileType": "SETTLEMENT",
        "reconciliationDate": RECON_DATE,
        "processingStatus": "FAILED",
        "totalRows": 20,
        "successRows": 0,
        "failedRows": 20,
        "configVersion": "MOMO_v01",
        "scopeType": "UNCONFIRMED",
        "scopeConfidence": 0.0,
        "scopeReason": [],
        "scopeSignals": {},
        "uploadedAt": NOW,
        "createdBy": "demo-seed",
        "createdAt": NOW,
    })

    await db["reconciliation_mapping_config"].insert_many([
        _mapping_doc(
            approved_config_id,
            status="APPROVED",
            version="MOMO_v01",
            reasoning="Approved baseline runtime for demo flow.",
        ),
        _mapping_doc(
            proposal_config_id,
            status="PENDING_APPROVAL",
            version="MOMO_v02",
            reasoning="Structure drift detected. A review item is ready.",
        ),
    ])

    await db["copilot_action"].insert_one({
        "_id": action_id,
        "type": "MAPPING_PROPOSAL",
        "status": "PENDING_APPROVAL",
        "partner": PARTNER,
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "targetConfigId": proposal_config_id,
        "payload": {
            "sheetName": "Sheet1",
            "startRow": 2,
            "confidence": 0.93,
            "reasoning": "Structure drift detected. A review item is ready.",
            "headers": ["txn_id", "amount", "trans_date", "status"],
            "sampleRows": [
                ["MOMO_DEMO_001", "125000", "2026-06-05 10:00:00", "SUCCESS"],
                ["MOMO_DEMO_002", "98000", "2026-06-05 10:05:00", "FAILED"],
            ],
        },
        "reason": "Generated from source file for review",
        "createdAt": NOW,
    })

    await db["review_packet"].insert_one({
        "_id": packet_id,
        "sourceType": "SCHEDULER_JOB",
        "partner": PARTNER,
        "fileName": "settlement_MOMO_20260605_demo.xlsx",
        "fileTypeDetected": "SETTLEMENT",
        "structureSignature": {
            "headers": ["txn_id", "amount", "trans_date", "status"],
            "headerRowIndex": 1,
            "firstDataRowIndex": 2,
        },
        "activeRuntimeConfigId": approved_config_id,
        "proposalConfigId": proposal_config_id,
        "targetActionId": action_id,
        "sourceFileId": file_id,
        "scopeType": "UNCONFIRMED",
        "scopeConfidence": 0.82,
        "scopeReason": ["Demo packet seeded for dashboard review flow."],
        "scopeSignals": {"seeded": True},
        "recommendedAction": {
            "actionType": "APPROVE_AND_ACTIVATE_NEXT_RUNTIME",
            "reason": "File structure changed; a review item is ready.",
            "confidence": 0.93,
        },
        "parseStrategy": {
            "sheetName": "Sheet1",
            "startRow": 2,
            "fieldMappingCount": 5,
            "strategy": "AI inferred spreadsheet draft mapping",
        },
        "validationGates": [
            {
                "gateKey": "structure_signature",
                "label": "Structure signature generated",
                "status": "pass",
                "reason": "File headers and shape were fingerprinted successfully.",
            },
            {
                "gateKey": "required_fields",
                "label": "Required fields proposed",
                "status": "pass",
                "reason": "AI generated canonical fields for settlement parsing.",
            },
            {
                "gateKey": "runtime_validation",
                "label": "Runtime validation",
                "status": "pass",
                "reason": "Validated successfully on 20/20 sampled rows.",
                "details": {"sampledRows": 20, "successRows": 20, "failedRows": 0},
            },
        ],
        "samplePreview": [
            {"rowIndex": 2, "values": ["MOMO_DEMO_001", "125000", "2026-06-05 10:00:00", "SUCCESS"]},
            {"rowIndex": 3, "values": ["MOMO_DEMO_002", "98000", "2026-06-05 10:05:00", "FAILED"]},
        ],
        "riskSummary": {
            "severity": "medium",
            "summary": "File structure changed; a review item is ready.",
        },
        "runtimeDecisionHint": "KEEP_CURRENT_RUNTIME_UNTIL_APPROVED",
        "status": "PENDING",
        "createdAt": NOW,
    })

    print("Seeded Copilot demo flow:")
    print(f"  partner: {PARTNER}")
    print("  date:    2026-06-05")
    print("  UI:      http://localhost:5173/")
    print("  route:   #data-intake")
    print()
    print("Expected flow:")
    print("  1. Open Data Intake")
    print("  2. Keep partner = MOMO, date = 05/06/2026")
    print("  3. Copilot Panel should show a needs-review recommendation")
    print("  4. Click Review now to open Review Queue")
    print("  5. Test Approve activate / Keep current / Reject")

    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
