import asyncio
from src.config.settings import settings
from src.models.internal_transaction import InternalTransactionRepository
from motor.motor_asyncio import AsyncIOMotorClient

async def sync():
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    
    repo = InternalTransactionRepository(db)
    
    # 1. Fetch all internal transactions from MongoDB
    all_mongo_docs = []
    async for doc in repo.collection.find():
        all_mongo_docs.append(repo._from_mongo(doc))
        
    print(f"Found {len(all_mongo_docs)} internal transactions in MongoDB.")
    
    if not all_mongo_docs:
        return
        
    # 2. Clear Postgres internal transactions for clean sync
    from sqlalchemy import delete
    from src.models.postgres import InternalTransactionTable
    async with repo.engine.begin() as conn:
        await conn.execute(delete(InternalTransactionTable))
        
    # 3. Write to PostgreSQL using insert_many (which writes to PG since use_postgres=True)
    inserted = await repo.insert_many(all_mongo_docs)
    print(f"Successfully sync'ed {inserted} internal transactions to PostgreSQL!")

if __name__ == "__main__":
    asyncio.run(sync())
