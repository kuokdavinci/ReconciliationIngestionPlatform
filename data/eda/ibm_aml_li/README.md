# IBM AML — LI Small

EDA dataset storage for the **IBM Transactions for Anti Money Laundering (AML)**
dataset.

## Source

- Provider: Kaggle
- Dataset owner: `ealtman2019`
- Dataset: IBM Transactions for Anti Money Laundering (AML)
- Subset: `LI Small`
- URL: https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml/data

## Directory layout

| Directory | Purpose | Git policy |
|---|---|---|
| `raw/` | Original Kaggle download | Ignored |
| `interim/` | Local cleaned/canonicalized data | Ignored |
| `profiles/` | EDA summaries and quality profiles | Track reproducible outputs |
| `manifest.yaml` | Provenance, version and checksum metadata | Tracked |

The EDA notebook will live under
`notebooks/ibm_aml_transaction_eda.ipynb`.

## Usage rules

- Do not commit the raw dataset before checking its Kaggle license and
  redistribution terms.
- Record the downloaded file name, dataset version, download date and SHA-256
  checksum in `manifest.yaml`.
- Keep transformed data separate from the original download.
- Do not use this dataset as a production partner settlement source; it is for
  EDA and data-quality profiling only.

