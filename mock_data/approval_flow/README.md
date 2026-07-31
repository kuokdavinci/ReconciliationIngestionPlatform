Approval flow test fixtures.

Files:
- `VNPAY_baseline_approved.csv`
  - Matches the seeded `VNPAY` approved config in `docker/init-mongo.js`
  - Use this first if your current `VNPAY` config has never had a `structureSignature` bootstrapped
- `VNPAY_structure_changed_pending_approval.csv`
  - Same business data shape, but different header names and one extra `Channel` column
  - Use this after the baseline run to trigger a `PENDING_APPROVAL` proposal while the existing approved config remains the runtime config
- `ACMEPAY_no_approved_config.csv`
  - Use with partner `ACMEPAY` to test the deterministic blocked path when no approved config exists

Suggested order:
1. Run or upload `VNPAY_baseline_approved.csv` with partner `VNPAY`
2. Then run `VNPAY_structure_changed_pending_approval.csv` with partner `VNPAY`
3. Then run `ACMEPAY_no_approved_config.csv` with partner `ACMEPAY`
