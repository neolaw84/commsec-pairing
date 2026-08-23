# AGENTS.md

Welcome to the **CommSec Pairing** codebase. This guide defines operational rules, architectural principles, domain context, and conventions for AI agents and human developers collaborating on this repository.

---

## 1. Ground Rules

0. **Data Privacy & Isolation (Rule Zero)**: The `data/` directory is listed in `.gitignore` and contains sensitive financial and portfolio data. Developers and users may request calculations, pairing, and processing on files located there. However, care **MUST** be taken never to leak, commit, or hardcode information from `data/` into the codebase (in `src/`, `tests/`, or documentation).
1. **Privacy & Anonymization**: Never store, hardcode, or commit real human names, personal identifiers, or account numbers. Always use generic placeholders (e.g., `entity-1`, `entity-a`, `<entity>`).
2. **No Secret / Key Access**: Never attempt to read, inspect, or parse `.env`, `.env.*`, `*.key`, `*.pem`, or other credential files.
3. **Relative Paths**: Always use paths relative to the repository root (e.g., `data/<entity>/`, `docs/specs.md`, `src/commsec_pairing/`).
4. **Dedicated Python 3.12 Virtual Environment**:
   - Always run Python code and CLI tools using the `.venv` directory located at the repository root (`.venv/bin/python`, `.venv/bin/pytest`).
   - If `.venv` needs recreation, activate the `py312` conda environment (Python 3.12) and run: `conda run -n py312 python -m venv .venv`. If the `py312` environment does not exist, create it first with `conda create -n py312 python=3.12`.

---

## 2. Input Data Directory Structure

Each portfolio entity is stored under a dedicated subfolder within `data/` (e.g., `data/<entity>/` or a custom path specified via `--dir <path>`):

```
data/
└── <entity-name>/                      # Portfolio entity directory (e.g. entity-1, portfolio-a)
    ├── Transactions_*.csv              # One or more transaction history CSVs (can be overlapping)
    ├── Contract *.pdf                  # CommSec trade confirmation contract PDFs (any filename)
    └── mapping.json                    # (Optional) Persistent state ledger
```

### Input File Requirements:
1. **Transaction CSVs**:
   - CommSec 6-column export: `Date, Reference, Details, Debit ($), Credit ($), Balance ($)`.
   - Trade transactions begin with contract reference `C<ID>` (e.g. `C103966253`) with Details format: `<B|S> <UNITS> <TICKER> @ <PRICE>`.
2. **Contract Note PDFs**:
   - CommSec Confirmation PDFs containing `CONFIRMATION NO <ID>`, action (`BOUGHT` / `SOLD`), `UNITS`, `SECURITY`, and `DATE`.
   - File names can be arbitrary; parsing relies strictly on PDF text streams.

---

## 3. Domain & Mathematical Foundations

### Australian Financial Year (Tax Year)
- Australian FY $k+1$ begins on **July 1st of year $k$** and ends on **June 30th of year $k+1$** (e.g., FY 2026 is `2025-07-01` to `2026-06-30`).
- Capital gains/losses are evaluated and declared on a per-financial-year basis based on the **trade date** of the SELL transaction.

### Capital Gains Tax (CGT) Rules
- **Short-Term Holding ($\le 12$ months / $\le 365$ days)**: $100\%$ of the net capital gain is taxable.
- **Long-Term Holding ($> 12$ months / $> 365$ days)**: $50\%$ CGT discount applies ($50\%$ of the net capital gain is taxable).
- **Capital Losses**: Short-term and long-term capital losses offset capital gains.

