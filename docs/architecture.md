# Architecture Specification: CommSec Pairing

This document outlines the architectural blueprint, data flow, mathematical model, and module responsibilities for the CommSec Pairing engine.

---

## 1. System Overview

CommSec Pairing is a multi-year portfolio audit and Capital Gains Tax (CGT) optimization engine. It automates the reconciliation of brokerage transactions against contract note PDFs and solves the optimal matching of purchase lots to sale lots under Australian taxation regulations.

```
+---------------------------------------------------------------------------------------------------+
|                                        DATA INGESTION                                             |
|  +--------------------------------+                  +--------------------------------+           |
|  |  Transaction CSVs (Ground Truth)|                  |   Contract Note PDFs (Audit)   |           |
|  +--------------------------------+                  +--------------------------------+           |
|                 |                                                    |                            |
|                 v                                                    v                            |
|  +--------------------------------+                  +--------------------------------+           |
|  |       CSV Union & Dedup        |                  |      Contract PDF Parser       |           |
|  |     (commsec_pairing.ingester) |                  |     (commsec_pairing.verifier) |           |
|  +--------------------------------+                  +--------------------------------+           |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                 RECONCILIATION & INTEGRITY                                        |
|  - Compare CSV contract references (C<ID>) with scanned PDF filenames / metadata                  |
|  - Report ERRORS for missing contract PDFs (without halting)                                      |
|  - Report WARNINGS for extra / unreferenced contract PDFs                                         |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                              PERSISTENT UNIT INVENTORY STORE                                      |
|  - Tracks purchase parcels and unmapped share units year-over-year                                |
|  - Preserves 1-to-[0, 1] unit conservation across tax years                                       |
|  - Data store: mapping_<entity>.json                                                              |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                  CGT OPTIMIZATION & MATCHING ENGINE                               |
|  - Strategies:                                                                                    |
|      1. 'granular' (default): Continuous LP exploiting Total Unimodularity (TUM) to guarantee      |
|         exact integer extreme points in polynomial time (M <-> N).                                |
|      2. 'whole-buy': 0-1 Knapsack MILP allocating intact buy parcels (Buy -> Sell is 1 -> Many).  |
|         Bounded by MAX_LOTS=500, MAX_COMBINATIONS=5000, and 60s timeout.                         |
|      3. 'fifo': Unit-based First-In, First-Out chronological allocation (O(M log M + N log N)).   |
|  - Constraints:                                                                                   |
|      1. Strict temporal constraint: No future buys (Buy Date <= Sell Date)                        |
|      2. 50% CGT discount for holding period > 365 days                                            |
|      3. 100% loss offset for negative gains                                                       |
|      4. Strict unit conservation: sum(allocated_units) <= available_units                        |
|  - Chaining:                                                                                      |
|      Supports '--input-mapping' to load prior FY state and '--output-mapping' for next FY.       |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Mathematical Pairing Formulation

### Multiplicity Relations
- **Contract to Units ($1 \to N$)**: A trade contract $c$ contains $q(c)$ units of security $S$.
- **Contract to Contract ($M \leftrightarrow N$)**: Multiple buy contracts can fulfill a single sell contract, or a single buy contract can be liquidated across multiple sell contracts.
- **Unit to Unit ($1 \to [0, 1]$)**: Each individual share unit $u$ purchased in contract $c_{\text{buy}}$ can be matched with at most **one** sold share unit in contract $c_{\text{sell}}$ across all time.

### Optimization Formulation (MILP / Min-Cost Matching)
For a specific financial year $\text{FY}$, let:
- $\mathcal{B} = \{ b_1, b_2, \dots, b_m \}$ be the set of unexhausted buy lots for security $S$ executed prior to the sell dates, where each lot $b_i$ has remaining units $U_i^{\text{rem}}$, unit cost base $C_i$, and trade date $D_i^{\text{buy}}$.
- $\mathcal{S} = \{ s_1, s_2, \dots, s_n \}$ be the set of sell lots for security $S$ executed within $\text{FY}$, where each lot $s_j$ has quantity $V_j$, unit proceeds $P_j$, and trade date $D_j^{\text{sell}}$.

Let decision variable $x_{i,j} \in \mathbb{Z}_{\ge 0}$ represent the number of share units from buy lot $b_i$ allocated to sell lot $s_j$.

#### Objective Function
Minimize the total taxable capital gain for the financial year:
$$\min \sum_{i \in \mathcal{B}} \sum_{j \in \mathcal{S}} x_{i,j} \cdot \tau(b_i, s_j)$$

where the taxable gain/loss per unit $\tau(b_i, s_j)$ is defined as:
$$\text{gain}(b_i, s_j) = P_j - C_i$$

$$\tau(b_i, s_j) = \begin{cases}
0.5 \times \text{gain}(b_i, s_j) & \text{if } \text{gain}(b_i, s_j) > 0 \text{ and } (D_j^{\text{sell}} - D_i^{\text{buy}}) > 365 \text{ days} \\
1.0 \times \text{gain}(b_i, s_j) & \text{if } \text{gain}(b_i, s_j) > 0 \text{ and } (D_j^{\text{sell}} - D_i^{\text{buy}}) \le 365 \text{ days} \\
\text{gain}(b_i, s_j) & \text{if } \text{gain}(b_i, s_j) \le 0 \quad (\text{capital loss})
\end{cases}$$

#### Constraints
1. **Sell Satisfaction**: Every unit sold in the financial year must be paired with an available buy unit:
   $$\sum_{i \in \mathcal{B}} x_{i,j} = V_j \quad \forall j \in \mathcal{S}$$
2. **Buy Inventory Conservation**: Units drawn from buy lot $b_i$ cannot exceed its remaining unallocated balance:
   $$\sum_{j \in \mathcal{S}} x_{i,j} \le U_i^{\text{rem}} \quad \forall i \in \mathcal{B}$$
3. **Temporal Validity**: A sell cannot match with a buy executed after the sell date:
   $$x_{i,j} = 0 \quad \text{if } D_i^{\text{buy}} > D_j^{\text{sell}}$$
4. **Integrality**:
   $$x_{i,j} \in \mathbb{Z}_{\ge 0}$$

---

## 3. Module Responsibilities

| Module | Purpose | Key Classes / Functions |
|---|---|---|
| `commsec_pairing.models` | Pydantic data models & schemas | `Transaction`, `TradeAction`, `ContractSummary`, `MatchPair`, `PersistentMappingStore` |
| `commsec_pairing.ingester` | Ingests, normalizes, unions, and deduplicates CSV files | `load_transactions_csv`, `union_and_deduplicate`, `parse_trade_details` |
| `commsec_pairing.verifier` | Reconciles CSV ground truth against contract PDFs | `verify_entity_contracts`, `ReconciliationReport` |
| `commsec_pairing.storage` | Manages persistent state and inventory ledgers | `MappingStorageManager`, `load_mapping_store`, `save_mapping_store` |
| `commsec_pairing.matcher` | Implements the MILP / bipartite matching solver | `CGTMatcher`, `optimize_pairing_for_fy` |
| `commsec_pairing.cli` | Terminal interface with Rich formatting | `main`, `verify`, `union_csv`, `match`, `status` |
