"""Architecture checks for the PostgreSQL persistence boundary."""

import src.infrastructure.persistence.postgres_schema as schema_module
from src.infrastructure.persistence.postgres_connection import (
    get_pg_engine as infrastructure_get_pg_engine,
)
from src.infrastructure.persistence.postgres_schema import (
    Base as infrastructure_base,
    InternalTransactionTable as infrastructure_internal_table,
    PartnerTransactionTable as infrastructure_partner_table,
    ReconciliationResultTable as infrastructure_result_table,
)
def test_postgres_schema_and_connection_are_infrastructure_owned() -> None:
    assert schema_module.__name__ == "src.infrastructure.persistence.postgres_schema"
    assert schema_module.Base is infrastructure_base
    assert schema_module.PartnerTransactionTable is infrastructure_partner_table
    assert schema_module.InternalTransactionTable is infrastructure_internal_table
    assert schema_module.ReconciliationResultTable is infrastructure_result_table
    assert infrastructure_partner_table.__table__.metadata is infrastructure_base.metadata
    assert infrastructure_internal_table.__table__.metadata is infrastructure_base.metadata
    assert infrastructure_result_table.__table__.metadata is infrastructure_base.metadata
    assert infrastructure_get_pg_engine.__module__ == "src.infrastructure.persistence.postgres_connection"
