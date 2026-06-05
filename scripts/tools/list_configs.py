import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from src.config.settings import settings

async def main():
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    print("=== Mapping Configs in DB ===")
    async for config in db.reconciliation_mapping_config.find():
        print(f"Partner: {config.get('partner')}, Version: {config.get('version')}, Sheet: {config.get('sheetName') or config.get('sheet_name')}, Start Row: {config.get('startRow') or config.get('start_row')}")
        # Print mappings
        mappings = config.get('fieldMappings') or config.get('field_mappings') or []
        print("Mappings:")
        for m in mappings:
            col = m.get('column')
            path = m.get('path')
            type_ = m.get('type')
            constant = m.get('constant')
            print(f"  - {path}: type={type_}, col={col}, constant={constant}")
            if m.get('mapping'):
                print(f"    mapping rules: {m.get('mapping')}")

asyncio.run(main())
