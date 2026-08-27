import asyncio
import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy import delete

from src.config.settings import settings
from src.core.enums import TransactionStatus
from src.core.enums import FileType
from src.core.types import FieldMapping, FieldMappingType
from src.domain.internal_transaction.models import InternalTransaction
from src.infrastructure.postgres.internal_transaction_repository import InternalTransactionRepository
from src.domain.fetch_config.models import FetchConfig, FetchMethod, FileDropConfig
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.domain.mapping.models import MappingConfig, MappingConfigStatus
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.postgres.reconciliation_result_repository import ReconciliationResultRepository

async def seed_acmepay_case():
    print("Connecting to MongoDB...")
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]

    # Repositories
    fetch_repo = FetchConfigRepository(db)
    mapping_repo = MappingConfigRepository(db)

    print("Cleaning up old ACMEPAY data...")
    internal_repo = InternalTransactionRepository()
    from src.infrastructure.persistence.postgres_schema import InternalTransactionTable
    async with internal_repo.engine.begin() as conn:
        await conn.execute(delete(InternalTransactionTable).where(InternalTransactionTable.partner == "ACMEPAY"))
    await db["reconciliation_file"].delete_many({"partner": "ACMEPAY"})
    await ReconciliationResultRepository().delete_by_partner_and_date("ACMEPAY", datetime.now(timezone.utc).date().isoformat())
    await db["reconciliation_mapping_config"].delete_many({"partner": "ACMEPAY"})
    await db["review_packet"].delete_many({"partner": "ACMEPAY"})
    await fetch_repo._collection.delete_many({"partner": "ACMEPAY"})

    # --- Seed 20 Internal Transactions ---
    print("Seeding 20 internal transactions for ACMEPAY...")
    recon_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    postgres_recon_date = recon_date.replace(tzinfo=None)
    
    internal_data = [
        ("INT_ACMEPAY_001", "ACMEPAY_TXN_001", "50000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_002", "ACMEPAY_TXN_002", "100000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_003", "ACMEPAY_TXN_003", "150000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_004", "ACMEPAY_TXN_004", "200000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_005", "ACMEPAY_TXN_005", "300000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_006", "ACMEPAY_TXN_006", "500000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_007", "ACMEPAY_TXN_007", "1000000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_008", "ACMEPAY_TXN_008", "10000", TransactionStatus.FAILED),
        ("INT_ACMEPAY_009", "ACMEPAY_TXN_009", "20000", TransactionStatus.FAILED),
        ("INT_ACMEPAY_010", "ACMEPAY_TXN_010", "75000", TransactionStatus.REVERSED),
        ("INT_ACMEPAY_011", "ACMEPAY_TXN_011", "120000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_012", "ACMEPAY_TXN_012", "250000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_013", "ACMEPAY_TXN_013", "80000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_014", "ACMEPAY_TXN_014", "90000", TransactionStatus.FAILED),
        ("INT_ACMEPAY_015", "ACMEPAY_TXN_015", "110000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_016", "ACMEPAY_TXN_016", "45000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_017", "ACMEPAY_TXN_017", "65000", TransactionStatus.SUCCESS),
        ("INT_ACMEPAY_018", "ACMEPAY_TXN_018", "135000", TransactionStatus.SUCCESS),
    ]

    internal_docs = [
        InternalTransaction(
            id=tx_id,
            partner="ACMEPAY",
            partnerTxnId=p_txn_id,
            amount=Decimal(amount),
            status=status,
            transactionTime=postgres_recon_date,
        )
        for tx_id, p_txn_id, amount, status in internal_data
    ]
    await internal_repo.insert_many(internal_docs)
    print(f"Successfully seeded {len(internal_docs)} internal records.")

    # --- Seed Fetch Config (FileDrop) ---
    print("Seeding Fetch Config for ACMEPAY...")
    fetch_config = FetchConfig(
        partner="ACMEPAY",
        fetchMethod=FetchMethod.FILEDROP,
        enabled=True,
        schedule="0 0 * * *",
        localDownloadDir="./downloads",
        cleanupAfterIngest=False,
        filedrop=FileDropConfig(
            directory="./sftp_data",
            pattern="settlement_ACMEPAY_*.csv"
        )
    )
    doc = fetch_config.model_dump(by_alias=True)
    doc["_id"] = str(doc["_id"])
    await fetch_repo._collection.insert_one(doc)
    print("Fetch Config saved.")

    print("Seeding approved ACMEPAY mapping config...")
    await mapping_repo.create(MappingConfig(
        partner="ACMEPAY",
        workflowType="UPC",
        fileType=FileType.SETTLEMENT,
        sheetName="Sheet1",
        startRow=2,
        configVersion="ACMEPAY_v01",
        status=MappingConfigStatus.APPROVED,
        approvedAt=datetime.now(timezone.utc),
        approvedBy="demo-seed",
        fieldMappings=[
            FieldMapping(path="id", column=1, type=FieldMappingType.STRING, required=True),
            FieldMapping(path="trace", column=2, type=FieldMappingType.STRING),
            FieldMapping(path="amount", column=3, type=FieldMappingType.DECIMAL, required=True),
            FieldMapping(path="status", column=4, type=FieldMappingType.MAPPING, required=True,
                         mapping={"SUCCESS": "SUCCESS", "FAILED": "FAILED", "REVERSED": "REVERSED"}),
            FieldMapping(path="transDate", column=5, type=FieldMappingType.DATE),
            FieldMapping(path="currency", type=FieldMappingType.CONSTANT, constant="VND"),
        ],
        configHealth={"stale": False, "status": "APPROVED", "confidence": 1.0, "reasoning": "Sprint 1 demo fixture."},
    ))
    print("Approved mapping saved.")

    # --- Prepare File Drop (in ./sftp_data) ---
    print("Creating partner file drop settlement_ACMEPAY_20240707.csv in ./sftp_data...")
    sftp_dir = Path("./sftp_data")
    sftp_dir.mkdir(exist_ok=True)
    file_path = sftp_dir / "settlement_ACMEPAY_20240707.csv"

    partner_rows = [
        ["transaction_id", "ref_no", "payment_amount", "txn_status", "created_time"],
        ["ACMEPAY_TXN_001", "ACMEPAY_TXN_001", "50000", "SUCCESS", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_002", "ACMEPAY_TXN_002", "100000", "SUCCESS", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_003", "ACMEPAY_TXN_003", "150000", "SUCCESS", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_004", "ACMEPAY_TXN_004", "200000", "SUCCESS", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_005", "ACMEPAY_TXN_005", "300000", "SUCCESS", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_006", "ACMEPAY_TXN_006", "500000", "SUCCESS", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_007", "ACMEPAY_TXN_007", "1000000", "SUCCESS", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_008", "ACMEPAY_TXN_008", "10000", "FAILED", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_009", "ACMEPAY_TXN_009", "20000", "FAILED", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_010", "ACMEPAY_TXN_010", "75000", "REVERSED", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_011", "ACMEPAY_TXN_011", "150000", "SUCCESS", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_012", "ACMEPAY_TXN_012", "240000", "SUCCESS", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_013", "ACMEPAY_TXN_013", "80000", "FAILED", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_014", "ACMEPAY_TXN_014", "90000", "SUCCESS", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_015", "ACMEPAY_TXN_015", "110000", "REVERSED", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_019", "ACMEPAY_TXN_019", "18000", "SUCCESS", "2024-07-07 12:00:00"],
        ["ACMEPAY_TXN_020", "ACMEPAY_TXN_020", "28000", "SUCCESS", "2024-07-07 12:00:00"],
    ]

    with open(file_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(partner_rows)
    print(f"File created successfully at {file_path}.")
    print("\nInitialization Complete! Please go to the Automation tab, locate ACMEPAY, and click 'Run Now'.")

    client.close()

if __name__ == "__main__":
    asyncio.run(seed_acmepay_case())
