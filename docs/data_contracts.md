# Data Contracts & Formats

This document defines the expected input directory structure, input CSV schemas, contract note PDF parsing rules, and the persistent buy-sell mapping store schema.

---

## 1. Expected Input Directory Structure

The system is organized around entity directories (e.g. `data/<entity-name>/` or any directory passed via `--dir <path>`):

```
data/
└── <entity-name>/                     # Portfolio directory (e.g., entity-1, fund-a)
    ├── Transactions_*.csv             # CommSec 6-column transaction history CSV(s)
    ├── *.pdf                          # CommSec trade confirmation PDFs (any filename)
    └── mapping.json                   # (Optional) Persistent state ledger
```

---

## 2. CommSec Transaction CSV Contract

Located at `data/<entity>/Transactions_<account_id>_<start_date>_<end_date>.csv`.

### CSV Columns

| Column | Type | Description | Example |
|---|---|---|---|
| `Date` | String (`DD/MM/YYYY`) | Settlement/Execution Date | `05/05/2025` |
| `Reference` | String | Transaction identifier. Contracts begin with `C` (e.g. `C161775901`), transfers with `P`/`R` | `C161775901` |
| `Details` | String | Trade action or transfer description | `S 29 IHHY @ 92.400000`, `Direct Transfer - Payee BENEFICIARY` |
| `Debit($)` | Float / Empty | Outflow (e.g., share purchases, cash withdrawals) | `5130.16` |
| `Credit($)` | Float / Empty | Inflow (e.g., share sales, cash deposits) | `2669.60` |
| `Balance($)` | Float | Cash account running balance | `0.00` |

### Deduplication Fingerprint Contract
For trade contracts (`Reference` starts with `C`), deduplication is strictly based on the 5-field trade composite key:
$$\text{Trade Fingerprint} = (\text{Reference}, \text{Date}, \text{Security Ticker}, \text{Units}, \text{Action (B/S)})$$

For non-trade rows (bank transfers, interest, dividends), deduplication is based on:
$$\text{Transfer Fingerprint} = (\text{Reference}, \text{Date}, \text{Details}, \text{Debit}, \text{Credit})$$

---

## 3. Contract Note PDF Identification

Located at `data/<entity>/`.

### Content-First Identification Rule
The verifier inspects **PDF file contents directly** using `pypdf`, extracting:
- `CONFIRMATION NO` (e.g., `94615705` $\to$ `C94615705` canonical key matching CSV `Reference`).
- Action (`BOUGHT` / `SOLD`).
- Security ticker (`A200`, `IVV`, `VAS`, etc.).
- Units and Trade Date.

**File names on disk are completely ignored** for identification, ensuring resilience against misnamed or unrenamed files.

---

## 4. Persistent Buy-Sell Mapping Store Schema

Persisted as a JSON ledger (e.g. `data/<entity>/mapping.json` or custom `--output-mapping` path).

```json
{
  "version": "1.0",
  "entity": "entity-1",
  "last_updated": "2026-08-23T17:20:00Z",
  "matches": [
    {
      "match_id": "m_2026_0001",
      "financial_year": 2026,
      "security": "A200",
      "matched_units": 25,
      "buy": {
        "contract_ref": "C139634377",
        "trade_date": "2022-12-21",
        "unit_price_aud": 118.50,
        "allocated_brokerage_aud": 0.00
      },
      "sell": {
        "contract_ref": "C177620801",
        "trade_date": "2026-08-04",
        "unit_price_aud": 135.20,
        "allocated_brokerage_aud": 0.00
      },
      "holding_period_days": 1322,
      "cgt_discount_eligible": true,
      "gross_gain_loss_aud": 417.50,
      "taxable_gain_loss_aud": 208.75,
      "strategy": "granular"
    }
  ],
  "buy_inventory": [
    {
      "contract_ref": "C139634377",
      "trade_date": "2022-12-21",
      "security": "A200",
      "unit_price_aud": 118.50,
      "total_units": 50,
      "matched_units": 25,
      "remaining_units": 25,
      "is_exhausted": false
    }
  ]
}
```

