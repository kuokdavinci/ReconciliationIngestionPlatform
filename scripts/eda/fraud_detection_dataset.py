"""Current source-dataset configuration for the generic quality profiler."""

from pathlib import Path

from scripts.eda.quality_profile import QualityProfileSpec


DEFAULT_INPUT = Path("data/eda/fraud_detection/raw/Fraud Detection Dataset.csv")
DEFAULT_OUTPUT_DIR = Path("data/eda/fraud_detection/profiles")

FRAUD_DATASET_SPEC = QualityProfileSpec(
    name="Fraud Detection Dataset",
    expected_columns=(
        "transaction_id",
        "timestamp",
        "customer_id",
        "card_id",
        "device_id",
        "ip_address",
        "merchant_id",
        "merchant_category",
        "merchant_country",
        "merchant_city",
        "merchant_latitude",
        "merchant_longitude",
        "transaction_type",
        "amount",
        "currency",
        "is_fraud",
        "fraud_type",
    ),
    required_columns=frozenset({"transaction_id", "timestamp", "amount", "currency"}),
    primary_key="transaction_id",
    identifier_columns=frozenset(
        {
            "transaction_id",
            "customer_id",
            "card_id",
            "device_id",
            "ip_address",
            "merchant_id",
        }
    ),
    categorical_columns=frozenset(
        {
            "merchant_category",
            "merchant_country",
            "merchant_city",
            "transaction_type",
            "currency",
            "is_fraud",
            "fraud_type",
        }
    ),
    numeric_columns=frozenset(
        {"amount", "merchant_latitude", "merchant_longitude"}
    ),
    datetime_columns=frozenset({"timestamp"}),
    amount_column="amount",
    timestamp_column="timestamp",
)
