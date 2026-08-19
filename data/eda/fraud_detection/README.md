# Fraud Detection Dataset — Sprint 3 EDA

This directory contains the canonical local dataset and reproducible profile
outputs for Sprint 3 Workstream A.

| Directory | Purpose | Git policy |
|---|---|---|
| `raw/` | Original local CSV used by the Kaggle notebook/profile | Ignored |
| `interim/` | Temporary slices or controlled analysis inputs | Ignored |
| `profiles/` | Machine-readable and human-readable profile outputs | Tracked |
| `manifest.yaml` | Provenance and checksum metadata | Tracked |

The raw file is intentionally kept local. The exploratory notebook remains a
Kaggle-only artefact; the repository-side profile script is the reproducible
evidence source for Workstream A.

This public/synthetic dataset is suitable for EDA and ingestion quality
profiling only. It is not a production settlement source. Verify the source
license before redistribution.
