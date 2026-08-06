import asyncio
from datetime import UTC, datetime
from bson.decimal128 import Decimal128

from src.config.settings import settings
from src.domain.internal_transaction.models import InternalTransaction
from src.infrastructure.postgres.internal_transaction_repository import InternalTransactionRepository
from motor.motor_asyncio import AsyncIOMotorClient


def _from_mongo_document(document: dict) -> InternalTransaction:
    amount = document["amount"]
    if isinstance(amount, Decimal128):
        amount = amount.to_decimal()
    return InternalTransaction(
        _id=str(document["_id"]),
        partner=document["partner"],
        partnerTxnId=document["partnerTxnId"],
        amount=amount,
        currency=document.get("currency", "VND"),
        status=document["status"],
        transactionTime=document["transactionTime"],
        createdAt=document.get("createdAt") or datetime.now(UTC),
        updatedAt=document.get("updatedAt") or datetime.now(UTC),
    )


async def sync():
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    repository = InternalTransactionRepository()

    try:
        documents = []
        async for document in db["internal_transaction"].find():
            documents.append(_from_mongo_document(document))

        print(f"Found {len(documents)} internal transactions in legacy MongoDB.")
        if not documents:
            return

        for partner in {document.partner for document in documents}:
            await repository.delete_by_partner(partner)

        inserted = await repository.insert_many(documents)
        print(f"Successfully migrated {inserted} internal transactions to PostgreSQL.")
    finally:
        client.close()

if __name__ == "__main__":
    asyncio.run(sync())
