"""Architecture checks for the PostgreSQL persistence boundary."""

from src.infrastructure.persistence.postgres_connection import (
    get_pg_engine as infrastructure_get_pg_engine,
)
from src.infrastructure.persistence.postgres_schema import (
    Base as infrastructure_base,
    InternalTransactionTable as infrastructure_internal_table,
    PartnerTransactionTable as infrastructure_partner_table,
    ReconciliationResultTable as infrastructure_result_table,
)
from src.models.postgres import (
    Base,
    InternalTransactionTable,
    PartnerTransactionTable,
    ReconciliationResultTable,
    get_pg_engine,
)


def test_legacy_postgres_module_is_a_compatibility_facade() -> None:
    """Legacy imports must resolve to the infrastructure-owned definitions."""

    assert Base is infrastructure_base
    assert PartnerTransactionTable is infrastructure_partner_table
    assert InternalTransactionTable is infrastructure_internal_table
    assert ReconciliationResultTable is infrastructure_result_table
    assert get_pg_engine is infrastructure_get_pg_engine
