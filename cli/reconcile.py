"""Reconciliation CLI handler."""

from datetime import datetime, timezone
from decimal import Decimal

from src.core.enums import TransactionStatus
from src.domain.internal_transaction.models import InternalTransaction
from src.domain.reconciliation.models import ReconciliationResult
from src.infrastructure.postgres.internal_transaction_repository import (
    InternalTransactionRepository,
)
from src.reconciliation.engine import ReconciliationEngine
from cli import get_db, init_databases


async def run_reconciliation(partner: str, date_str: str, seed_mock: bool = False):
    """Handle --reconcile and --seed-mock CLI commands.

    Seeds mock internal transactions if requested, then runs reconciliation.
    """
    db, client = await get_db()
    await init_databases(db)

    recon_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    if seed_mock:
        print("Seeding mock internal transactions...")
        repo = InternalTransactionRepository()
        # Clear old mock data for clean run
        await repo.delete_by_partner(partner)

        await repo.insert_many(
            [
                InternalTransaction(
                    _id="internal_matched_01",
                    partner=partner,
                    partnerTxnId="2407055711887385978413624",
                    amount=Decimal("259200"),
                    status=TransactionStatus.SUCCESS,
                    transactionTime=recon_date,
                ),
                InternalTransaction(
                    _id="internal_amt_mismatch_01",
                    partner=partner,
                    partnerTxnId="2407055711887385978413625",
                    amount=Decimal("100000"),
                    status=TransactionStatus.SUCCESS,
                    transactionTime=recon_date,
                ),
                InternalTransaction(
                    _id="internal_missing_partner_01",
                    partner=partner,
                    partnerTxnId="internal_only_txn_999",
                    amount=Decimal("15000"),
                    status=TransactionStatus.SUCCESS,
                    transactionTime=recon_date,
                ),
            ]
        )
        print("Mock internal transactions seeded successfully.")

    print(f"Executing reconciliation for partner {partner} on {date_str}...")
    engine = ReconciliationEngine(db)
    results = await engine.reconcile(partner, recon_date)
    print(f"Reconciliation finished. Total results generated/updated: {len(results)}")
    for r in results:
        if isinstance(r, ReconciliationResult):
            print(
                f"  - Key: {r.partner_txn_id} -> Status: {r.reconciliation_status} "
                f"(Partner Amt: {r.partner_amount}, Internal Amt: {r.internal_amount})"
            )
        else:
            print(
                f"  - Key: {r.get('partner_txn_id')} -> Status: "
                f"{r.get('reconciliation_status')} (Partner Amt: {r.get('partner_amount')}, "
                f"Internal Amt: {r.get('internal_amount')})"
            )
