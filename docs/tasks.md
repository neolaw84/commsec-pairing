# Task Breakdown & Implementation Roadmap

This document outlines the roadmap for the tasks specified in `docs/specs.md`.

---

## Task 1: Persistent Buy-to-Sell Mapping Data Structure

### Objective
Define and implement a serializable, versioned data structure to store unit-level mappings between buy and sell transactions across multiple tax years.

### Requirements & Acceptance Criteria
- [x] Schema models $1 \to N$ contract-to-units and $M \leftrightarrow N$ contract-to-contract relationships.
- [x] Enforces strict $1 \to [0, 1]$ unit-level conservation (a purchased unit can never be paired with more than one sold unit).
- [x] Tracks inventory ledger with remaining unexhausted units per buy contract.
- [x] Calculates and stores holding periods, 50% CGT discount eligibility, gross gain/loss, and net taxable gain/loss.
- [x] Supported by Pydantic models in `src/commsec_pairing/models.py` and persistent storage manager in `src/commsec_pairing/storage.py`.

---

## Task 2: Transaction History Union & Deduplication

### Objective
Ingest multiple potentially overlapping transaction history CSV files for each entity, union their records, and deduplicate overlaps.

### Requirements & Acceptance Criteria
- [x] Scan and discover all `Transactions_*.csv` files in an entity's directory.
- [x] Normalize dates (`YYYY-MM-DD` / `DD/MM/YYYY`) and parse structured trade details (`B/S <qty> <ticker> @ <price>`).
- [x] Deduplicate identical transaction entries based on `(Date, Reference, Details, Debit, Credit, Balance)`.
- [x] Sort all unified transactions chronologically.
- [x] Supported by `commsec_pairing.ingester` and CLI command `python -m commsec_pairing.cli union-csv`.

---

## Task 3: Contract PDF Completeness & Verification

### Objective
Verify the completeness of contract note PDF files against the ground truth transaction CSVs for each entity.

### Requirements & Acceptance Criteria
- [x] Extract contract reference numbers from filenames (`Contract <ID>.pdf` or `YYYY-MM-DD-*-Contract <ID>.pdf`).
- [x] Reconcile trade transactions in CSV (references starting with `C`) with scanned PDF contracts.
- [x] Output **Errors** for missing contract PDFs (without halting execution).
- [x] Output **Warnings** for extra/unreferenced contract PDFs (files present on disk with no corresponding CSV trade).
- [x] Return a structured reconciliation report object with summary statistics.
- [x] Supported by `commsec_pairing.verifier` and CLI command `python -m commsec_pairing.cli verify`.

---

## Task 4: CGT Bipartite Matching Optimization Engine

### Objective
Implement the tax liability minimization engine to pair buy lots with sell lots within a target financial year.

### Requirements & Acceptance Criteria
- [x] Formulate and solve the MILP / bipartite matching optimization problem.
- [x] Strict temporal validity: never match a sell against a future buy ($D_{\text{buy}} \le D_{\text{sell}}$).
- [x] Default strategy (`granular`): minimizes tax liability (accounting for 50% discount for holding $> 365$ days and 100% loss offset for negative gains).
- [x] Whole Buy Contract strategy (`whole-buy`): matches whole buy contracts without splitting ($1 \to \text{Many}$).
- [x] FIFO strategy (`fifo`): unit-based chronological First-In, First-Out allocation ($M \leftrightarrow N$).
- [x] Preserves identical persistent mapping store schema across all strategies.
- [x] Supports multi-year chaining via `--input-mapping` and `--output-mapping`.
- [x] Supported by `commsec_pairing.matcher` and CLI command `python -m commsec_pairing.cli match`.