### Invariants
1. `remaining_units == total_units - matched_units`
2. `remaining_units >= 0` for all inventory lots.
3. For any buy lot $c$, $\sum_{m \in \text{matches}} m.\text{matched\_units} \le c.\text{total\_units}$.
4. For any sell transaction $s$, $\sum_{m \in \text{matches}} m.\text{matched\_units} == s.\text{total\_units}$.

---

## 5. Generated Report Contracts & Formats

Generated via `python -m commsec_pairing.cli export` (implemented by `commsec_pairing.exporter`).

### A. Granular Matched Parcels CSV (`matched_parcels.csv`)
Flat 1-row-per-matched-parcel audit trail for accounting systems and spreadsheet analysis:

| Column | Type | Description | Example |
|---|---|---|---|
| `FinancialYear` | Integer | Australian tax year of the disposal | `2026` |
| `Security` | String | Security ticker code | `SOL` |
| `MatchedUnits` | Integer | Discrete share units in this match leg | `67` |
| `BuyContractRef` | String | Buy contract confirmation reference | `C144815020` |
| `BuyTradeDate` | String (`YYYY-MM-DD`) | Date shares were acquired | `2023-08-01` |
| `BuyUnitPriceAUD` | Float (2 dec) | Purchase price per share | `32.83` |
| `SellContractRef` | String | Sell contract confirmation reference | `C165524615` |
| `SellTradeDate` | String (`YYYY-MM-DD`) | Date shares were disposed | `2025-09-02` |
| `SellUnitPriceAUD` | Float (2 dec) | Sale price per share | `43.72` |
| `HoldingPeriodDays` | Integer | Calendar days held ($D_{\text{sell}} - D_{\text{buy}}$) | `763` |
| `CGTDiscountEligible` | Boolean | True if held $> 365$ days and gain $> 0$ | `True` |
| `GrossGainLossAUD` | Float (2 dec) | Nominal capital gain or loss | `729.63` |
| `TaxableGainLossAUD` | Float (2 dec) | Net taxable amount after 50% CGT discount | `364.81` |
| `Strategy` | String | Matching strategy utilized | `granular` |
| `MatchID` | String | Unique match identifier | `m_2026_0001` |

### B. Annual CGT Tax Summary CSV (`cgt_annual_tax_summary.csv`)
Aggregated per Australian Financial Year for direct copy-paste into Australian Tax Returns (Item 18: Capital Gains):

| Column | Type | Description | Example |
|---|---|---|---|
| `FinancialYear` | String | Financial year label | `FY2026` |
| `Strategy` | String | Matching strategy/strategies applied | `granular` |
| `TotalDisposals` | Integer | Total number of matched disposal legs | `2` |
| `TotalGrossGainsAUD` | Float (2 dec) | Sum of all positive nominal capital gains | `729.63` |
| `TotalGrossLossesAUD` | Float (2 dec) | Sum of all nominal capital losses | `-704.27` |
| `NetGrossGainLossAUD` | Float (2 dec) | Net nominal capital gain/loss | `25.36` |
| `CGTDiscountDeductionAUD` | Float (2 dec) | Total 50% CGT discount deduction | `364.82` |
| `NetTaxableGainLossAUD` | Float (2 dec) | Final net taxable capital gain/loss declared | `-339.46` |

### C. Audit Report Markdown (`audit_report.md`)
Human-readable documentation artifact containing:
1. **Executive Annual CGT Table**: Summary table covering all financial years with gross P/L, discount deductions, and taxable P/L.
2. **Disposal & Match Details by FY**: Tables breaking down each trade leg with contract IDs and holding days.
3. **Active Buy Inventory Ledger**: Status of all remaining purchase parcels (`🟢 Available`, `🟡 Partial`, `🔴 Exhausted`).