### Unit Pairing & Matching Multiplicities
1. **Contract to Units ($1 \to N$)**: A contract note represents a parcel of $N$ discrete shares.
2. **Contract to Contract ($M \leftrightarrow N$)**: A sell contract can be fulfilled across multiple buy contracts; a buy contract can be liquidated across multiple sell contracts.
3. **Unit to Unit ($1 \to [0, 1]$)**: Each purchased share unit $u_{\text{buy}}$ can be mapped to at most **one** sold unit $u_{\text{sell}}$ across the lifetime of the portfolio ($0$ if currently held/unsold). **Pairing a purchased unit with more than one sold unit is strictly forbidden.**
4. **Matching Strategies**:
   - `granular` (Default): Mixed-Integer Linear Program (MILP) minimizing net taxable capital gain.
   - `whole-buy`: 0-1 Knapsack MILP allocating intact buy contract parcels ($1 \to \text{Many}$).
   - `fifo`: Unit-based chronological First-In, First-Out allocation.

---

## 4. Repository Architecture

```
commsec-pairing/
├── .venv/                         # Python 3.12 virtual environment
├── .gitignore                     # Git ignore file (excludes data/ and virtualenv)
├── AGENTS.md                      # Agent operational guide & conventions
├── pyproject.toml                 # Packaging, dependencies, tool configurations
├── README.md                      # Quick-start documentation
├── docs/                          # Specifications and technical documentation
│   ├── specs.md                   # Core product requirements
│   ├── architecture.md            # System architecture & mathematical pairing formulation
│   ├── data_contracts.md          # Input/output data schemas & formats
│   └── tasks.md                   # Task breakdown & implementation roadmap
├── src/
│   └── commsec_pairing/           # Core Python package
│       ├── __init__.py
│       ├── models.py              # Pydantic domain models & contracts
│       ├── ingester.py            # CSV ingestion, union, and deduplication
│       ├── verifier.py            # PDF contract reconciliation & error/warning reporter
│       ├── storage.py             # Persistent buy-sell mapping & inventory store
│       ├── matcher.py             # CGT minimization and FIFO pairing engine
│       ├── exporter.py            # Multi-format CSV & Markdown report generator
│       └── cli.py                 # Rich CLI entrypoint
└── tests/                         # Automated test suite
    ├── conftest.py                # Shared pytest fixtures & test data
    ├── test_ingester.py           # Ingestion & deduplication unit tests
    ├── test_verifier.py           # Contract verification unit tests
    ├── test_models_and_storage.py # Persistence & unit conservation tests
    ├── test_matcher.py            # Matching optimization & FIFO tests
    └── test_exporter.py           # Reporting & CSV/Markdown export tests
```

---

## 5. Key Developer & Agent Workflows

### Virtual Environment & Dependencies
```bash
# Activate environment
source .venv/bin/activate

# Install / update package in editable mode with dev dependencies
pip install -e .[dev]
```

### Running Tests & Linting
```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=commsec_pairing

# Run linter
ruff check .
```

### CLI Commands
```bash
# Run CLI help
python -m commsec_pairing.cli --help

# Verify contract completeness against transaction CSVs
python -m commsec_pairing.cli verify --entity <entity-name>
# or using a direct path
python -m commsec_pairing.cli verify --dir data/<entity-name>

# Union and deduplicate overlapping transaction CSVs
python -m commsec_pairing.cli union-csv --entity <entity-name> --output-file data/<entity-name>/unified_transactions.csv

# Run CGT trade matching for a financial year
python -m commsec_pairing.cli match --entity <entity-name> --fy 2025 --strategy granular --save

# Inspect persistent mapping ledger status
python -m commsec_pairing.cli status --entity <entity-name>

# Export accountant CSVs and Markdown audit report
python -m commsec_pairing.cli export --dir data/matched-<entity-name>
# or specify explicit output files
python -m commsec_pairing.cli export --entity <entity-name> --output-dir exports/
```

---

## 6. Verification & Integrity Checklist

When writing or modifying code:
- [ ] **Privacy Adherence**: Ensure no personal names or real credentials are written.
- [ ] **First-Principles Adherence**: Check requirements against domain rules (Australian FY, CGT discount, unit conservation).
- [ ] **Interface Primacy**: Check producer signatures and schema contracts before updating callers.
- [ ] **Completeness**: Return non-zero exit codes on CLI failure, output structured Rich tables and logs.
- [ ] **Empirical Validation**: Run `pytest` and verify that all tests pass without errors.
