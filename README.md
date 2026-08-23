# CommSec Pairing

A Python-based Capital Gains Tax (CGT) pairing and portfolio management engine for CommSec trading accounts.

---

## Core Capabilities
- **Transaction Ingestion & Deduplication**: Unions multiple overlapping transaction history CSVs per entity and deduplicates records using a 5-tuple fingerprint `(reference, date, security, units, action)`.
- **Contract Verification**: Reconciles transaction records against contract note PDFs by inspecting text streams (completely file-name agnostic), flagging missing files (Errors) or unreferenced contracts (Warnings).
- **Persistent Unit-Level Mapping**: Maintains a multi-year audit ledger of buy-to-sell unit allocations ensuring strict $1 \to [0, 1]$ unit conservation across tax years.
- **Multi-Strategy CGT Matching Engine**:
  - `granular` *(Default)*: Mixed-Integer Linear Program (MILP) minimizing net taxable capital gains across discrete share units ($M \leftrightarrow N$).
  - `whole-buy`: 0-1 Knapsack MILP allocating intact buy contract parcels ($1 \to \text{Many}$).
  - `fifo`: Unit-based chronological First-In, First-Out allocation.

---

## Expected Input Directory Structure

The CLI expects portfolio data to be placed in an entity directory (under `data/<entity-name>/` or any custom path passed via `--dir <path>`):

```
data/
└── <entity-name>/                  # e.g., entity-1, portfolio-a
    ├── Transactions_*.csv          # CommSec transaction history CSV(s) (can overlap)
    ├── Contract *.pdf              # CommSec confirmation note PDFs (any filename)
    └── mapping.json                # (Optional) Generated persistent mapping ledger
```

---

## Quick Start

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies (in editable mode)
pip install -e .[dev]

# Run tests
pytest

# 1. Union & deduplicate overlapping CSVs (optional export)
python -m commsec_pairing.cli union-csv --entity <entity-name> --output-file data/<entity-name>/unified_transactions.csv

# 2. Verify contract note completeness against CSV ground truth
python -m commsec_pairing.cli verify --entity <entity-name>
# or using an explicit unified CSV:
python -m commsec_pairing.cli verify --entity <entity-name> --transactions-csv data/<entity-name>/unified_transactions.csv

# 3. Run trade matching for a financial year (e.g., FY 2025)
python -m commsec_pairing.cli match --entity <entity-name> --fy 2025 --strategy granular --save
# or using an explicit unified CSV:
python -m commsec_pairing.cli match --entity <entity-name> --fy 2025 --transactions-csv data/<entity-name>/unified_transactions.csv --save

# 4. Check inventory and ledger status
python -m commsec_pairing.cli status --entity <entity-name>
```

---

## Philosophy & Disclaimer

This project is 100% free and open-source software provided on an "as-is" basis without warranties. It is a mathematical calculation tool and **does not provide financial, legal, or tax advice**. 

This independent project and its creator(s) have **no affiliation, authorization, endorsement by, or official connection with Commonwealth Securities Limited (CommSec), Commonwealth Bank of Australia (CBA), or any of their subsidiaries or parent entities**.

For full details on project scope, target audiences, and design principles, see [WHY.md](WHY.md).
