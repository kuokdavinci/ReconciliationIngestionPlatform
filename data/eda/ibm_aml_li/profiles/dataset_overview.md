# Dataset Overview

- File: LI-Small_Trans.csv
- Rows: 6,924,049 (valid: 6,924,049)
- Columns: 11
- Size: 650,422,357 bytes
- SHA-256: f7a9940339c78b5d1476071505b5867c0f5319640b9c4279d13f531bf965319d

## Schema

| Column | Source header | Role | Nulls | Distinct | Exact | Samples |
|---|---|---:|---:|---:|:---:|---|
| Timestamp | Timestamp | datetime | 0 | 10,000 | no | 2022/09/01 00:08, 2022/09/01 00:21, 2022/09/01 00:00, 2022/09/01 00:16, 2022/09/01 00:24 |
| From Bank | From Bank | categorical | 0 | 10,000 | no | 011, 03402, 03814, 020, 012 |
| From Account | Account | identifier | 0 | 10,000 | no | 8000ECA90, 80021DAD0, 8006AD080, 8006AD530, 8006ADD30 |
| To Bank | To Bank | categorical | 0 | 10,000 | no | 011, 03402, 001120, 03814, 020 |
| To Account | Account | identifier | 0 | 10,000 | no | 8000ECA90, 80021DAD0, 8006AA910, 8006AD080, 8006AD530 |
| Amount Received | Amount Received | numeric | 0 | 10,000 | no | 3195403.00, 1858.96, 592571.00, 12.32, 2941.56 |
| Receiving Currency | Receiving Currency | categorical | 0 | 15 | yes | US Dollar, Euro, Bitcoin, Yuan, Yen |
| Amount Paid | Amount Paid | numeric | 0 | 10,000 | no | 3195403.00, 1858.96, 592571.00, 12.32, 2941.56 |
| Payment Currency | Payment Currency | categorical | 0 | 15 | yes | US Dollar, Euro, Bitcoin, Yuan, Yen |
| Payment Format | Payment Format | categorical | 0 | 7 | yes | Reinvestment, Cheque, ACH, Credit Card, Wire |
| Is Laundering | Is Laundering | label | 0 | 2 | yes | 0, 1 |

## Quality Summary

- Blank rows: 0
- Malformed rows: 0
- Null cells: 0

## Observations

- Timestamp range: 2022/09/01 00:00 → 2022/09/17 15:28
- Is Laundering distribution: {"0": 6920484, "1": 3565}

## Numeric Summary

| Column | Min | Max | Invalid |
|---|---:|---:|---:|
| Amount Received | 0.000001 | 3644853662746.95 | 0 |
| Amount Paid | 0.000001 | 3644853662746.95 | 0 |
