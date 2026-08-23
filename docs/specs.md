# CommSec Pairing

## Ground-Rules

* **Ground Rule 0 (Data Privacy & Isolation)**: The `data/` directory is listed in `.gitignore` and may contain sensitive financial data. Developers and users may ask to perform calculations on files and directories there. However, care **MUST** be given not to leak any info from `data/` into the codebase (in `src/`, `tests/`, or in documentation).
* No reading of `.env` or other key files (if any).
* Always use *relative path from repo root*. 
* Create if not exists, and always use the `.venv` directory using python 3.12 (using conda env py312) at repo-root. 

## Context

Australian financial year or tax year, FY $k+1$, is from July 1st of year $k-1$ to June 30th $k$. For example, FY 2026 is from July 1st, 2025 to June 30th, 2025. 

Capital Gains (for taxation purposes) are calculated as follow: 
* If an asset is held for 12 months or less, the capital gain is 100% of the gain. 
* Else, the capital gain is 50% of the gain.

The pairing of buy to sell plays a very important role as it is allowed to identify and map each unit of the sold securities to the purchased securities. It is NOT necessarily FIFO or LIFO. It is more like bipartite graph matching problem. The goal is to minimize the tax liability for the current tax year. **However, pairing a unit bought with *more than one* units of sold securities is NOT allowed.**

## Data

The input data is available at `data` directory and it includes two entities' share holding (using CommSec brokerage account). 

This project will invoked once a year. Since a unit cannot be mapped multiple times, there should be a data structure to keep track of the mapping. 

**Task 1:** Identify a data structure (file format) to store the mapping of buy to sell. This data structure will be updated year after year.

### Data Integrity Checks

There are going to be at least one transaction history csv file (such as `data/<entity>/Transactions_*.csv`). Note that, they may overlap. 

**Task 2:** Write a python script to union the transaction history (for each entity) and deduplicate the overlaps. 

**Task 3:** Write a python script, for each entity, using the transaction history as "ground truth", verify the completeness of the contracts (pdf files). Output Errors (but don't halt the program) for missing contracts and Warnings (there is a contract but the corresponding line in transaction history is missing). 

### CGT Matching Engine

**Task 4:** Write a python module and CLI command to perform bipartite trade matching for a given financial year to minimize Capital Gains Tax liability (supporting `granular` discrete-unit MILP optimization, `whole-buy` intact parcel allocation, and `fifo` matching).

### Reporting & Audit Trail Exports

**Task 5:** Write a python module and CLI command to deterministically export persistent mapping ledgers into multi-format reports (accountant CSVs and Markdown audit trail).